"""Projects (docs/PROJECTS_PLAN.md, PR 1), end to end against a local Supabase:
the real API and database, with the embedding call stubbed.

    ATLAS_INTEGRATION=1 uv run --extra api --extra dev \\
        pytest tests/test_projects_integration.py

What it holds the feature to: nothing is visible or writable without the
'projects' switch; a project is seen by its owner, the lab or chosen lab members
as its visibility says; only the owner changes its settings, while everyone who
sees it can add and dismiss papers, and only the lab's own; closeness is to the
nearest project paper; merging two papers keeps their projects; deleting an
account removes its private projects and leaves shared ones.
"""

from __future__ import annotations

import math
import os
import uuid

import httpx
import pytest

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api import embeddings  # noqa: E402
from api.app import app  # noqa: E402
from api.config import get_api_settings  # noqa: E402
from api.supa import _anon_client, service_client  # noqa: E402
from supabase import create_client  # noqa: E402
from tests.local_supabase import ANON, LOCAL_URL, REST, SERVICE, bearer  # noqa: E402

PASSWORD = "projects-test-only"
DIM = 1024


def vec(*parts: tuple[int, float]) -> list[float]:
    """A unit vector with the given weights on the given axes."""
    v = [0.0] * DIM
    for axis, w in parts:
        v[axis] = w
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def pg(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


@pytest.fixture(autouse=True)
def _local(monkeypatch):
    """Local stack only; the description is "embedded" onto axis 0."""
    monkeypatch.setenv("SUPABASE_URL", LOCAL_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE)
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()
    monkeypatch.setattr(embeddings, "embed_query", lambda text, **k: vec((0, 1.0)))
    yield
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()


@pytest.fixture
def admin():
    return create_client(LOCAL_URL, SERVICE)


class World:
    def __init__(self, admin) -> None:
        self.admin = admin
        self.users: list[str] = []
        self.teams: list[str] = []
        self.papers: list[str] = []

    def user(self, *, feature: bool = True) -> tuple[str, str, str]:
        """(user_id, email, token), with the projects switch on unless told not."""
        email = f"proj-{uuid.uuid4().hex[:8]}@example.test"
        uid = self.admin.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user.id
        self.users.append(uid)
        if feature:
            self.admin.table("user_features").insert(
                {"user_id": uid, "feature": "projects"}
            ).execute()
        token = (
            create_client(LOCAL_URL, ANON)
            .auth.sign_in_with_password({"email": email, "password": PASSWORD})
            .session.access_token
        )
        return uid, email, token

    def lab(self, *members: str) -> str:
        tid = str(uuid.uuid4())
        self.teams.append(tid)
        self.admin.table("teams").insert(
            {
                "id": tid,
                "name": f"Proj {tid[:8]}",
                "slug": f"proj-{tid[:8]}",
                "created_by": members[0],
            }
        ).execute()
        for i, uid in enumerate(members):
            self.admin.table("team_members").insert(
                {"team_id": tid, "user_id": uid, "role": "owner" if i == 0 else "member"}
            ).execute()
        return tid

    def paper(self, team_id: str | None, embedding: list[float], **extra) -> str:
        pid = str(uuid.uuid4())
        self.papers.append(pid)
        self.admin.table("papers").insert(
            {
                "id": pid,
                "url": f"https://example.test/{pid}",
                "url_norm": pid,
                "title": f"Paper {pid[:8]}",
                "embedding": pg(embedding),
                **extra,
            }
        ).execute()
        if team_id:
            self.admin.table("paper_posts").insert(
                {"paper_id": pid, "team_id": team_id, "source": "web"}
            ).execute()
        return pid

    def cleanup(self) -> None:
        for tid in self.teams:
            self.admin.table("teams").delete().eq("id", tid).execute()
            self.admin.table("removed_posts").delete().eq("team_id", tid).execute()
        if self.papers:
            self.admin.table("paper_aliases").delete().in_("old_paper_id", self.papers).execute()
            self.admin.table("papers").delete().in_("id", self.papers).execute()
        for uid in self.users:
            try:
                self.admin.auth.admin.delete_user(uid)
            except Exception:  # noqa: BLE001 — already deleted by the test
                pass


@pytest.fixture
def world(admin):
    w = World(admin)
    yield w
    w.cleanup()


@pytest.fixture
def api():
    return TestClient(app)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def rest(token: str, method: str, path: str, **kw) -> httpx.Response:
    """PostgREST as a signed-in user."""
    headers = {**bearer(token), "Prefer": "return=representation", **kw.pop("headers", {})}
    return httpx.request(method, f"{REST}/{path}", headers=headers, **kw)


def seen(token: str, project_id: str) -> bool:
    r = rest(token, "GET", f"projects?id=eq.{project_id}&select=id")
    return r.status_code == 200 and len(r.json()) == 1


def create(api, token: str, team: str, **body) -> dict:
    r = api.post("/projects", headers=auth(token), json={"team_id": team, "name": "TLS", **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_dark_without_the_switch(world, api):
    owner, _, t_owner = world.user()
    plain, _, t_plain = world.user(feature=False)
    team = world.lab(owner, plain)

    r = api.post("/projects", headers=auth(t_plain), json={"team_id": team, "name": "X"})
    assert r.status_code == 404

    pj = create(api, t_owner, team, visibility="lab")
    assert "description_embedding" not in pj
    assert not seen(t_plain, pj["id"])  # a lab project, but no switch
    r = api.patch(f"/projects/{pj['id']}", headers=auth(t_plain), json={"name": "Y"})
    assert r.status_code == 404
    r = rest(t_plain, "POST", "projects", json={"team_id": team, "owner_id": plain, "name": "Z"})
    assert r.status_code in (401, 403)


def test_visibility_and_settings(world, api):
    owner, _, t_owner = world.user()
    mate, _, t_mate = world.user()
    other, _, t_other = world.user()
    team = world.lab(owner, mate)
    world.lab(other)

    pj = create(api, t_owner, team, description="Tertiary lymphoid structures")
    assert pj["visibility"] == "private" and pj["owner_id"] == owner
    assert seen(t_owner, pj["id"]) and not seen(t_mate, pj["id"])

    api.patch(f"/projects/{pj['id']}", headers=auth(t_owner), json={"visibility": "lab"})
    assert seen(t_mate, pj["id"]) and not seen(t_other, pj["id"])

    api.patch(f"/projects/{pj['id']}", headers=auth(t_owner), json={"visibility": "people"})
    assert not seen(t_mate, pj["id"])
    # Only lab members can be added, and only by the owner.
    r = rest(t_owner, "POST", "project_people", json={"project_id": pj["id"], "user_id": other})
    assert r.status_code == 403
    r = rest(t_mate, "POST", "project_people", json={"project_id": pj["id"], "user_id": mate})
    assert r.status_code == 403
    r = rest(t_owner, "POST", "project_people", json={"project_id": pj["id"], "user_id": mate})
    assert r.status_code == 201, r.text
    assert seen(t_mate, pj["id"])

    # Settings are the owner's: the API says so, and RLS holds without it.
    r = api.patch(f"/projects/{pj['id']}", headers=auth(t_mate), json={"name": "Mine"})
    assert r.status_code == 403
    r = rest(t_mate, "PATCH", f"projects?id=eq.{pj['id']}", json={"name": "Mine"})
    assert r.status_code == 200 and r.json() == []
    r = rest(t_owner, "PATCH", f"projects?id=eq.{pj['id']}", json={"team_id": str(uuid.uuid4())})
    assert r.status_code in (401, 403)  # the lab never changes
    r = rest(t_mate, "DELETE", f"projects?id=eq.{pj['id']}")
    assert r.json() == []
    assert seen(t_owner, pj["id"])

    r = api.patch(
        f"/projects/{pj['id']}",
        headers=auth(t_owner),
        json={"name": " TLS in breast ", "suggest_level": "more"},
    )
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["suggest_level"]) == ("TLS in breast", "more")


def test_papers_follow_who_can_see(world, api):
    owner, _, t_owner = world.user()
    mate, _, t_mate = world.user()
    team = world.lab(owner, mate)
    mine = world.paper(team, vec((1, 1.0)))
    elsewhere = world.paper(None, vec((1, 1.0)))

    pj = create(api, t_owner, team)
    row = {"project_id": pj["id"], "paper_id": mine, "added_by": mate}
    assert rest(t_mate, "POST", "project_papers", json=row).status_code == 403  # private

    api.patch(f"/projects/{pj['id']}", headers=auth(t_owner), json={"visibility": "lab"})
    assert rest(t_mate, "POST", "project_papers", json=row).status_code == 201
    row_out = {**row, "paper_id": elsewhere}
    assert rest(t_mate, "POST", "project_papers", json=row_out).status_code == 403
    r = rest(
        t_mate,
        "PATCH",
        f"project_papers?project_id=eq.{pj['id']}&paper_id=eq.{mine}",
        json={"state": "dismissed", "added_by": owner},
    )
    assert r.status_code == 403  # can't write as someone else
    r = rest(
        t_mate,
        "PATCH",
        f"project_papers?project_id=eq.{pj['id']}&paper_id=eq.{mine}",
        json={"state": "dismissed", "added_by": mate},
    )
    assert r.status_code == 200 and r.json()[0]["state"] == "dismissed"
    # The web app's upsert: back in the project, as whoever does it.
    r = rest(
        t_mate,
        "POST",
        "project_papers",
        json={**row, "state": "in"},
        headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()[0]["state"] == "in"
    r = rest(
        t_mate,
        "POST",
        "project_papers",
        json={**row, "paper_id": elsewhere},
        headers={"Prefer": "resolution=merge-duplicates,return=representation"},
    )
    assert r.status_code == 403


def test_closeness(world, api, admin):
    owner, _, t_owner = world.user()
    team = world.lab(owner)
    a = world.paper(team, vec((1, 1.0)), year=2020, authors=["X Y", "Bruno TC"])
    b = world.paper(team, vec((1, 1.0), (2, 0.2)), year=2021)
    c = world.paper(team, vec((3, 1.0)), year=2022)
    near_a = world.paper(team, vec((1, 1.0), (4, 0.3)), year=2024)
    near_c = world.paper(team, vec((3, 1.0), (4, 0.3)), year=2025)
    far = world.paper(team, vec((5, 1.0)), year=2025, tags=["b-cells"])
    by_lab = world.paper(
        team, vec((6, 1.0)), year=2025, authors=["Q", "Bruno TC", "KEYNOTE Investigators"]
    )
    dismissed = world.paper(team, vec((1, 1.0), (4, 0.2)), year=2023)
    world.paper(world.lab(owner), vec((1, 1.0)))  # another lab's paper: never counted

    pj = create(api, t_owner, team, description="anything")

    def closeness() -> dict[str, dict]:
        r = rest(t_owner, "POST", "rpc/project_closeness", json={"p_project": pj["id"]})
        assert r.status_code == 200, r.text
        return {row["paper_id"]: row for row in r.json()}

    # No papers yet: the description (axis 0) is all there is, and the line is a
    # rank (the 20 closest), so in a lab of eight every paper is suggested.
    rows = closeness()
    assert len(rows) == 8
    assert all(r["nearest_id"] is None and r["suggested"] == "close" for r in rows.values())

    for pid in (a, b, c):
        rest(
            t_owner,
            "POST",
            "project_papers",
            json={"project_id": pj["id"], "paper_id": pid, "added_by": owner},
        )
    rest(
        t_owner,
        "POST",
        "project_papers",
        json={
            "project_id": pj["id"],
            "paper_id": dismissed,
            "state": "dismissed",
            "added_by": owner,
        },
    )

    rows = closeness()
    # Nearest paper, not the centroid: each newcomer is close to its own strand.
    assert rows[near_a]["nearest_id"] in (a, b) and rows[near_a]["similarity"] > 0.9
    assert rows[near_c]["nearest_id"] == c and rows[near_c]["similarity"] > 0.9
    # Project papers are scored against the others (c is alone in its strand).
    assert rows[a]["nearest_id"] == b and rows[c]["similarity"] < 0.1
    assert rows[a]["state"] == "in" and rows[a]["suggested"] is None
    assert rows[near_a]["suggested"] == "close" and rows[near_c]["suggested"] == "close"
    assert rows[far]["suggested"] is None
    assert rows[dismissed]["state"] == "dismissed" and rows[dismissed]["suggested"] is None
    # A small lab: everything is in the pool, except what was dismissed.
    assert all(r["related"] == (pid != dismissed) for pid, r in rows.items())

    # Following a tag or a lab suggests its related papers below the line.
    rest(
        t_owner,
        "POST",
        "project_follows",
        json={"project_id": pj["id"], "kind": "tag", "value": "b-cells"},
    )
    rest(
        t_owner,
        "POST",
        "project_follows",
        json={"project_id": pj["id"], "kind": "lab", "value": "Bruno TC"},
    )
    rows = closeness()
    assert (rows[far]["suggested"], rows[far]["via"]) == ("tag", "b-cells")
    assert (rows[by_lab]["suggested"], rows[by_lab]["via"]) == ("lab", "Bruno TC")

    # The lab and tags behind those, as the web app counts them.
    assert rows[by_lab]["lab"] == "Bruno TC" and rows[far]["tags"] == ["b-cells"]

    for _ in range(2):  # opening it again only moves the time
        r = rest(t_owner, "POST", "rpc/mark_project_viewed", json={"p": pj["id"]})
        assert r.status_code in (200, 204), r.text
    views = rest(t_owner, "GET", f"project_views?project_id=eq.{pj['id']}").json()
    assert len(views) == 1


def test_changes_to_papers_update_the_project(world, api, admin):
    owner, _, t_owner = world.user()
    mate, _, t_mate = world.user()
    team = world.lab(owner, mate)
    paper = world.paper(team, vec((1, 1.0)))
    pj = create(api, t_owner, team, visibility="lab")
    admin.table("projects").update({"updated_at": "2026-01-01T00:00:00+00:00"}).eq(
        "id", pj["id"]
    ).execute()
    row = {"project_id": pj["id"], "paper_id": paper, "added_by": mate}
    assert rest(t_mate, "POST", "project_papers", json=row).status_code == 201
    (after,) = admin.table("projects").select("updated_at").eq("id", pj["id"]).execute().data
    assert not after["updated_at"].startswith("2026-01-01")


def test_merge_keeps_projects(world, api, admin):
    owner, _, t_owner = world.user()
    team = world.lab(owner)
    old = world.paper(team, vec((1, 1.0)))
    kept = world.paper(team, vec((1, 1.0)))
    pj = create(api, t_owner, team)
    pj2 = create(api, t_owner, team)
    rest(
        t_owner,
        "POST",
        "project_papers",
        json={"project_id": pj["id"], "paper_id": old, "added_by": owner},
    )
    rest(
        t_owner,
        "POST",
        "project_papers",
        json={"project_id": pj2["id"], "paper_id": old, "added_by": owner},
    )
    rest(
        t_owner,
        "POST",
        "project_papers",
        json={"project_id": pj2["id"], "paper_id": kept, "state": "dismissed", "added_by": owner},
    )

    admin.rpc("merge_papers", {"p_from": old, "p_into": kept, "p_reason": "doi_case"}).execute()

    rows = (
        admin.table("project_papers")
        .select("project_id, paper_id, state")
        .eq("paper_id", kept)
        .execute()
        .data
    )
    assert sorted((r["project_id"], r["state"]) for r in rows) == sorted(
        [(pj["id"], "in"), (pj2["id"], "in")]
    )


def test_delete_account(world, api, admin):
    owner, email, t_owner = world.user()
    mate, _, _ = world.user()
    team = world.lab(mate, owner)  # mate owns the lab, so the owner may leave it
    private = create(api, t_owner, team)
    shared = create(api, t_owner, team, visibility="lab")

    r = httpx.post(
        f"{REST}/rpc/delete_account",
        headers=bearer(SERVICE),
        json={"p_user": owner, "p_confirm_email": email},
    )
    assert r.status_code == 200, r.text
    left = {
        p["id"]: p
        for p in admin.table("projects")
        .select("id, owner_id")
        .in_("id", [private["id"], shared["id"]])
        .execute()
        .data
    }
    assert list(left) == [shared["id"]] and left[shared["id"]]["owner_id"] is None


def test_leaving_the_lab(world, api, admin):
    boss, _, t_boss = world.user()
    owner, _, t_owner = world.user()
    mate, _, t_mate = world.user()
    team = world.lab(boss, owner, mate)
    private = create(api, t_owner, team)
    alone = create(api, t_owner, team, visibility="people")
    shared = create(api, t_owner, team, visibility="people")
    rest(t_owner, "POST", "project_people", json={"project_id": shared["id"], "user_id": mate})
    paper = world.paper(team, vec((1, 1.0)))
    rest(
        t_owner,
        "POST",
        "project_papers",
        json={"project_id": shared["id"], "paper_id": paper, "added_by": owner},
    )
    theirs = create(api, t_mate, team, visibility="people")
    rest(t_mate, "POST", "project_people", json={"project_id": theirs["id"], "user_id": owner})

    admin.table("team_members").delete().eq("team_id", team).eq("user_id", owner).execute()

    ids = [p["id"] for p in (private, alone, shared, theirs)]
    left = {
        p["id"]: p
        for p in admin.table("projects").select("id, owner_id").in_("id", ids).execute().data
    }
    # Private and shared-with-nobody go; the shared one stays, ownerless.
    assert set(left) == {shared["id"], theirs["id"]}
    assert left[shared["id"]]["owner_id"] is None
    people = admin.table("project_people").select("user_id").eq("project_id", theirs["id"])
    assert people.execute().data == []
    # The lab's owner sees the ownerless project and can remove it; others can't.
    assert seen(t_mate, shared["id"]) and seen(t_boss, shared["id"])
    papers = rest(t_boss, "GET", f"project_papers?project_id=eq.{shared['id']}").json()
    assert [p["paper_id"] for p in papers] == [paper]  # what they'd be deleting
    assert rest(t_mate, "DELETE", f"projects?id=eq.{shared['id']}").json() == []
    assert len(rest(t_boss, "DELETE", f"projects?id=eq.{shared['id']}").json()) == 1
