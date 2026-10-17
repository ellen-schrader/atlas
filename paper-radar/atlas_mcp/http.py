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

import contextlib
import functools
import logging
import threading
import time
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
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse

from api.config import get_api_settings
from api.ratelimit import PerUserRateLimiter

from . import lab
from .papers import READ_TOOLS

log = logging.getLogger("atlas_mcp.http")

# Browser origins allowed to call the connector (Claude's own clients are server-side
# and send none). Kept in step between the transport check and CORS.
_BROWSER_ORIGINS = ["https://claude.ai", "https://claude.com"]

# Supabase signs user tokens with an asymmetric key (ES256 in prod, checked in M0).
# Never accept HS256 here: that would let anyone holding the legacy shared secret
# mint connector tokens.
_ALGORITHMS = ["ES256", "RS256"]
# Tolerated clock difference between Supabase and a machine just resumed from suspend.
_LEEWAY_SECONDS = 30
# An unrecognised key id can only make us refetch the key set this often. Without it,
# anyone could send junk tokens with random key ids and turn us into a fetch loop
# against Supabase. (Supabase rotates keys rarely; a new one is picked up within this.)
_UNKNOWN_KEY_REFETCH_SECONDS = 300
# Key-set fetches get their own small pool, apart from the tools' and the API's.
_JWKS_THREADS = anyio.CapacityLimiter(2)


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
            f"{self.issuer}/.well-known/jwks.json", lifespan=3600, timeout=5
        )
        self._last_refetch = float("-inf")
        self._refetch_lock = threading.Lock()

    def _signing_key(self, token: str) -> jwt.PyJWK:
        """The key the token names, from the cached key set (refreshed hourly).

        An unknown key id refetches the set at most once per
        _UNKNOWN_KEY_REFETCH_SECONDS, however many tokens ask.
        """
        kid = jwt.get_unverified_header(token).get("kid")
        if not kid:
            raise jwt.InvalidTokenError("token names no signing key")
        key = _find_key(self._jwks.get_jwk_set(), kid)
        if key is None:
            with self._refetch_lock:
                now = time.monotonic()
                if now - self._last_refetch < _UNKNOWN_KEY_REFETCH_SECONDS:
                    raise jwt.InvalidTokenError(f"unknown signing key {kid!r}")
                self._last_refetch = now
            key = _find_key(self._jwks.get_jwk_set(refresh=True), kid)
        if key is None:
            raise jwt.InvalidTokenError(f"unknown signing key {kid!r}")
        return key

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # Fetching the key set is blocking I/O; keep it off the event loop.
            key = await anyio.to_thread.run_sync(self._signing_key, token, limiter=_JWKS_THREADS)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=_ALGORITHMS,
                issuer=self.issuer,
                audience="authenticated",
                leeway=_LEEWAY_SECONDS,
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


def _find_key(jwk_set: jwt.PyJWKSet, kid: str) -> jwt.PyJWK | None:
    try:
        return jwk_set[kid]
    except KeyError:
        return None


# One connection pool for every caller. Each request still sends its own token: a
# postgrest client puts its headers on each request it makes, never on the shared
# httpx client (tests/test_mcp_http.py pins that).
_pool = httpx.Client(timeout=30.0, limits=httpx.Limits(max_connections=20))


def _pooled_client(token: str) -> SyncPostgrestClient:
    s = get_api_settings()
    if not (s.supabase_url and s.supabase_anon_key):
        # Say so plainly: with no anon key every query would 401 and read to the
        # user as an expired sign-in, sending them round a reconnect loop.
        raise lab.LabError("Atlas's server is misconfigured (Supabase settings missing).")
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
            client = _pooled_client(token.token)
        except lab.LabError as exc:
            return f"Error: {exc}"
        with lab.act_as(token.token, token.subject, client=client):
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
            allowed_origins=[public, *_BROWSER_ORIGINS],
        ),
    )
    for tool in READ_TOOLS:
        mcp.add_tool(as_caller(tool))
    return mcp


class Connector:
    """The hosted MCP server for one public host, as the API process runs it.

    `running()` builds and starts a fresh server for the app's lifespan (its session
    manager can be started only once, and tests may start the app more than once);
    `ConnectorHost` sends that host's requests to it.
    """

    def __init__(self, public_url: str, supabase_url: str) -> None:
        self.public_url = public_url.rstrip("/")
        self.host = (urlparse(self.public_url).hostname or "").lower()
        self.supabase_url = supabase_url
        self.asgi = None  # set while running

    @contextlib.asynccontextmanager
    async def running(self):
        mcp = build_mcp(self.public_url, self.supabase_url)
        app = mcp.streamable_http_app()
        async with mcp.session_manager.run():
            # Its own CORS policy: the API's (the web app's origins) never sees these.
            self.asgi = CORSMiddleware(
                app,
                allow_origins=[self.public_url, *_BROWSER_ORIGINS],
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
            )
            try:
                yield
            finally:
                self.asgi = None

    def serves(self, scope) -> bool:
        if scope["type"] not in ("http", "websocket"):
            return False
        for name, value in scope.get("headers", ()):
            if name == b"host":
                return value.decode("latin-1").split(":")[0].lower() == self.host
        return False


class ConnectorHost:
    """ASGI middleware sending the connector's host to it; everything else (and the
    lifespan) goes to the wrapped app. Add it outermost, so connector requests skip
    the API's own middleware — its CORS policy in particular."""

    def __init__(self, app, connector: Connector) -> None:
        self.app = app
        self.connector = connector

    async def __call__(self, scope, receive, send):
        if not self.connector.serves(scope):
            await self.app(scope, receive, send)
        elif self.connector.asgi is None:
            await PlainTextResponse("Starting up", status_code=503)(scope, receive, send)
        else:
            await self.connector.asgi(scope, receive, send)
