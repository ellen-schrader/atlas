"""Shared FastAPI dependencies.

Kept out of ``app.py`` so routers (e.g. ``maps.py``) can depend on the same token
extraction without importing the app module and creating a cycle.
"""

from __future__ import annotations

import base64
import json

from fastapi import Header, HTTPException


def _is_connector_token(token: str) -> bool:
    """Whether `token` was issued to an OAuth client (the Claude connector).

    Read without verifying the signature: this only ever *refuses* a token, and a
    forged one is rejected by Supabase further down anyway.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return False  # not a JWT we can read; Supabase will reject it
    return isinstance(claims, dict) and claims.get("client_id") is not None


def require_token(authorization: str | None = Header(default=None)) -> str:
    """Extract the bearer token from the Authorization header (401 if absent).

    Connector tokens are refused outright (403): the connector reads papers through
    the MCP server and the database's own gate, and has no business on this API —
    every endpoint here was written for the user's own browser session.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    if _is_connector_token(token):
        raise HTTPException(status_code=403, detail="Claude connections can't use this API.")
    return token


def _caller_id(token: str) -> str:
    """The token's user id, or 401."""
    from .supa import get_user_id  # lazy: keep this module import-light

    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


def require_member(token: str, team_id: str) -> str:
    """The caller's id, or 403 unless they are in this lab, for routes that read
    or write with the service role (which bypasses RLS) and so must check first.

    Without it `team_id` is the caller's to pick: the .bib import pre-flight, for
    one, would tell you whether another lab has a DOI."""
    from .supa import user_client  # lazy: keep this module import-light

    user_id = _caller_id(token)
    member = (
        user_client(token)  # as the caller, so RLS answers the question honestly
        .table("team_members")
        .select("user_id")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not member.data:
        raise HTTPException(status_code=403, detail="You are not a member of this lab.")
    return user_id


def require_feature(token: str, team_id: str, feature: str) -> str:
    """The caller's id, or 404 unless ``feature`` is on for them in this lab, so
    a dark feature is not advertised. Asked as the caller, so has_feature()
    checks membership too."""
    from .supa import user_client  # lazy: keep this module import-light

    user_id = _caller_id(token)
    ok = user_client(token).rpc("has_feature", {"t": team_id, "f": feature}).execute().data
    if ok is not True:
        raise HTTPException(status_code=404, detail="Not Found")
    return user_id
