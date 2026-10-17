"""The hosted MCP server — token verification and request handling (offline).

What must hold before the connector goes on the internet: only genuine connector
tokens get in, each tool call runs as the token's user, only the read-only paper tools
are served, and unauthenticated callers get the 401 that starts Claude's sign-in.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

import httpx  # noqa: E402
import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from mcp.server.auth.provider import AccessToken, TokenVerifier  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from api import embeddings  # noqa: E402
from atlas_mcp import http as mcp_http  # noqa: E402
from atlas_mcp import lab  # noqa: E402
from atlas_mcp.papers import READ_TOOLS  # noqa: E402

SUPABASE = "https://project.supabase.test"
ISSUER = f"{SUPABASE}/auth/v1"
PUBLIC = "https://mcp.atlas.test"
KEY = ec.generate_private_key(ec.SECP256R1())


def _token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": "user-a",
        "iat": now,
        "exp": now + 600,
        "role": "authenticated",
        "client_id": "claude-client",
        "session_id": "11111111-1111-1111-1111-111111111111",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, KEY, algorithm="ES256", headers={"kid": "k1"})


@pytest.fixture
def verifier(monkeypatch):
    v = mcp_http.SupabaseTokenVerifier(SUPABASE)
    monkeypatch.setattr(v, "_signing_key", lambda _t: SimpleNamespace(key=KEY.public_key()))
    return v


def _verify(v, token):
    return asyncio.run(v.verify_token(token))


# --- token verification ------------------------------------------------------


def test_a_connector_token_is_accepted_as_its_user(verifier):
    got = _verify(verifier, _token())
    assert got is not None
    assert (got.subject, got.client_id) == ("user-a", "claude-client")


def test_a_web_session_token_is_refused(verifier):
    """No client_id = the web app's own login, which the database gate doesn't fence
    in. It must not work here."""
    assert _verify(verifier, _token(client_id=None)) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://other.supabase.test/auth/v1"},
        {"aud": "something-else"},
        {"exp": int(time.time()) - 60},
        {"sub": None},
    ],
)
def test_wrong_issuer_audience_expiry_or_subject_is_refused(verifier, overrides):
    assert _verify(verifier, _token(**overrides)) is None


def test_hs256_tokens_are_refused_even_with_the_right_secret(verifier, monkeypatch):
    """Whoever holds a legacy shared secret could mint any token; only the asymmetric
    signing key counts."""
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": "user-a",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "client_id": "x",
        },
        "shared-secret",
        algorithm="HS256",
    )
    monkeypatch.setattr(verifier, "_signing_key", lambda _t: SimpleNamespace(key="shared-secret"))
    assert _verify(verifier, forged) is None


def test_a_bad_signature_is_refused(verifier):
    other = ec.generate_private_key(ec.SECP256R1())
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": "user-a",
            "iat": now,
            "exp": now + 600,
            "client_id": "x",
        },
        other,
        algorithm="ES256",
    )
    assert _verify(verifier, token) is None


# --- the shared connection pool -------------------------------------------------


def test_pooled_clients_each_send_their_own_token(monkeypatch):
    """One httpx pool serves every caller; a token must never ride along on another
    caller's request."""
    seen: list[str] = []
    pool = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: (seen.append(req.headers["authorization"]), httpx.Response(200, json=[]))[1]
        )
    )
    monkeypatch.setattr(mcp_http, "_pool", pool)
    monkeypatch.setattr(
        mcp_http,
        "get_api_settings",
        lambda: SimpleNamespace(supabase_url=SUPABASE, supabase_anon_key="anon"),
    )
    a, b = mcp_http._pooled_client("tok-a"), mcp_http._pooled_client("tok-b")
    a.table("papers").select("id").execute()
    b.table("papers").select("id").execute()
    a.rpc("search_papers", {"p_team": "t", "p_q": ""}).execute()
    assert seen == ["Bearer tok-a", "Bearer tok-b", "Bearer tok-a"]
    assert "authorization" not in pool.headers


# --- the server ------------------------------------------------------------------


class StubVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("ok-"):
            return None
        user = token.removeprefix("ok-")
        return AccessToken(token=token, client_id="claude", scopes=[], subject=user)


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(mcp_http, "_pooled_client", lambda token: f"client-for-{token}")
    mcp = mcp_http.build_mcp(PUBLIC, SUPABASE, verifier=StubVerifier())
    with TestClient(mcp.streamable_http_app(), base_url="https://mcp.atlas.test") as client:
        yield client


def _rpc(client, method, params=None, token="ok-user-a", **kw):
    headers = {"accept": "application/json, text/event-stream", **kw.pop("headers", {})}
    if token:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=headers, **kw)


