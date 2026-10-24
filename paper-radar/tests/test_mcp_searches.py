"""The saved searches tools are listed and runnable only for people who have
the feature (atlas_mcp/http.AtlasMCP), apart from the trials tools' switch;
offline, with the entitlements stubbed. The tools themselves, against a local
Supabase, are test_mcp_searches_integration.py's."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from atlas_mcp import http, lab, searches, trials  # noqa: E402


def _server():
    return http.build_mcp(
        "https://atlas.test", "http://127.0.0.1:54321", verifier=SimpleNamespace()
    )


def _as(monkeypatch, subject: str, searchers: set[str], trialists: set[str] = frozenset()):
    monkeypatch.setattr(
        http, "get_access_token", lambda: SimpleNamespace(subject=subject, token="t")
    )
    monkeypatch.setattr(searches, "entitled", lambda uid: uid in searchers)
    monkeypatch.setattr(trials, "entitled", lambda uid: uid in trialists)


def _names() -> set[str]:
    return {t.name for t in asyncio.run(_server().list_tools())}


def test_listed_only_with_the_feature_and_apart_from_trials(monkeypatch):
    _as(monkeypatch, "ada", searchers={"ada"})
    names = _names()
    assert searches.SEARCH_TOOL_NAMES <= names
    assert not names & trials.TRIAL_TOOL_NAMES

    _as(monkeypatch, "bob", searchers={"ada"}, trialists={"bob"})
    names = _names()
    assert not names & searches.SEARCH_TOOL_NAMES
    assert trials.TRIAL_TOOL_NAMES <= names
    assert "search_lab_papers" in names


def test_every_tool_is_registered():
    registered = set(_server()._tool_manager._tools)
    assert searches.SEARCH_TOOL_NAMES <= registered


def test_calling_a_hidden_tool_by_name_is_an_unknown_tool(monkeypatch):
    _as(monkeypatch, "bob", searchers={"ada"})
    with pytest.raises(ToolError, match="Unknown tool: list_suggestions"):
        asyncio.run(_server().call_tool("list_suggestions", {}))


def test_hidden_when_entitlement_cant_be_checked(monkeypatch):
    _as(monkeypatch, "ada", searchers=set(), trialists={"ada"})

    def broken(_uid):
        raise RuntimeError("database down")

    monkeypatch.setattr(searches, "entitled", broken)
    names = _names()
    assert not names & searches.SEARCH_TOOL_NAMES
    assert trials.TRIAL_TOOL_NAMES <= names  # one switch failing hides only its own tools


def test_suggestion_ids_are_checked():
    ok = "6f1c1a0e-2c39-4b8e-9a59-1f0a3c1d2e4f"
    assert searches._ids([ok, f" {ok.upper()} "]) == [ok]
    with pytest.raises(lab.LabError, match="aren't suggestion ids"):
        searches._ids(["paper 1"])
    with pytest.raises(lab.LabError, match="Pass the ids"):
        searches._ids([])
    with pytest.raises(lab.LabError, match="At most"):
        searches._ids([ok] * 51)


def test_a_paper_line_links_to_its_source_safely():
    line = searches._paper_line(
        {
            "title": "A [title](https://evil) here",
            "url": "https://doi.org/10.1/x",
            "source": "medrxiv",
            "authors": ["A", "B", "C", "D"],
            "venue": "medRxiv",
            "published_on": "2026-10-20",
            "abstract": "word " * 400,
        },
        abstract=True,
    )
    head, meta, abstract = line.split("\n")
    assert head == "[A (title)(https://evil) here](https://doi.org/10.1/x)"
    assert "A, B, C et al." in meta and "medRxiv" in meta
    assert len(abstract) < 620 and abstract.endswith("…")
