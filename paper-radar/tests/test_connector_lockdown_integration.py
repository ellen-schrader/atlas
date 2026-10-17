"""The connector lockdown, end to end, with a real connector token.

Gets a token the way Claude does — dynamic client registration, authorize (PKCE),
consent, code exchange — against a local Supabase with the OAuth server on, then
sends it through the real PostgREST and Storage:

  * every read-only paper tool still works with it (the lockdown mustn't break the
    connector it exists for);
  * everything else is refused: writes, deletes, RLS-bypassing RPCs, GraphQL, tables
    outside the read list (directly or embedded), Storage;
  * the web session's own token is unaffected;
  * revoking the connection stops the *existing* access token at once.

Opt-in, local only, and needs `[auth.oauth_server] enabled = true` in config.toml:

    ATLAS_INTEGRATION=1 uv run --extra mcp --extra dev \\
        pytest tests/test_connector_lockdown_integration.py
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp")

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

import httpx  # noqa: E402

from api import embeddings  # noqa: E402
from api.config import get_api_settings  # noqa: E402
from atlas_mcp import lab, papers  # noqa: E402

LOCAL_URL = os.environ.get("ATLAS_IT_SUPABASE_URL", "http://127.0.0.1:54321")
AUTH = f"{LOCAL_URL}/auth/v1"
REST = f"{LOCAL_URL}/rest/v1"
# The standard local-stack demo keys (`supabase status`) — never a real project's.
ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24i"
    "LCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)
SERVICE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZp"
    "Y2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
REDIRECT = "http://localhost:33418/callback"
PASSWORD = "connector-lockdown-test-only"

assert LOCAL_URL.startswith(("http://127.0.0.1", "http://localhost")), "local Supabase only"


def _bearer(token: str) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {token}"}


def _connector_token(web_token: str) -> tuple[str, str]:
    """(access_token, client_id) for a fresh OAuth client, approved by the user."""
    client = httpx.post(
        f"{AUTH}/oauth/clients/register",
        json={
            "client_name": "Lockdown test",
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
    httpx.get(f"{AUTH}/oauth/authorizations/{aid}", headers=_bearer(web_token))
    approved = httpx.post(
        f"{AUTH}/oauth/authorizations/{aid}/consent",
        headers=_bearer(web_token),
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


def _vec() -> list[float]:
    return [1.0] + [0.0] * 1023


@pytest.fixture(scope="module")
def world():
    if httpx.get(f"{AUTH}/.well-known/oauth-authorization-server").status_code != 200:
        pytest.skip("local Supabase OAuth server is off ([auth.oauth_server] in config.toml)")
    admin = _bearer(SERVICE)
    marker = f"LOCKDOWN-{uuid.uuid4().hex[:8]}"
    team_id, paper_id = str(uuid.uuid4()), str(uuid.uuid4())
    email = f"lockdown-{uuid.uuid4().hex[:8]}@example.test"
    user_id = httpx.post(
        f"{AUTH}/admin/users",
        headers=admin,
        json={"email": email, "password": PASSWORD, "email_confirm": True},
    ).json()["id"]
    try:
        rows = [
            (
                "teams",
                {
                    "id": team_id,
                    "name": f"Lab {marker}",
                    "slug": marker.lower(),
                    "created_by": user_id,
                },
            ),
            ("team_members", {"team_id": team_id, "user_id": user_id, "role": "owner"}),
            (
                "papers",
                {
                    "id": paper_id,
                    "url": f"https://example.test/{marker}",
                    "url_norm": marker.lower(),
                    "title": f"{marker} tumor microenvironment study",
                    "abstract": f"Abstract {marker}.",
                    "authors": ["A One", "B Two"],
                    "embedding": "[" + ",".join(map(str, _vec())) + "]",
                },
            ),
            (
                "paper_posts",
                {"paper_id": paper_id, "team_id": team_id, "posted_by": user_id, "source": "web"},
            ),
            (
                "paper_status",
                {"paper_id": paper_id, "team_id": team_id, "user_id": user_id, "status": "read"},
            ),
        ]
        for table, row in rows:
            httpx.post(f"{REST}/{table}", headers=admin, json=row).raise_for_status()
        web = httpx.post(
            f"{AUTH}/token?grant_type=password",
            headers={"apikey": ANON},
            json={"email": email, "password": PASSWORD},
        ).json()["access_token"]
        # As the user, the way the web app does it (the service role can't write these).
        for rpc, args in (
            ("set_mcp_access", {"p_team": team_id, "p_enabled": True}),
            ("mark_team_visit", {"p_team": team_id}),
        ):
            httpx.post(f"{REST}/rpc/{rpc}", headers=_bearer(web), json=args).raise_for_status()
        connector, client_id = _connector_token(web)
        yield {
            "marker": marker,
            "team_id": team_id,
            "paper_id": paper_id,
            "user_id": user_id,
            "web": web,
            "connector": connector,
            "client_id": client_id,
        }
    finally:
        httpx.delete(f"{REST}/teams?id=eq.{team_id}", headers=admin)  # cascades
        httpx.delete(f"{REST}/papers?id=eq.{paper_id}", headers=admin)
        httpx.delete(f"{AUTH}/admin/users/{user_id}", headers=admin)


@pytest.fixture(autouse=True)
def _local_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", LOCAL_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    get_api_settings.cache_clear()
    reset = lab._env_session_allowed.set(False)
    monkeypatch.setattr(embeddings, "embed_query", lambda text, **_: _vec())
    yield
    lab._env_session_allowed.reset(reset)
    get_api_settings.cache_clear()


def test_every_read_tool_still_works_with_a_connector_token(world):
    with lab.act_as(world["connector"], world["user_id"]):
        out = {
            "list_labs": papers.list_labs(),
            "search": papers.search_lab_papers("study"),
            "semantic": papers.search_lab_papers("study", mode="semantic"),
            "recent": papers.list_recent_papers(),
            "recommend": papers.recommend_reading(),
            "similar": papers.similar_papers(world["paper_id"]),
            "digest": papers.lab_digest(),
            "novelty": papers.novelty_check(text="a study"),
            "related": papers.draft_related_work(topic="study"),
            "get": papers.get_paper(world["paper_id"]),
            # UK spelling of a US-spelt title: search_papers expands it by reading
            # spelling_variants as the caller, which the lockdown must leave readable.
            "spelling": papers.search_lab_papers("tumour"),
        }
    for label, text in out.items():
        assert not text.startswith("Error:"), f"{label}: {text}"
    # The paper's id (in its deep link) only appears when the paper itself came back;
    # the lab name — which an empty "No papers in …" reply also contains — wouldn't do.
    assert world["team_id"] in out["list_labs"], out["list_labs"]
    for label in ("search", "semantic", "recent", "digest", "get", "spelling"):
        assert world["paper_id"] in out[label], f"{label} returned no paper:\n{out[label]}"
    # And each call was audited (the gate lets the audit insert through).
    logged = httpx.get(
        f"{REST}/mcp_tool_calls?team_id=eq.{world['team_id']}&select=tool",
        headers=_bearer(world["web"]),
    ).json()
    assert len(logged) >= 9


REFUSED = [
    ("DELETE", "/paper_posts?team_id=eq.{team_id}", None),
    ("PATCH", "/papers?id=eq.{paper_id}", {"title": "pwned"}),
    ("POST", "/paper_posts", {"paper_id": "{paper_id}", "team_id": "{team_id}", "source": "web"}),
    ("PATCH", "/team_members?team_id=eq.{team_id}", {"role": "member"}),
    (
        "POST",
        "/rpc/set_member_role",
        {"p_team": "{team_id}", "p_user": "{user_id}", "p_role": "member"},
    ),
    ("POST", "/rpc/set_mcp_access", {"p_team": "{team_id}", "p_enabled": False}),
    ("POST", "/rpc/create_team", {"p_name": "Evil", "p_slug": "evil"}),
    ("POST", "/rpc/regenerate_team_code", {"p_team": "{team_id}"}),
    ("POST", "/rpc/mark_team_visit", {"p_team": "{team_id}"}),
    ("GET", "/team_visits", None),
    ("GET", "/team_integrations", None),
    ("GET", "/profiles", None),
]


@pytest.mark.parametrize(("method", "path", "body"), REFUSED)
def test_connector_is_refused_everything_else(world, method, path, body):
    def fill(value):
        if not isinstance(value, str):
            return value
        for key in ("team_id", "paper_id", "user_id"):
            value = value.replace("{" + key + "}", world[key])
        return value

    json_body = {k: fill(v) for k, v in body.items()} if body else None
    r = httpx.request(
        method, REST + fill(path), headers=_bearer(world["connector"]), json=json_body
    )
    assert r.status_code == 403, f"{method} {path}: {r.status_code} {r.text}"
    assert "ATLAS_CONNECTOR_FORBIDDEN" in r.text


def test_connector_cannot_use_graphql(world):
    """GraphQL is its own endpoint, served by PostgREST as /rpc/graphql in the
    graphql_public schema — so the gate covers it too."""
    query = {"query": "{ teamsCollection { edges { node { id } } } }"}
    as_connector = httpx.post(
        f"{LOCAL_URL}/graphql/v1", headers=_bearer(world["connector"]), json=query
    )
    assert as_connector.status_code == 403, as_connector.text
    as_web = httpx.post(f"{LOCAL_URL}/graphql/v1", headers=_bearer(world["web"]), json=query)
    assert as_web.status_code == 200, as_web.text


def test_embedding_a_closed_table_returns_nothing(world):
    path = f"{REST}/teams?id=eq.{world['team_id']}&select=id,team_visits(user_id)"
    as_web = httpx.get(path, headers=_bearer(world["web"])).json()
    as_connector = httpx.get(path, headers=_bearer(world["connector"])).json()
    assert as_web[0]["team_visits"], "seed: the web session should see its visit"
    assert as_connector == [{"id": world["team_id"], "team_visits": []}]


def test_connector_cannot_use_storage(world):
    r = httpx.post(
        f"{LOCAL_URL}/storage/v1/object/figures/{world['team_id']}/x.png",
        headers={**_bearer(world["connector"]), "content-type": "image/png"},
        content=b"\x89PNG\r\n",
    )
    assert r.status_code in (400, 403), r.text
    listed = httpx.post(
        f"{LOCAL_URL}/storage/v1/object/list/figures",
        headers=_bearer(world["connector"]),
        json={"prefix": world["team_id"]},
    )
    assert listed.status_code != 200 or listed.json() == []


def test_the_web_session_is_unaffected(world):
    web = _bearer(world["web"])
    assert httpx.get(f"{REST}/team_visits", headers=web).status_code == 200
    assert httpx.get(f"{REST}/profiles?limit=1", headers=web).status_code == 200
    r = httpx.post(f"{REST}/rpc/mark_team_visit", headers=web, json={"p_team": world["team_id"]})
    assert r.status_code in (200, 204), r.text


def test_revoking_stops_the_existing_token_at_once(world):
    """Runs last in this module: it revokes the connection the others use."""
    papers_url = f"{REST}/papers?id=eq.{world['paper_id']}&select=id"
    assert httpx.get(papers_url, headers=_bearer(world["connector"])).status_code == 200

    httpx.delete(
        f"{AUTH}/user/oauth/grants",
        params={"client_id": world["client_id"]},
        headers=_bearer(world["web"]),
    ).raise_for_status()

    r = httpx.get(papers_url, headers=_bearer(world["connector"]))
    assert r.status_code == 401, r.text  # the JWT hasn't expired — the gate refuses it
    assert "ATLAS_CONNECTOR_REVOKED" in r.text
    with lab.act_as(world["connector"], world["user_id"]):
        out = papers.list_recent_papers()
    assert out.startswith("Error:") and "revoked" in out, out