def test_unauthenticated_requests_get_the_challenge_that_starts_sign_in(server):
    r = _rpc(server, "tools/list", token=None)
    assert r.status_code == 401
    challenge = r.headers["www-authenticate"]
    assert "resource_metadata=" in challenge
    assert f"{PUBLIC}/.well-known/oauth-protected-resource/mcp" in challenge
    assert _rpc(server, "tools/list", token="forged").status_code == 401


def test_protected_resource_metadata_points_at_supabase(server):
    meta = server.get("/.well-known/oauth-protected-resource/mcp").json()
    assert meta["resource"] == f"{PUBLIC}/mcp"
    assert [s.rstrip("/") for s in meta["authorization_servers"]] == [ISSUER]


def test_only_the_read_only_paper_tools_are_served(server):
    r = _rpc(server, "tools/list")
    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {t.__name__ for t in READ_TOOLS}
    assert "post_paper" not in names and "get_figure_image" not in names


def test_each_call_runs_as_the_tokens_user(server, monkeypatch):
    monkeypatch.setattr(
        lab,
        "list_teams",
        lambda: [{"id": f"{lab.current_user_id()}|{lab.get_client()}", "name": "x"}],
    )
    for user in ("user-a", "user-b"):
        r = _rpc(server, "tools/call", {"name": "list_labs", "arguments": {}}, token=f"ok-{user}")
        text = r.json()["result"]["content"][0]["text"]
        assert f"{user}|client-for-ok-{user}" in text, text


def test_other_hosts_are_refused(server):
    """DNS-rebinding protection: only the connector's own host name is served."""
    r = _rpc(server, "tools/list", headers={"host": "evil.example"})
    assert r.status_code in (400, 421)


def test_calls_are_capped_per_user(server, monkeypatch):
    monkeypatch.setattr(
        mcp_http,
        "_call_limiter",
        mcp_http.PerUserRateLimiter(1, 60.0, lambda: lab.LabError("Too many Atlas requests")),
    )
    monkeypatch.setattr(lab, "list_teams", lambda: [])
    call = {"name": "list_labs", "arguments": {}}
    first = _rpc(server, "tools/call", call, token="ok-user-a").json()
    second = _rpc(server, "tools/call", call, token="ok-user-a").json()
    other = _rpc(server, "tools/call", call, token="ok-user-b").json()
    assert "Too many" not in json.dumps(first)
    assert "Too many Atlas requests" in json.dumps(second)
    assert "Too many" not in json.dumps(other)


# --- the paid embedding budget ------------------------------------------------------


def test_hosted_query_embeddings_have_a_daily_cap(monkeypatch):
    monkeypatch.setattr(lab, "_embed_budget", lab._DailyBudget())
    monkeypatch.setattr(lab, "get_api_settings", lambda: SimpleNamespace(mcp_daily_embeddings=2))
    monkeypatch.setattr(lab, "_user_client", lambda token: "client")
    calls: list[str] = []
    monkeypatch.setattr(embeddings, "embed_query", lambda text, **_: calls.append(text) or [1.0])
    with lab.act_as("tok", "user-a"):
        lab._embed_query("a")
        lab._embed_query("b")
        with pytest.raises(embeddings.EmbeddingError, match="allowance"):
            lab._embed_query("c")
    assert calls == ["a", "b"]


