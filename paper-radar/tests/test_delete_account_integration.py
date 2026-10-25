"""Self-service account deletion, end to end against a real (local) Supabase.

What `delete_account` and POST /account/delete promise (docs/ACCOUNT_DELETION_PLAN.md):
a person's contributions to a shared lab stay, without their name; their personal
data goes; a last owner can't strand other members; a lab they're alone in goes
with them, files and removal records included; undo still works for papers they
posted; a lab owner may remove what a former member left, and nothing more; and
only the API, for the user it verified, can run it.

Opt-in, because it creates (and removes) users in the database:

    ATLAS_INTEGRATION=1 uv run --extra api --extra mcp --extra dev \\
        pytest tests/test_delete_account_integration.py

It refuses to run against anything but a local Supabase (127.0.0.1 / localhost).
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api.config import get_api_settings  # noqa: E402
from api.supa import _anon_client, service_client  # noqa: E402
from supabase import create_client  # noqa: E402
from tests.local_supabase import (  # noqa: E402
    ANON,
    LOCAL_URL,
    REST,
    SERVICE,
    bearer,
    connector_token,
    oauth_server_on,
)

PASSWORD = "delete-account-test-only"
PNG = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _local_settings(monkeypatch):
    """Point the API at the local stack (api/.env may name a real project)."""
    monkeypatch.setenv("SUPABASE_URL", LOCAL_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE)
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()
    yield
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()


@pytest.fixture
def admin():
    return create_client(LOCAL_URL, SERVICE)


class World:
    """Users and labs made for one test, removed afterwards whatever happened."""

    def __init__(self, admin) -> None:
        self.admin = admin
        self.users: list[str] = []
        self.teams: list[str] = []
        self.papers: list[str] = []
        self.files: list[str] = []

    def user(self, name: str) -> tuple[str, str, str]:
        """(user_id, email, web access token)."""
        email = f"delete-{name}-{uuid.uuid4().hex[:8]}@example.test"
        uid = self.admin.auth.admin.create_user(
            {"email": email, "password": PASSWORD, "email_confirm": True}
        ).user.id
        self.users.append(uid)
        token = (
            create_client(LOCAL_URL, ANON)
            .auth.sign_in_with_password({"email": email, "password": PASSWORD})
            .session.access_token
        )
        return uid, email, token

    def lab(self, *members: tuple[str, str]) -> str:
        """A lab with (user_id, role) members."""
        tid = str(uuid.uuid4())
        self.teams.append(tid)
        self.admin.table("teams").insert(
            {
                "id": tid,
                "name": f"Delete test {tid[:8]}",
                "slug": f"del-{tid[:8]}",
                "created_by": members[0][0],
            }
        ).execute()
        for uid, role in members:
            self.admin.table("team_members").insert(
                {"team_id": tid, "user_id": uid, "role": role}
            ).execute()
        return tid

    def paper(self, team_id: str, posted_by: str) -> str:
        pid = str(uuid.uuid4())
        self.papers.append(pid)
        self.admin.table("papers").insert(
            {
                "id": pid,
                "url": f"https://example.test/{pid}",
                "url_norm": pid,
                "title": f"Paper {pid[:8]}",
            }
        ).execute()
        self.admin.table("paper_posts").insert(
            {"paper_id": pid, "team_id": team_id, "posted_by": posted_by, "source": "web"}
        ).execute()
        return pid

    def figure(self, team_id: str, uploaded_by: str) -> str:
        """A figure row plus its file; returns the storage path."""
        fid = str(uuid.uuid4())
        path = f"{team_id}/{fid}.png"
        self.admin.storage.from_("figures").upload(path, PNG, {"content-type": "image/png"})
        self.files.append(path)
        self.admin.table("figures").insert(
            {
                "id": fid,
                "team_id": team_id,
                "uploaded_by": uploaded_by,
                "storage_path": path,
                "width": 1,
                "height": 1,
                "mime_type": "image/png",
            }
        ).execute()
        return path

    def cleanup(self) -> None:
        if self.files:
            self.admin.storage.from_("figures").remove(self.files)
        for tid in self.teams:
            self.admin.table("teams").delete().eq("id", tid).execute()
            self.admin.table("removed_posts").delete().eq("team_id", tid).execute()
        if self.papers:
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


def _rpc(user_id: str, email: str, token: str = SERVICE) -> httpx.Response:
    """delete_account as the API runs it (service role) unless another token is given."""
    return httpx.post(
        f"{REST}/rpc/delete_account",
        headers=bearer(token),
        json={"p_user": user_id, "p_confirm_email": email},
    )


def _rows(admin, table: str, **eq) -> list[dict]:
    q = admin.table(table).select("*")
    for col, val in eq.items():
        q = q.eq(col, val)
    return q.execute().data


def _files(admin, team_id: str) -> set[str]:
    return {f"{team_id}/{o['name']}" for o in admin.storage.from_("figures").list(team_id)}


def test_shared_lab_keeps_contributions_and_drops_personal_data(admin, world):
    a, a_email, _ = world.user("a")
    b, _, _ = world.user("b")
    lab = world.lab((a, "member"), (b, "owner"))
    paper = world.paper(lab, a)
    admin.table("comments").insert(
        {"paper_id": paper, "team_id": lab, "author_id": a, "body": "keep me"}
    ).execute()
    admin.table("reactions").insert(
        {"paper_id": paper, "team_id": lab, "user_id": a, "emoji": "👍"}
    ).execute()
    lab_map = (
        admin.table("maps")
        .insert(
            {"team_id": lab, "created_by": a, "name": "Lab map", "seed": "x", "visibility": "lab"}
        )
        .execute()
        .data[0]["id"]
    )
    private_map = (
        admin.table("maps")
        .insert(
            {"team_id": lab, "created_by": a, "name": "Mine", "seed": "y", "visibility": "private"}
        )
        .execute()
        .data[0]["id"]
    )

    r = _rpc(a, f" {a_email.upper()} ")  # case and spacing don't matter
    assert r.status_code == 200, r.text
    assert r.json() == []  # no solo labs

    # Gone: the person and what was only theirs.
    assert _rows(admin, "profiles", id=a) == []
    assert _rows(admin, "team_members", user_id=a) == []
    assert _rows(admin, "reactions", user_id=a) == []
    assert _rows(admin, "maps", id=private_map) == []
    # Stays, anonymised: what they contributed to the lab.
    assert _rows(admin, "paper_posts", paper_id=paper)[0]["posted_by"] is None
    comment = _rows(admin, "comments", paper_id=paper)
    assert [c["body"] for c in comment] == ["keep me"] and comment[0]["author_id"] is None
    assert _rows(admin, "maps", id=lab_map)[0]["created_by"] is None
    # The other member and the lab are untouched.
    assert [m["user_id"] for m in _rows(admin, "team_members", team_id=lab)] == [b]


def test_last_owner_with_members_is_refused_and_nothing_changes(admin, world):
    a, a_email, _ = world.user("a")
    b, _, _ = world.user("b")
    lab = world.lab((a, "owner"), (b, "member"))

    r = _rpc(a, a_email)
    assert r.status_code == 400, r.text
    assert "Make someone else an owner" in r.json()["message"]
    assert _rows(admin, "profiles", id=a) != []
    assert len(_rows(admin, "team_members", team_id=lab)) == 2


def test_wrong_email_is_refused(admin, world):
    a, _, _ = world.user("a")
    world.lab((a, "owner"))

    r = _rpc(a, "someone-else@example.test")
    assert r.status_code == 400, r.text
    assert "doesn't match" in r.json()["message"]
    assert _rows(admin, "profiles", id=a) != []


def test_solo_lab_goes_with_the_account_but_no_other_lab(admin, world):
    a, a_email, _ = world.user("a")
    b, _, _ = world.user("b")
    solo = world.lab((a, "owner"))
    shared = world.lab((b, "owner"), (a, "member"))
    solo_paper = world.paper(solo, a)
    shared_paper = world.paper(shared, a)

    r = _rpc(a, a_email)
    assert r.status_code == 200, r.text
    assert r.json() == [solo]
    assert _rows(admin, "teams", id=solo) == []
    assert _rows(admin, "paper_posts", paper_id=solo_paper) == []
    # The cascade's removal records for the deleted lab go too.
    assert _rows(admin, "removed_posts", team_id=solo) == []
    assert _rows(admin, "teams", id=shared) != []
    assert _rows(admin, "paper_posts", paper_id=shared_paper)[0]["posted_by"] is None


def test_users_cannot_call_it_directly(admin, world):
    """Only the API may run it, so its file cleanup can't be skipped and nobody
    can name another user's id."""
    a, a_email, a_token = world.user("a")
    b, _, _ = world.user("b")
    world.lab((a, "owner"))
    for target in (a, b):
        r = _rpc(target, a_email, token=a_token)
        assert r.status_code in (401, 403, 404), r.text
    assert _rows(admin, "profiles", id=a) != [] and _rows(admin, "profiles", id=b) != []


