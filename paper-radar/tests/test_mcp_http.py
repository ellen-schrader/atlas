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
    monkeypatch.setattr(
        v._jwks, "get_signing_key_from_jwt", lambda _t: SimpleNamespace(key=KEY.public_key())
    )
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
    monkeypatch.setattr(
        verifier._jwks, "get_signing_key_from_jwt", lambda _t: SimpleNamespace(key="shared-secret")
    )
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
