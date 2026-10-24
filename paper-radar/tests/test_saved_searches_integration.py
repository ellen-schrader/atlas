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
    for table in (
        "saved_searches",
        "search_suggestions",
        "search_candidates",
        "search_suggestion_searches",
        "rxiv_feed",
    ):
        with pytest.raises(Exception, match="permission denied"):
            as_user.table(table).select("*").limit(1).execute()
    with pytest.raises(Exception, match="permission denied"):
        as_user.rpc(
            "pending_suggestions", {"p_user": a, "p_team": lab, "p_per_search": 10}
        ).execute()


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


# --- round 2: several searches per paper, order, arXiv subjects, ideas ----------------


def _suggestions(client, lab, auth) -> list[dict]:
    out = client.get("/saved-searches/suggestions", params={"team_id": lab}, headers=auth)
    assert out.status_code == 200, out.text
    return out.json()


def _searches(client, lab, auth) -> list[dict]:
    return client.get("/saved-searches", params={"team_id": lab}, headers=auth).json()


def test_a_paper_two_searches_find_shows_under_both_and_one_answer_clears_it(world, monkeypatch):
    a, a_auth = world.user()
    lab = world.lab(a)
    shared, only_first = world.hit(1), world.hit(2)
    client = TestClient(app)

    _stub_pubmed(monkeypatch, [shared, only_first])
    first = client.post(
        "/saved-searches",
        json={"team_id": lab, "name": "One", "query": "tls", "sources": ["pubmed"]},
        headers=a_auth,
    ).json()
    _stub_pubmed(monkeypatch, [shared])
    second = client.post(
        "/saved-searches",
        json={"team_id": lab, "name": "Two", "query": "b cells", "sources": ["pubmed"]},
        headers=a_auth,
    ).json()

    mine = {s["paper"]["title"]: s for s in _suggestions(client, lab, a_auth)}
    assert len(mine) == 2  # one suggestion per paper, however many searches found it
    assert mine[shared.title]["search_ids"] == sorted([first["id"], second["id"]])
    assert mine[only_first.title]["search_ids"] == [first["id"]]
    assert [s["pending"] for s in _searches(client, lab, a_auth)] == [2, 1]

    out = client.post(
        "/saved-searches/suggestions/dismiss",
        json={"team_id": lab, "ids": [mine[shared.title]["id"]]},
        headers=a_auth,
    )
    assert out.json() == {"count": 1}
    assert [s["pending"] for s in _searches(client, lab, a_auth)] == [1, 0]

    # Deleting the first search leaves its paper waiting, under no search.
    client.delete(f"/saved-searches/{first['id']}", params={"team_id": lab}, headers=a_auth)
    (left,) = _suggestions(client, lab, a_auth)
    assert left["search_ids"] == []


def test_the_page_lists_the_newest_few_of_every_search(world, monkeypatch):
    """A noisy search does not crowd a quiet one off the page."""
    a, a_auth = world.user()
    lab = world.lab(a)
    client = TestClient(app)
    _stub_pubmed(monkeypatch, [world.hit(1)])
    quiet = client.post(
        "/saved-searches",
        json={"team_id": lab, "name": "Quiet", "query": "tls", "sources": ["pubmed"]},
        headers=a_auth,
    ).json()
    _stub_pubmed(monkeypatch, [world.hit(n) for n in range(10, 16)])
    noisy = client.post(
        "/saved-searches",
        json={"team_id": lab, "name": "Noisy", "query": "ai", "sources": ["pubmed"]},
        headers=a_auth,
    ).json()

    rows = ss.page_suggestions(service_client(), a, lab, per_search=3)
    by_search: dict[str, int] = {}
    for r in rows:
        for sid in r["search_ids"]:
            by_search[sid] = by_search.get(sid, 0) + 1
    assert by_search == {quiet["id"]: 1, noisy["id"]: 3}