def test_undo_still_works_for_a_removed_post_by_a_deleted_member(admin, world):
    a, a_email, _ = world.user("a")
    b, _, b_token = world.user("b")
    lab = world.lab((b, "owner"), (a, "member"))
    paper = world.paper(lab, a)
    post_id = _rows(admin, "paper_posts", paper_id=paper)[0]["id"]
    # B removes A's paper, leaving a tombstone that names A.
    admin.table("paper_posts").delete().eq("id", post_id).execute()
    assert _rows(admin, "removed_posts", id=post_id)[0]["posted_by"] == a

    assert _rpc(a, a_email).status_code == 200
    assert _rows(admin, "removed_posts", id=post_id)[0]["posted_by"] is None

    restored = httpx.post(
        f"{REST}/rpc/restore_post", headers=bearer(b_token), json={"p_post": post_id}
    )
    assert restored.status_code == 200, restored.text
    assert _rows(admin, "paper_posts", id=post_id)[0]["posted_by"] is None


def test_owner_may_remove_what_a_former_member_left_and_nothing_more(admin, world):
    a, a_email, _ = world.user("a")
    b, _, b_token = world.user("b")
    c, _, _ = world.user("c")
    lab = world.lab((b, "owner"), (a, "member"), (c, "member"))
    paper = world.paper(lab, b)
    a_file, c_file = world.figure(lab, a), world.figure(lab, c)
    for who in (a, c):
        admin.table("comments").insert(
            {"paper_id": paper, "team_id": lab, "author_id": who, "body": who}
        ).execute()
    assert _rpc(a, a_email).status_code == 200

    as_owner = httpx.Client(headers=bearer(b_token))
    remove = lambda path: as_owner.request(  # noqa: E731
        "DELETE", f"{LOCAL_URL}/storage/v1/object/figures", json={"prefixes": [path]}
    )
    # C is still a member: the owner may not delete C's file, figure or comment.
    remove(c_file)
    as_owner.delete(f"{REST}/figures", params={"storage_path": f"eq.{c_file}"})
    as_owner.delete(f"{REST}/comments", params={"author_id": f"eq.{c}"})
    assert c_file in _files(admin, lab)
    assert _rows(admin, "figures", storage_path=c_file)
    assert _rows(admin, "comments", author_id=c)
    # A's leftovers: the owner may remove them.
    remove(a_file)
    as_owner.delete(f"{REST}/figures", params={"storage_path": f"eq.{a_file}"})
    as_owner.delete(f"{REST}/comments", params={"paper_id": f"eq.{paper}", "author_id": "is.null"})
    assert a_file not in _files(admin, lab)
    assert not _rows(admin, "figures", storage_path=a_file)
    assert [x["author_id"] for x in _rows(admin, "comments", paper_id=paper)] == [c]


