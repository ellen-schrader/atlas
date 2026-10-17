"""The hosted Atlas MCP server: the Claude connector, over Streamable HTTP + OAuth.

Served by the API process for one host (``mcp_public_url``, e.g.
https://mcp.labatlas.app), so it costs nothing extra to run. Read-only paper tools
only — no writes, no mood board (docs/CLAUDE_CONNECTOR_PLAN.md).

Auth: this is an OAuth *resource server*. Supabase Auth's OAuth 2.1 server issues the
tokens; we only verify them. The SDK publishes the protected-resource metadata and
answers unauthenticated requests with the 401 that starts Claude's sign-in. Each tool
call then runs as the token's user (`lab.act_as`), so RLS — and the database's
connector gate (20261017150000_connector_lockdown.sql) — decide what it can see.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from urllib.parse import urlparse

import anyio
import httpx
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from postgrest import SyncPostgrestClient
from starlette.applications import Starlette

from api.config import get_api_settings
from api.ratelimit import PerUserRateLimiter

from . import lab
from .papers import READ_TOOLS

log = logging.getLogger("atlas_mcp.http")

# Supabase signs user tokens with an asymmetric key (ES256 in prod, checked in M0).
# Never accept HS256 here: that would let anyone holding the legacy shared secret
# mint connector tokens.
_ALGORITHMS = ["ES256", "RS256"]


class SupabaseTokenVerifier(TokenVerifier):
    """Accept a Supabase access token issued to an OAuth client, verified locally.

    The signature is checked against Supabase's published JWKS (cached), so a tool
    call costs no extra round-trip to Auth. A token with no `client_id` is a web-app
    session, not a connector grant, and is refused: the web app's token has no
    business here, and only connector tokens are fenced in by the database gate.
    Revocation is enforced by that gate on every query (the session must still exist).
    """

    def __init__(self, supabase_url: str) -> None:
        self.issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        self._jwks = jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # A cache miss fetches the JWKS; keep that off the event loop.
            key = await anyio.to_thread.run_sync(self._jwks.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=_ALGORITHMS,
                issuer=self.issuer,
                audience="authenticated",
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
        except (jwt.PyJWTError, httpx.HTTPError, OSError) as exc:
            log.info("rejected token: %s", exc)
            return None
        client_id = claims.get("client_id")
        if not client_id:
            return None
        return AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=str(claims.get("scope") or "").split(),
            expires_at=int(claims["exp"]),
            subject=str(claims["sub"]),
            claims=claims,
        )


# One connection pool for every caller. Each request still sends its own token: a
# postgrest client puts its headers on each request it makes, never on the shared
# httpx client (tests/test_mcp_http.py pins that).
_pool = httpx.Client(timeout=30.0, limits=httpx.Limits(max_connections=20))


def _pooled_client(token: str) -> SyncPostgrestClient:
    s = get_api_settings()
    return SyncPostgrestClient(
        f"{s.supabase_url.rstrip('/')}/rest/v1",
        headers={"apikey": s.supabase_anon_key, "Authorization": f"Bearer {token}"},
        http_client=_pool,
    )


# Per user, across all tools: generous for a conversation, tight for a runaway loop.
_call_limiter = PerUserRateLimiter(
    max_events=60,
    window_seconds=60.0,
    error=lambda: lab.LabError("Too many Atlas requests in a minute — give it a moment."),
)


def as_caller(tool: Callable) -> Callable:
    """Run `tool` as the user whose verified token came with this request."""

    @functools.wraps(tool)
    async def wrapper(*args, **kwargs):
        token = get_access_token()
        if token is None or not token.subject:
            return "Error: Not signed in to Atlas."
        try:
            _call_limiter.check(token.subject)
        except lab.LabError as exc:
            return f"Error: {exc}"
        with lab.act_as(token.token, token.subject, client=_pooled_client(token.token)):
            return await tool(*args, **kwargs)

    return wrapper


def build_mcp(public_url: str, supabase_url: str, verifier: TokenVerifier | None = None) -> FastMCP:
    """The hosted server: read-only paper tools, each run as the caller. `verifier`
    defaults to Supabase's; tests pass a stub."""
    public = public_url.rstrip("/")
    host = urlparse(public).netloc
    mcp = FastMCP(
        "atlas",
        token_verifier=verifier or SupabaseTokenVerifier(supabase_url),
        auth=AuthSettings(
            issuer_url=f"{supabase_url.rstrip('/')}/auth/v1",
            resource_server_url=f"{public}/mcp",
        ),
        # Fly suspends idle machines, so no server-side session would survive anyway.
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, f"{host}:*"],
            allowed_origins=[public, "https://claude.ai", "https://claude.com"],
        ),
    )
    for tool in READ_TOOLS:
        mcp.add_tool(as_caller(tool))
    return mcp


def build_app(public_url: str | None = None) -> Starlette:
    """The ASGI app for the connector host. Its lifespan must run (it starts the
    MCP session manager): mount it with `api.app`'s lifespan, or serve it directly."""
    s = get_api_settings()
    return build_mcp(public_url or s.mcp_public_url, s.supabase_url).streamable_http_app()