def test_searches_keep_the_order_their_owner_gives(world, monkeypatch):
    a, a_auth = world.user()
    b, b_auth = world.user()
    lab = world.lab(a, b)
    _stub_pubmed(monkeypatch, [])
    client = TestClient(app)
    ids = [
        client.post(
            "/saved-searches",
            json={"team_id": lab, "name": name, "query": "tls", "sources": ["pubmed"]},
            headers=a_auth,
        ).json()["id"]
        for name in ("A", "B", "C")
    ]
    assert [s["name"] for s in _searches(client, lab, a_auth)] == ["A", "B", "C"]

    out = client.put(
        "/saved-searches/order",
        json={"team_id": lab, "ids": [ids[2], ids[0], ids[1]]},
        headers=a_auth,
    )
    assert out.status_code == 204, out.text
    assert [s["name"] for s in _searches(client, lab, a_auth)] == ["C", "A", "B"]

    # Not all of them, or someone else's: refused, and nothing moves.
    for bad in ([ids[0], ids[1]], [ids[0], ids[1], ids[2], ids[2]]):
        out = client.put("/saved-searches/order", json={"team_id": lab, "ids": bad}, headers=a_auth)
        assert out.status_code == 422
    out = client.put("/saved-searches/order", json={"team_id": lab, "ids": ids}, headers=b_auth)
    assert out.status_code == 422
    assert [s["name"] for s in _searches(client, lab, a_auth)] == ["C", "A", "B"]


def test_new_searches_keep_to_biology_on_arxiv_unless_told_otherwise(world, monkeypatch):
    a, a_auth = world.user()
    lab = world.lab(a)
    asked: list[str] = []
    monkeypatch.setattr(sources, "search_arxiv", lambda query, *a, **k: asked.append(query) or [])
    client = TestClient(app)

    made = client.post(
        "/saved-searches",
        json={"team_id": lab, "name": "FM", "query": '"flow matching"', "sources": ["arxiv"]},
        headers=a_auth,
    ).json()
    assert made["arxiv_categories"] == ["q-bio"]
    assert asked[-1].endswith("AND (cat:q-bio*)")

    out = client.patch(
        f"/saved-searches/{made['id']}",
        json={"team_id": lab, "arxiv_categories": []},
        headers=a_auth,
    )
    assert out.json()["arxiv_categories"] == []
    assert "cat:" not in asked[-1]  # the change re-ran it, on all of arXiv

    out = client.patch(
        f"/saved-searches/{made['id']}",
        json={"team_id": lab, "arxiv_categories": ["q-bio.GN", "drop table"]},
        headers=a_auth,
    )
    assert out.status_code == 422
    assert "arXiv subject code" in out.json()["detail"]


def test_ideas_come_from_the_persons_tags_and_skip_what_they_search_already(world, monkeypatch):
    a, a_auth = world.user()
    lab = world.lab(a)
    client = TestClient(app)
    world.admin.table("profiles").update({"interests": ["organoids"]}).eq("id", a).execute()
    for n, tags in enumerate(
        (
            ["spatial-transcriptomics", "breast-cancer", "review"],
            ["spatial-transcriptomics", "breast-cancer"],
            ["tertiary-lymphoid-structures"],
            ["tertiary-lymphoid-structures"],
        )
    ):
        doi = f"10.9999/ss-{world.tag}-idea-{n}"
        world.dois.append(doi)
        paper = (
            world.admin.table("papers")
            .insert(
                {
                    "url": f"https://doi.org/{doi}",
                    "url_norm": f"doi.org/{doi}",
                    "doi": doi,
                    "title": f"Idea {n}",
                }
            )
            .execute()
            .data[0]
        )
        world.admin.table("paper_posts").insert(
            {
                "team_id": lab,
                "paper_id": paper["id"],
                "posted_by": a,
                "source": "web",
                "tags": tags,
            }
        ).execute()

    got = client.get("/saved-searches/ideas", params={"team_id": lab}, headers=a_auth)
    assert got.status_code == 200, got.text
    ideas = got.json()
    assert ideas[0]["query"] == '"breast cancer"[tiab] AND "spatial transcriptomics"[tiab]'
    queries = [i["query"] for i in ideas]
    assert "organoids[tiab]" in queries
    assert '"tertiary lymphoid structures"[tiab]' in queries
    assert not any("review" in x for x in queries)

    # Once a search covers TLS, it is no longer suggested.
    _stub_pubmed(monkeypatch, [])
    client.post(
        "/saved-searches",
        json={
            "team_id": lab,
            "name": "TLS",
            "query": '"tertiary lymphoid structures"',
            "sources": ["pubmed"],
        },
        headers=a_auth,
    )
    again = client.get("/saved-searches/ideas", params={"team_id": lab}, headers=a_auth).json()
    assert not any("tertiary" in i["query"] for i in again)