def test_long_texts_are_cut_before_embedding(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(embeddings, "embed_query", lambda text, **_: seen.append(text) or [1.0])
    lab._embed_query("x" * 10_000)  # stdio: no budget, still cut
    assert len(seen[0]) == lab._MAX_EMBED_CHARS


def test_clock_skew_within_leeway_is_tolerated(verifier):
    """A machine just resumed from suspend can run a little behind Supabase."""
    soon = int(time.time()) + 10
    assert _verify(verifier, _token(iat=soon)) is not None
    assert _verify(verifier, _token(iat=int(time.time()) + 600)) is None


def test_unknown_key_ids_cannot_drive_a_refetch_loop(monkeypatch):
    """Junk tokens naming random key ids may refetch the key set at most once per
    window — otherwise anyone could make us hammer Supabase."""
    v = mcp_http.SupabaseTokenVerifier(SUPABASE)
    fetches: list[bool] = []

    class EmptySet:
        def __getitem__(self, kid):
            raise KeyError(kid)

    monkeypatch.setattr(
        v._jwks, "get_jwk_set", lambda refresh=False: fetches.append(refresh) or EmptySet()
    )
    for i in range(20):
        token = jwt.encode({"sub": "x"}, KEY, algorithm="ES256", headers={"kid": f"random-{i}"})
        assert _verify(v, token) is None
    assert fetches.count(True) == 1  # one forced refetch for twenty unknown kids


# --- the tools' own thread pool -------------------------------------------------------


def test_tools_run_in_their_own_thread_pool_not_the_apis():
    """FastAPI's sync endpoints and the Teams webhook share anyio's default pool; a
    busy connector must not be able to take it over."""
    import anyio

    from atlas_mcp.tools import TOOL_THREADS, in_worker_thread

    seen = {}
    pools = {}

    def tool():
        seen["tools"] = TOOL_THREADS.borrowed_tokens
        seen["default"] = pools["default"].borrowed_tokens

    async def main():
        pools["default"] = anyio.to_thread.current_default_thread_limiter()
        await in_worker_thread(tool)()

    anyio.run(main)
    assert seen == {"tools": 1, "default": 0}


# --- configuration ---------------------------------------------------------------------


def test_missing_supabase_settings_say_so(monkeypatch):
    """Not "sign-in expired", which would send users round a reconnect loop."""
    monkeypatch.setattr(
        mcp_http, "get_api_settings", lambda: SimpleNamespace(supabase_url="", supabase_anon_key="")
    )
    with pytest.raises(lab.LabError, match="misconfigured"):
        mcp_http._pooled_client("tok")


# --- the embedding allowance -----------------------------------------------------------


def test_failed_embeddings_are_refunded(monkeypatch):
    """A Voyage outage must not drain the day's allowance for everyone."""
    monkeypatch.setattr(lab, "_embed_budget", lab._DailyBudget())
    monkeypatch.setattr(lab, "get_api_settings", lambda: SimpleNamespace(mcp_daily_embeddings=1))
    monkeypatch.setattr(lab, "_user_client", lambda token: "client")

    def down(text, **_):
        raise embeddings.EmbeddingError("Voyage is down")

    monkeypatch.setattr(embeddings, "embed_query", down)
    with lab.act_as("tok", "user-a"):
        for _ in range(5):
            with pytest.raises(embeddings.EmbeddingError, match="down"):
                lab._embed_query("query")
        monkeypatch.setattr(embeddings, "embed_query", lambda text, **_: [1.0])
        assert lab._embed_query("query") == [1.0]  # the allowance is still there


def test_empty_queries_spend_nothing(monkeypatch):
    monkeypatch.setattr(lab, "_embed_budget", lab._DailyBudget())
    monkeypatch.setattr(embeddings, "embed_query", lambda *a, **k: pytest.fail("embedded"))
    with pytest.raises(lab.LabError, match="Nothing to search"):
        lab._embed_query("   ")
    assert lab._embed_budget._spent == 0


# --- served by the API process ---------------------------------------------------------


@pytest.fixture
def api_with_connector(monkeypatch):
    """A FastAPI app wired the way api/app.py wires the connector."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    monkeypatch.setattr(mcp_http, "SupabaseTokenVerifier", lambda _url: StubVerifier())
    connector = mcp_http.Connector(PUBLIC, SUPABASE)

    @asynccontextmanager
    async def lifespan(_app):
        async with connector.running():
            yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["https://labatlas.test"])
    app.add_middleware(mcp_http.ConnectorHost, connector=connector)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def test_the_api_can_start_more_than_once(api_with_connector):
    """Each lifespan gets a fresh server: a session manager runs only once."""
    for _ in range(2):
        with TestClient(api_with_connector, base_url="https://mcp.atlas.test") as client:
            assert _rpc(client, "tools/list", token=None).status_code == 401


def test_only_the_connector_host_reaches_it(api_with_connector):
    with TestClient(api_with_connector, base_url="https://api.atlas.test") as api:
        assert api.get("/health").status_code == 200
        assert api.post("/mcp").status_code == 404
    with TestClient(api_with_connector, base_url="https://mcp.atlas.test") as mcp:
        assert mcp.get("/health").status_code == 404


def test_connector_has_its_own_cors_policy(api_with_connector):
    """The API allows only the web app's origin; the connector allows claude.ai."""
    preflight = {
        "origin": "https://claude.ai",
        "access-control-request-method": "POST",
        "access-control-request-headers": "authorization,content-type",
    }
    with TestClient(api_with_connector, base_url="https://mcp.atlas.test") as mcp:
        r = mcp.options("/mcp", headers=preflight)
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "https://claude.ai"
        evil = mcp.options("/mcp", headers={**preflight, "origin": "https://evil.example"})
        assert "access-control-allow-origin" not in evil.headers
    with TestClient(api_with_connector, base_url="https://api.atlas.test") as api:
        r = api.options("/health", headers=preflight)
        assert "access-control-allow-origin" not in r.headers  # the API's policy is unchanged


def test_requests_before_startup_get_503(api_with_connector):
    client = TestClient(api_with_connector, base_url="https://mcp.atlas.test")  # no lifespan
    assert client.post("/mcp").status_code == 503
