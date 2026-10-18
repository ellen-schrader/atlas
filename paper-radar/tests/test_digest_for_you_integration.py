"""The digest's "For you" and recommend_reading, end to end against a real (local)
Supabase: the caller's signals read through RLS and my_recommendation_inputs(),
ranked the way the app's Discover feed ranks (api/taste.py).

One lab, two members. Ada posted one paper from Teams (so it carries only her
name), follows a tag, and has a research profile. Bo posted the rest: two papers
close to Ada's, one far from everything she reads but carrying her followed tag,
and one far and untagged.

Opt-in, because it creates (and removes) users in the database:

    ATLAS_INTEGRATION=1 uv run --extra mcp --extra dev \\
        pytest tests/test_digest_for_you_integration.py
"""

from __future__ import annotations

import os
import uuid

import pytest

pytest.importorskip("mcp")

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

from api.config import get_api_settings  # noqa: E402
from atlas_mcp import lab, papers  # noqa: E402
from supabase import ClientOptions, create_client  # noqa: E402

from .test_mcp_isolation_integration import ANON, LOCAL_URL, PASSWORD, SERVICE  # noqa: E402

DIM = 1024


def _axis(*weights: tuple[int, float]) -> str:
    """A unit vector with the given (axis, weight) components, as pgvector text."""
    v = [0.0] * DIM
    for i, w in weights:
        v[i] = w
    n = sum(x * x for x in v) ** 0.5
    return "[" + ",".join(f"{x / n:.6f}" for x in v) + "]"


@pytest.fixture(scope="module")
def world():
    admin = create_client(LOCAL_URL, SERVICE)
    tag = uuid.uuid4().hex[:8]
    team = str(uuid.uuid4())
    p = {k: str(uuid.uuid4()) for k in ("ada_teams", "close1", "close2", "tagged", "far")}
    users = {}
    try:
        for who in ("ada", "bo"):
            users[who] = admin.auth.admin.create_user(
                {
                    "email": f"foryou-{who}-{tag}@example.test",
                    "password": PASSWORD,
                    "email_confirm": True,
                }
            ).user.id
        admin.table("profiles").update({"display_name": "Ada Lovelace", "interests": ["ffpe"]}).eq(
            "id", users["ada"]
        ).execute()
        admin.table("teams").insert(
            {
                "id": team,
                "name": f"For-you lab {tag}",
                "slug": f"foryou-{tag}",
                "created_by": users["ada"],
            }
        ).execute()
        admin.table("team_members").insert(
            [
                {"team_id": team, "user_id": users["ada"], "role": "owner"},
                {"team_id": team, "user_id": users["bo"], "role": "member"},
            ]
        ).execute()
        vectors = {
            "ada_teams": _axis((0, 1.0)),
            "close1": _axis((0, 1.0), (1, 0.2)),
            "close2": _axis((0, 1.0), (2, 0.25)),
            "tagged": _axis((500, 1.0)),
            "far": _axis((700, 1.0)),
        }
        for k, pid in p.items():
            admin.table("papers").insert(
                {
                    "id": pid,
                    "url": f"https://foryou.test/{tag}/{k}",
                    "url_norm": f"foryou-{tag}-{k}",
                    "title": f"For-you {k} {tag}",
                    "abstract": f"Abstract of {k}.",
                    "embedding": vectors[k],
                    "tags": ["ffpe"] if k == "tagged" else [],
                }
            ).execute()
        admin.table("paper_posts").insert(
            {
                "paper_id": p["ada_teams"],
                "team_id": team,
                "posted_by": None,
                "posted_by_label": "Lovelace, Ada",
                "source": "teams",
            }
        ).execute()
        for k in ("close1", "close2", "tagged", "far"):
            admin.table("paper_posts").insert(
                {"paper_id": p[k], "team_id": team, "posted_by": users["bo"], "source": "web"}
            ).execute()
        token = (
            create_client(LOCAL_URL, ANON)
            .auth.sign_in_with_password(
                {"email": f"foryou-ada-{tag}@example.test", "password": PASSWORD}
            )
            .session.access_token
        )
        # As the owner, the way the web app's Connect screen does it.
        create_client(
            LOCAL_URL,
            ANON,
            options=ClientOptions(headers={"Authorization": f"Bearer {token}"}),
        ).rpc("set_mcp_access", {"p_team": team, "p_enabled": True}).execute()
        yield {"team": team, "p": p, "ada": users["ada"], "token": token}
    finally:
        admin.table("teams").delete().eq("id", team).execute()
        admin.table("papers").delete().in_("id", list(p.values())).execute()
        for uid in users.values():
            admin.auth.admin.delete_user(uid)


def test_for_you_picks_by_your_teams_post_and_followed_tag(world):
    p = world["p"]
    with lab.act_as(world["token"], world["ada"]):
        d = lab.digest({"id": world["team"], "name": "For-you lab"}, days=7)
    picks = {h["paper_id"]: h["reason"] for h in d["for_you"]}
    assert set(picks) == {p["close1"], p["close2"], p["tagged"]}
    # Close to the paper Ada posted from Teams, and said so, naming it.
    assert picks[p["close1"]]["kind"] == "similar_posted"
    assert picks[p["close1"]]["ref_id"] == p["ada_teams"]
    assert picks[p["tagged"]]["kind"] == "tag"
    # Her own post and the far, untagged paper are not picks.
    assert p["ada_teams"] not in picks and p["far"] not in picks


def test_the_digest_reads_as_designed(world):
    p = world["p"]
    with lab.act_as(world["token"], world["ada"]):
        out = papers.lab_digest(days=7, team_id=world["team"])
    for_you, rest = out.split("### All new papers")
    assert p["close1"] in for_you and "which you shared" in for_you
    assert "Tagged ffpe, which you follow" in for_you
    assert p["far"] not in for_you and p["far"] in rest
    assert "How to present this digest" in out


def test_recommend_reading_uses_the_same_signals(world):
    p = world["p"]
    with lab.act_as(world["token"], world["ada"]):
        out = papers.recommend_reading(limit=3, team_id=world["team"])
    assert "Why: Similar to " in out and "which you shared" in out
    # Her own Teams post is never recommended back to her (it is named only as a reason).
    assert f"papers?paper={p['ada_teams']})**" not in out


@pytest.fixture(autouse=True)
def _local_settings(monkeypatch):
    """Point the data layer at the local stack (api/.env may name a real project),
    as the hosted server would: no environment user."""
    monkeypatch.setenv("SUPABASE_URL", LOCAL_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    get_api_settings.cache_clear()
    reset = lab._env_session_allowed.set(False)
    yield
    lab._env_session_allowed.reset(reset)
    get_api_settings.cache_clear()
