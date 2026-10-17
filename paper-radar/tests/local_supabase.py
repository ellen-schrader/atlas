"""Helpers for the opt-in integration tests that run against a *local* Supabase.

Not a test module. The keys are the standard local-stack demo keys (`supabase
status`) — never a real project's — and `LOCAL_URL` must be localhost.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from urllib.parse import parse_qs, urlparse

import httpx

LOCAL_URL = os.environ.get("ATLAS_IT_SUPABASE_URL", "http://127.0.0.1:54321")
AUTH = f"{LOCAL_URL}/auth/v1"
REST = f"{LOCAL_URL}/rest/v1"
ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24i"
    "LCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)
SERVICE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZp"
    "Y2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
REDIRECT = "http://localhost:33418/callback"

assert LOCAL_URL.startswith(("http://127.0.0.1", "http://localhost")), "local Supabase only"


def bearer(token: str) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}"}


def oauth_server_on() -> bool:
    return httpx.get(f"{AUTH}/.well-known/oauth-authorization-server").status_code == 200


def connector_token(web_token: str) -> tuple[str, str]:
    """(access_token, client_id): what Claude gets after the user approves a new client.

    Dynamic client registration → authorize (PKCE) → consent (as the signed-in user,
    the way the consent page will) → code exchange.
    """
    client = httpx.post(
        f"{AUTH}/oauth/clients/register",
        json={
            "client_name": "Integration test",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    ).json()
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    r = httpx.get(
        f"{AUTH}/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client["client_id"],
            "redirect_uri": REDIRECT,
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    aid = parse_qs(urlparse(r.headers["location"]).query)["authorization_id"][0]
    # The consent page: read the request (binds it to the user), then approve.
    httpx.get(f"{AUTH}/oauth/authorizations/{aid}", headers=bearer(web_token))
    approved = httpx.post(
        f"{AUTH}/oauth/authorizations/{aid}/consent",
        headers=bearer(web_token),
        json={"action": "approve"},
    ).json()
    code = parse_qs(urlparse(approved["redirect_url"]).query)["code"][0]
    tokens = httpx.post(
        f"{AUTH}/oauth/token",
        headers={"apikey": ANON},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client["client_id"],
            "code_verifier": verifier,
        },
    ).json()
    return tokens["access_token"], client["client_id"]
