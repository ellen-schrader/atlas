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
