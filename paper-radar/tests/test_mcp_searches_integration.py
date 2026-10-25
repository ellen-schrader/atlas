"""The saved searches tools (atlas_mcp/searches.py), end to end against a local
Supabase: real connector tokens and database, the tools called as the caller
the way the hosted server calls them; the literature sources stubbed.

    ATLAS_INTEGRATION=1 uv run --extra api --extra mcp --extra dev \\
        pytest tests/test_mcp_searches_integration.py

What it holds the tools to: a search saved from Claude previews first and then
files suggestions for its owner alone; importing previews first and then posts
to the lab as that person; nobody can answer another person's suggestions;
and in a lab without the feature every tool refuses. Which tools are listed to
whom is test_mcp_searches.py's.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

pytest.importorskip("mcp")

import httpx  # noqa: E402

from api import paper_identity  # noqa: E402
from api import saved_searches as ss  # noqa: E402
from api.config import get_api_settings  # noqa: E402
from api.supa import _anon_client, service_client  # noqa: E402
from atlas_mcp import features, http, lab, searches  # noqa: E402
from paper_radar.ingest.metadata import PaperMetadata  # noqa: E402
from paper_radar.search import sources  # noqa: E402
from paper_radar.search.sources import Hit  # noqa: E402
from tests.local_supabase import (  # noqa: E402
    ANON,
    AUTH,
    LOCAL_URL,
    REST,
    SERVICE,
    bearer,
    connector_token,
    oauth_server_on,
)

PASSWORD = "mcp-searches-test-only"


class _Now:
    """threading.Thread stand-in: runs the target at once, so the test sees
    the background import and first run finished."""

    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture(autouse=True)
def _local(monkeypatch):
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
    monkeypatch.setattr(searches.threading, "Thread", _Now)
    features._enabled_cache.clear()
    yield
    for cached in (get_api_settings, service_client, _anon_client):
        cached.cache_clear()


@pytest.fixture
def world():
    if not oauth_server_on():
        pytest.skip("local Supabase OAuth server is off ([auth.oauth_server] in config.toml)")
    w = _World()
    yield w
    w.cleanup()


class _World:
    def __init__(self) -> None:
        self.admin = bearer(SERVICE)
        self.users: list[str] = []
        self.teams: list[str] = []
        self.dois: list[str] = []
        self.tag = uuid.uuid4().hex[:8]

    def _post(self, table: str, row: dict) -> None:
        httpx.post(f"{REST}/{table}", headers=self.admin, json=row).raise_for_status()

    def user(self) -> tuple[str, str]:
        """(user id, web token)."""
        email = f"mcpss-{uuid.uuid4().hex[:8]}@example.test"
        uid = httpx.post(
            f"{AUTH}/admin/users",
            headers=self.admin,
            json={"email": email, "password": PASSWORD, "email_confirm": True},
        ).json()["id"]
        self.users.append(uid)
        web = httpx.post(
            f"{AUTH}/token?grant_type=password",
            headers={"apikey": ANON},
            json={"email": email, "password": PASSWORD},
        ).json()["access_token"]
        return uid, web

    def lab(self, owner: tuple[str, str], *members: str, feature: bool = True) -> str:
        """A lab with Claude access on; ``owner`` is (id, web token)."""
        tid = str(uuid.uuid4())
        self.teams.append(tid)
        self._post(
            "teams",
            {"id": tid, "name": f"MS {tid[:8]}", "slug": f"ms-{tid[:8]}", "created_by": owner[0]},
        )
        self._post("team_members", {"team_id": tid, "user_id": owner[0], "role": "owner"})
        for uid in members:
            self._post("team_members", {"team_id": tid, "user_id": uid, "role": "member"})
        if feature:
            self._post("team_features", {"team_id": tid, "feature": ss.FEATURE})
        httpx.post(
            f"{REST}/rpc/set_mcp_access",
            headers=bearer(owner[1]),
            json={"p_team": tid, "p_enabled": True},
        ).raise_for_status()
        return tid

    def hit(self, n: int) -> Hit:
        doi = f"10.9999/mcpss-{self.tag}-{n}"
        self.dois.append(doi)
        return Hit(
            source="pubmed",
            url=f"https://doi.org/{doi}",
            title=f"Claude-found paper {n}",
            doi=doi,
            pmid=str(800000 + n),
            authors=["Ada Lovelace"],
            venue="Journal",
            published_on="2026-10-20",
            abstract="Tertiary lymphoid structures in tumours.",
        )

    def cleanup(self) -> None:
        for tid in self.teams:
            httpx.delete(f"{REST}/teams?id=eq.{tid}", headers=self.admin)
        for doi in self.dois:
            httpx.delete(f"{REST}/search_candidates?doi=eq.{doi}", headers=self.admin)
            httpx.delete(f"{REST}/papers?doi=eq.{doi}", headers=self.admin)
        for uid in self.users:
            httpx.delete(f"{AUTH}/admin/users/{uid}", headers=self.admin)


def _as(person: tuple[str, str], tool, **kwargs) -> str:
    """Call ``tool`` as ``person`` (id, connector token), as the hosted server does."""
    uid, token = person

    async def run():
        result = tool(**kwargs)
        return await result if asyncio.iscoroutine(result) else result

    with lab.act_as(token, uid, client=http._pooled_client(token)):
        return asyncio.run(run())


def _connected(world) -> tuple[tuple[str, str], tuple[str, str], str]:
    """Two members of a lab with the feature, each connected through Claude."""
    a_id, a_web = world.user()
    b_id, b_web = world.user()
    team = world.lab((a_id, a_web), b_id)
    return (a_id, connector_token(a_web)[0]), (b_id, connector_token(b_web)[0]), team


def _suggestion_ids(text: str) -> list[str]:
    return [
        line.split("suggestion id: ")[1].strip()
        for line in text.splitlines()
        if "suggestion id: " in line
    ]


def test_saving_previews_then_files_suggestions_for_its_owner_alone(world, monkeypatch):
    a, b, team = _connected(world)
    monkeypatch.setattr(sources, "search_pubmed", lambda *a_, **k: [world.hit(1), world.hit(2)])
    args = {"name": "TLS", "query": "tertiary lymphoid[tiab]", "sources": ["pubmed"]}

    preview = _as(a, searches.create_saved_search, **args)
    assert "PubMed: 2 in the past week" in preview and "Claude-found paper 1" in preview
    assert "Nothing saved yet" in preview
    assert "You have no saved searches" in _as(a, searches.list_saved_searches)

    saved = _as(a, searches.create_saved_search, confirm=True, **args)
    assert saved.startswith("Saved [TLS]")
    listing = _as(a, searches.list_saved_searches)
    assert "TLS: tertiary lymphoid[tiab]" in listing and "2 waiting" in listing
    found = _as(a, searches.list_suggestions)
    assert "2 suggestions waiting" in found and "found by: TLS" in found
    assert len(_suggestion_ids(found)) == 2
    past = _as(a, searches.list_suggestions, search="TLS", offset=2)
    assert past == "Only 2 suggestions are waiting; nothing past 2."

    # B shares the lab but not the search, nor its suggestions.
    assert "You have no saved searches" in _as(b, searches.list_saved_searches)
    assert "No suggestions waiting" in _as(b, searches.list_suggestions)


def test_a_bad_query_is_refused_in_words(world):
    a, _b, _team = _connected(world)
    out = _as(a, searches.create_saved_search, name="x", query="(tertiary AND", confirm=True)
    assert out.startswith("Error:") and "expected" in out


def test_importing_previews_then_posts_as_the_person(world, monkeypatch):
    a, b, team = _connected(world)
    monkeypatch.setattr(sources, "search_pubmed", lambda *a_, **k: [world.hit(1), world.hit(2)])
    _as(
        a,
        searches.create_saved_search,
        name="TLS",
        query="tertiary",
        sources=["pubmed"],
        confirm=True,
    )
    first, second = _suggestion_ids(_as(a, searches.list_suggestions))

    # B can't answer A's suggestions, either way.
    assert "none of those" in _as(b, searches.import_suggestions, suggestion_ids=[first])
    assert "none of those" in _as(b, searches.dismiss_suggestions, suggestion_ids=[first])

    preview = _as(a, searches.import_suggestions, suggestion_ids=[first])
    assert "About to add 1 papers" in preview and "Nothing imported yet" in preview
    out = _as(
        a, searches.import_suggestions, suggestion_ids=[first, str(uuid.uuid4())], confirm=True
    )
    assert out.startswith("Importing 1 papers") and "1 of the ids weren't" in out

    svc = service_client()
    posts = (
        svc.table("paper_posts")
        .select("posted_by, source, papers!inner(doi)")
        .eq("team_id", team)
        .execute()
        .data
    )
    assert [(p["posted_by"], p["source"]) for p in posts] == [(a[0], "saved_search")]

    assert _as(a, searches.dismiss_suggestions, suggestion_ids=[second]) == "Dismissed 1."
    assert "No suggestions waiting" in _as(a, searches.list_suggestions)
    assert "Those aren't suggestion ids" in _as(
        a, searches.dismiss_suggestions, suggestion_ids=["7"]
    )


def test_every_tool_refuses_in_a_lab_without_the_feature(world):
    c_id, c_web = world.user()
    team = world.lab((c_id, c_web), feature=False)
    c = (c_id, connector_token(c_web)[0])
    assert not searches.entitled(c_id)
    calls = [
        (searches.list_saved_searches, {}),
        (searches.list_suggestions, {}),
        (searches.import_suggestions, {"suggestion_ids": [str(uuid.uuid4())]}),
        (searches.dismiss_suggestions, {"suggestion_ids": [str(uuid.uuid4())]}),
        (searches.create_saved_search, {"name": "x", "query": "tls"}),
    ]
    for tool, kwargs in calls:
        out = _as(c, tool, team_id=team, **kwargs)
        assert out == f"Error: {searches.NOT_AVAILABLE}", (tool.__name__, out)


def test_saving_at_the_cap_is_refused_before_anything_is_searched(world, monkeypatch):
    a, _b, team = _connected(world)
    svc = service_client()
    svc.table("saved_searches").insert(
        [
            {"user_id": a[0], "team_id": team, "name": f"s{i}", "query": "x", "sources": ["pubmed"]}
            for i in range(ss.MAX_SEARCHES)
        ]
    ).execute()

    def no_search(*_a, **_k):
        raise AssertionError("searched although saving would be refused")

    monkeypatch.setattr(sources, "search_pubmed", no_search)
    out = _as(a, searches.create_saved_search, name="TLS", query="tertiary")
    assert out == f"Error: You have {ss.MAX_SEARCHES} saved searches; delete one first."


def test_a_searchs_suggestions_page_past_the_newest(world, monkeypatch):
    a, _b, team = _connected(world)
    hits = [world.hit(n) for n in range(1, 8)]
    for name, found in (("Old", hits[:3]), ("New", hits[3:])):
        monkeypatch.setattr(sources, "search_pubmed", lambda *a_, f=found, **k: list(f))
        _as(
            a,
            searches.create_saved_search,
            name=name,
            query="tertiary",
            sources=["pubmed"],
            confirm=True,
        )
    first = _as(a, searches.list_suggestions, search="old", limit=2)
    assert first.startswith("3 suggestions waiting") and "showing 2 from 1" in first
    assert "found by: New" not in first and "offset=2" in first
    rest = _as(a, searches.list_suggestions, search="Old", limit=2, offset=2)
    assert len(_suggestion_ids(rest)) == 1 and "more:" not in rest
    assert _as(a, searches.list_suggestions).startswith("7 suggestions waiting")