def test_api_route_deletes_and_removes_solo_lab_files(admin, world):
    from api.app import app

    a, a_email, a_token = world.user("a")
    solo = world.lab((a, "owner"))
    path = world.figure(solo, a)
    assert path in _files(admin, solo)

    client = TestClient(app)
    auth = {"Authorization": f"Bearer {a_token}"}
    refused = client.post(
        "/account/delete", json={"confirm_email": "nope@example.test"}, headers=auth
    )
    assert refused.status_code == 409

    ok = client.post("/account/delete", json={"confirm_email": a_email}, headers=auth)
    assert ok.status_code == 204, ok.text
    assert _rows(admin, "profiles", id=a) == []
    assert _files(admin, solo) == set()
    # The web token now gets nothing from the API.
    after = client.post("/account/delete", json={"confirm_email": a_email}, headers=auth)
    assert after.status_code == 401


@pytest.mark.skipif(
    not oauth_server_on(), reason="local OAuth server is off (supabase/config.toml)"
)
def test_connector_token_cannot_delete_and_is_revoked_after(admin, world):
    a, a_email, a_token = world.user("a")
    world.lab((a, "owner"))
    conn, _ = connector_token(a_token)

    refused = _rpc(a, a_email, token=conn)
    assert refused.status_code >= 400, refused.text
    assert _rows(admin, "profiles", id=a) != []

    assert _rpc(a, a_email).status_code == 200
    after = httpx.get(f"{REST}/teams?select=id", headers=bearer(conn))
    assert after.status_code >= 400 and "ATLAS_CONNECTOR_REVOKED" in after.text
