"""Saved searches (issue #164), end to end against a local Supabase: the real API
and database, with the literature sources stubbed.

    ATLAS_INTEGRATION=1 uv run --extra api --extra mcp --extra dev \\
        pytest tests/test_saved_searches_integration.py

What it holds the feature to: searches and suggestions are personal; one person
dismissing a paper does not hide it from anyone else; importing posts it to the
lab as that person; papers the lab already has are not suggested; nobody can
read or change another person's search; and without the feature it all 404s.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api import paper_identity  # noqa: E402
from api import saved_searches as ss  # noqa: E402
from api.app import app  # noqa: E402
from api.config import get_api_settings  # noqa: E402
from api.supa import _anon_client, service_client  # noqa: E402
from paper_radar.ingest.metadata import PaperMetadata  # noqa: E402
from paper_radar.search import sources  # noqa: E402
from paper_radar.search.sources import Hit  # noqa: E402
from supabase import create_client  # noqa: E402
from tests.local_supabase import ANON, LOCAL_URL, SERVICE  # noqa: E402

PASSWORD = "saved-searches-test-only"


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    """Local stack only; no network: the sources and the metadata lookup are stubbed."""
    monkeypatch.setenv("SUPABASE_URL", LOCAL_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE)
    monkeypatch.setenv("VOYAGE_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()
    monkeypatch.setattr(ss, "fetch_metadata", lambda url: PaperMetadata(url=url))
    monkeypatch.setattr(paper_identity, "published_record", lambda meta: None)
    monkeypatch.setattr(sources, "search_arxiv", lambda *a, **k: [])
    yield
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()


@pytest.fixture
def admin():
    return create_client(LOCAL_URL, SERVICE)


@pytest.fixture
def world(admin):
    w = _World(admin)
    yield w
    w.cleanup()


class _World:
    def __init__(self, admin) -> None:
        self.admin = admin
        self.users: list[str] = []
        self.teams: list[str] = []
        self.dois: list[str] = []
        self.tag = uuid.uuid4().hex[:8]

    def user(self) -> tuple[str, dict]:
        email = f"ss-{uuid.uuid4().hex[:8]}@example.test"
        uid = self.admin.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user.id
        self.users.append(uid)
        token = (
            create_client(LOCAL_URL, ANON)
            .auth.sign_in_with_password({"email": email, "password": PASSWORD})
            .session.access_token
        )
        return uid, {"Authorization": f"Bearer {token}"}

    def lab(self, *members: str, feature: bool = True) -> str:
        tid = str(uuid.uuid4())
        self.teams.append(tid)
        self.admin.table("teams").insert(
            {"id": tid, "name": f"SS {tid[:8]}", "slug": f"ss-{tid[:8]}", "created_by": members[0]}
        ).execute()
        for uid in members:
            self.admin.table("team_members").insert(
                {"team_id": tid, "user_id": uid, "role": "member"}
            ).execute()
        if feature:
            self.admin.table("team_features").insert(
                {"team_id": tid, "feature": ss.FEATURE}
            ).execute()
        return tid

    def hit(self, n: int) -> Hit:
        doi = f"10.9999/ss-{self.tag}-{n}"
        self.dois.append(doi)
        return Hit(
            source="pubmed",
            url=f"https://doi.org/{doi}",
            title=f"Saved-search paper {n}",
            doi=doi,
            pmid=str(900000 + n),
            authors=["Ada Lovelace"],
            venue="Journal",
            published_on="2026-10-20",
            abstract="Tertiary lymphoid structures.",
        )

    def cleanup(self) -> None:
        for tid in self.teams:
            self.admin.table("teams").delete().eq("id", tid).execute()
        if self.dois:
            self.admin.table("search_candidates").delete().in_("doi", self.dois).execute()
            self.admin.table("papers").delete().in_("doi", self.dois).execute()
        for uid in self.users:
            self.admin.auth.admin.delete_user(uid)


def _stub_pubmed(monkeypatch, hits: list[Hit]) -> None:
    monkeypatch.setattr(sources, "search_pubmed", lambda *a, **k: list(hits))


def test_suggestions_are_personal_and_dismissal_is_too(world, monkeypatch):
    a, a_auth = world.user()
    b, b_auth = world.user()
    lab = world.lab(a, b)
    hits = [world.hit(1), world.hit(2)]
    _stub_pubmed(monkeypatch, hits)
    client = TestClient(app)

    # Creating a search runs it at once (a background task, done by the time
    # TestClient returns).
    body = {"team_id": lab, "name": "TLS", "query": "tertiary lymphoid", "sources": ["pubmed"]}
    made = client.post("/saved-searches", json=body, headers=a_auth)
    assert made.status_code == 201, made.text
    mine = client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=a_auth).json()
    assert sorted(s["paper"]["title"] for s in mine) == [
        "Saved-search paper 1",
        "Saved-search paper 2",
    ]
    # B has no searches, so nothing; and cannot see A's search.
    assert (
        client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=b_auth).json()
        == []
    )
    assert client.get("/saved-searches", params={"team_id": lab}, headers=b_auth).json() == []
    assert (
        client.get("/saved-searches", params={"team_id": lab}, headers=a_auth).json()[0]["pending"]
        == 2
    )

    # A dismisses paper 1. B then saves a search that finds the same papers: B
    # still gets paper 1 -- A's lack of interest is A's alone.
    first = next(s for s in mine if s["paper"]["title"].endswith("1"))
    out = client.post(
        "/saved-searches/suggestions/dismiss",
        json={"team_id": lab, "ids": [first["id"]]},
        headers=a_auth,
    )
    assert out.json() == {"count": 1}
    made_b = client.post("/saved-searches", json=body, headers=b_auth)
    assert made_b.status_code == 201
    theirs = client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=b_auth)
    assert len(theirs.json()) == 2

    # A's next run does not bring paper 1 back for A.
    search = world.admin.table("saved_searches").select("*").eq("id", made.json()["id"]).execute()
    ss.run_saved_search(service_client(), search.data[0], date.today(), feed=None)
    mine = client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=a_auth).json()
    assert [s["paper"]["title"] for s in mine] == ["Saved-search paper 2"]

    # B cannot answer A's suggestions.
    out = client.post(
        "/saved-searches/suggestions/import",
        json={"team_id": lab, "ids": [mine[0]["id"]]},
        headers=b_auth,
    )
    assert out.json() == {"count": 0}


def test_import_posts_to_the_lab_as_the_person_and_others_stop_seeing_it(world, monkeypatch):
    a, a_auth = world.user()
    b, b_auth = world.user()
    lab = world.lab(a, b)
    _stub_pubmed(monkeypatch, [world.hit(1)])
    client = TestClient(app)
    body = {"team_id": lab, "name": "TLS", "query": "tertiary lymphoid", "sources": ["pubmed"]}
    for auth in (a_auth, b_auth):
        assert client.post("/saved-searches", json=body, headers=auth).status_code == 201

    (sugg,) = client.get(
        "/saved-searches/suggestions", params={"team_id": lab}, headers=a_auth
    ).json()
    out = client.post(
        "/saved-searches/suggestions/import",
        json={"team_id": lab, "ids": [sugg["id"]]},
        headers=a_auth,
    )
    assert out.json() == {"count": 1}

    paper = world.admin.table("papers").select("id, title").eq("doi", world.dois[0]).execute().data
    assert paper and paper[0]["title"] == "Saved-search paper 1"  # the source's record
    post = (
        world.admin.table("paper_posts")
        .select("posted_by, source")
        .eq("team_id", lab)
        .eq("paper_id", paper[0]["id"])
        .execute()
        .data
    )
    assert post == [{"posted_by": a, "source": "saved_search"}]
    row = world.admin.table("search_suggestions").select("status, paper_id").eq("id", sugg["id"])
    assert row.execute().data == [{"status": "imported", "paper_id": paper[0]["id"]}]

    # B's suggestion of the same paper goes: the lab has it now.
    assert (
        client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=b_auth).json()
        == []
    )
    # And a new search does not suggest it again to anyone.
    c, c_auth = world.user()
    world.admin.table("team_members").insert(
        {"team_id": lab, "user_id": c, "role": "member"}
    ).execute()
    assert client.post("/saved-searches", json=body, headers=c_auth).status_code == 201
    assert (
        client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=c_auth).json()
        == []
    )


def test_searches_are_owned(world, monkeypatch):
    a, a_auth = world.user()
    b, b_auth = world.user()
    lab = world.lab(a, b)
    _stub_pubmed(monkeypatch, [])
    client = TestClient(app)
    body = {"team_id": lab, "name": "TLS", "query": "tls", "sources": ["pubmed"]}
    sid = client.post("/saved-searches", json=body, headers=a_auth).json()["id"]

    patch = client.patch(
        f"/saved-searches/{sid}", json={"team_id": lab, "name": "x"}, headers=b_auth
    )
    assert patch.status_code == 404
    gone = client.delete(f"/saved-searches/{sid}", params={"team_id": lab}, headers=b_auth)
    assert gone.status_code == 404
    patch = client.patch(
        f"/saved-searches/{sid}", json={"team_id": lab, "active": False}, headers=a_auth
    )
    assert patch.status_code == 200 and patch.json()["active"] is False
    assert (
        client.delete(f"/saved-searches/{sid}", params={"team_id": lab}, headers=a_auth).status_code
        == 204
    )


def test_bad_query_and_limits(world, monkeypatch):
    a, a_auth = world.user()
    lab = world.lab(a)
    _stub_pubmed(monkeypatch, [])
    client = TestClient(app)
    bad = client.post(
        "/saved-searches", json={"team_id": lab, "name": "x", "query": "(tls"}, headers=a_auth
    )
    assert bad.status_code == 422 and bad.json() == {"detail": "A '(' is never closed."}
    none = client.post(
        "/saved-searches",
        json={"team_id": lab, "name": "x", "query": "tls", "sources": ["scopus"]},
        headers=a_auth,
    )
    assert none.status_code == 422
    for i in range(ss.MAX_SEARCHES):
        world.admin.table("saved_searches").insert(
            {"user_id": a, "team_id": lab, "name": f"s{i}", "query": "tls", "sources": ["pubmed"]}
        ).execute()
    full = client.post(
        "/saved-searches", json={"team_id": lab, "name": "x", "query": "tls"}, headers=a_auth
    )
    assert full.status_code == 409


def test_without_the_feature_everything_404s(world):
    a, a_auth = world.user()
    lab = world.lab(a, feature=False)
    client = TestClient(app)
    assert client.get("/saved-searches", params={"team_id": lab}, headers=a_auth).status_code == 404
    assert (
        client.get(
            "/saved-searches/suggestions", params={"team_id": lab}, headers=a_auth
        ).status_code
        == 404
    )
    made = client.post(
        "/saved-searches", json={"team_id": lab, "name": "x", "query": "tls"}, headers=a_auth
    )
    assert made.status_code == 404
    # Nor does it work for a lab one is not in, feature or not.
    b, b_auth = world.user()
    other = world.lab(b)
    assert (
        client.get("/saved-searches", params={"team_id": other}, headers=a_auth).status_code == 404
    )


def test_connectors_cannot_read_the_tables(world):
    """No grants for signed-in users at all: the tables are API-only."""
    a, a_auth = world.user()
    lab = world.lab(a)
    world.admin.table("saved_searches").insert(
        {"user_id": a, "team_id": lab, "name": "x", "query": "tls", "sources": ["pubmed"]}
    ).execute()
    token = a_auth["Authorization"].split()[1]
    as_user = create_client(LOCAL_URL, ANON)
    as_user.postgrest.auth(token)
    for table in ("saved_searches", "search_suggestions", "search_candidates", "rxiv_feed"):
        with pytest.raises(Exception, match="permission denied"):
            as_user.table(table).select("*").limit(1).execute()


def test_an_interrupted_import_is_finished_by_the_job(world, monkeypatch):
    """The API machine stopped mid-import: the row is left 'importing'."""
    from datetime import UTC, datetime, timedelta

    a, a_auth = world.user()
    lab = world.lab(a)
    _stub_pubmed(monkeypatch, [world.hit(1)])
    client = TestClient(app)
    body = {"team_id": lab, "name": "TLS", "query": "tls", "sources": ["pubmed"]}
    assert client.post("/saved-searches", json=body, headers=a_auth).status_code == 201
    (sugg,) = client.get(
        "/saved-searches/suggestions", params={"team_id": lab}, headers=a_auth
    ).json()
    two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    world.admin.table("search_suggestions").update(
        {"status": "importing", "decided_at": two_hours_ago}
    ).eq("id", sugg["id"]).execute()

    assert ss.retry_stuck_imports(service_client(), datetime.now(UTC)) >= 1
    row = world.admin.table("search_suggestions").select("status, paper_id").eq("id", sugg["id"])
    (done,) = row.execute().data
    assert done["status"] == "imported" and done["paper_id"]
    post = world.admin.table("paper_posts").select("posted_by").eq("team_id", lab).execute().data
    assert post == [{"posted_by": a}]


def test_malformed_ids_are_422_not_500(world):
    a, a_auth = world.user()
    lab = world.lab(a)
    client = TestClient(app)
    bad = client.post(
        "/saved-searches/suggestions/dismiss", json={"team_id": lab, "ids": ["x"]}, headers=a_auth
    )
    assert bad.status_code == 422
    bad = client.patch("/saved-searches/nope", json={"team_id": lab, "name": "x"}, headers=a_auth)
    assert bad.status_code == 422
    bad = client.get("/saved-searches", params={"team_id": "lab"}, headers=a_auth)
    assert bad.status_code == 422


def test_query_errors_come_back_as_a_sentence(world):
    a, a_auth = world.user()
    lab = world.lab(a)
    client = TestClient(app)
    bad = client.post(
        "/saved-searches/preview", json={"team_id": lab, "query": "(tls"}, headers=a_auth
    )
    assert bad.status_code == 422 and bad.json() == {"detail": "A '(' is never closed."}
