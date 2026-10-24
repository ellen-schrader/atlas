"""The clinical trials tools are listed and runnable only for people who have
the feature (atlas_mcp/http.AtlasMCP); offline, with the entitlement stubbed.
The end-to-end check against a local Supabase is test_mcp_trials_integration.py."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from atlas_mcp import features, http, lab, trials  # noqa: E402


def _server():
    return http.build_mcp(
        "https://atlas.test", "http://127.0.0.1:54321", verifier=SimpleNamespace()
    )


def _as(monkeypatch, subject: str | None, allowed: set[str]):
    token = SimpleNamespace(subject=subject, token="t") if subject else None
    monkeypatch.setattr(http, "get_access_token", lambda: token)
    monkeypatch.setattr(trials, "entitled", lambda uid: uid in allowed)


def test_hidden_from_people_without_the_feature(monkeypatch):
    _as(monkeypatch, "bob", allowed={"ada"})
    names = {t.name for t in asyncio.run(_server().list_tools())}
    assert names and not names & trials.TRIAL_TOOL_NAMES
    assert "search_lab_papers" in names  # everything else as before


def test_listed_for_people_with_it(monkeypatch):
    _as(monkeypatch, "ada", allowed={"ada"})
    names = {t.name for t in asyncio.run(_server().list_tools())}
    assert trials.TRIAL_TOOL_NAMES <= names


def test_calling_a_hidden_tool_by_name_is_an_unknown_tool(monkeypatch):
    _as(monkeypatch, "bob", allowed={"ada"})
    with pytest.raises(ToolError, match="Unknown tool: get_trial"):
        asyncio.run(_server().call_tool("get_trial", {"trial": "NCT03036488"}))


def test_hidden_when_entitlement_cant_be_checked(monkeypatch):
    monkeypatch.setattr(http, "get_access_token", lambda: SimpleNamespace(subject="ada", token="t"))

    def broken(_uid):
        raise RuntimeError("database down")

    monkeypatch.setattr(trials, "entitled", broken)
    names = {t.name for t in asyncio.run(_server().list_tools())}
    assert not names & trials.TRIAL_TOOL_NAMES


def test_hidden_without_a_token(monkeypatch):
    _as(monkeypatch, None, allowed={"ada"})
    names = {t.name for t in asyncio.run(_server().list_tools())}
    assert not names & trials.TRIAL_TOOL_NAMES


# --- the per-lab check inside every tool -------------------------------------------------


class _Svc:
    def __init__(self, team_on: bool, user_on: bool):
        self.on = {"team_features": team_on, "user_features": user_on}

    def table(self, name):
        on = self.on.get(name, False)

        class Q:
            def __getattr__(self, _a):
                return lambda *a, **k: self

            def execute(self):
                return SimpleNamespace(data=[{"x": 1}] if on else [])

        return Q()


@pytest.mark.parametrize(
    ("team_on", "user_on", "ok"),
    [(True, False, True), (False, True, True), (False, False, False)],
)
def test_each_tool_checks_the_lab_switch(monkeypatch, team_on, user_on, ok):
    monkeypatch.setattr(lab, "resolve_team", lambda _t: {"id": "lab", "name": "Lab"})
    monkeypatch.setattr(lab, "current_user_id", lambda: "ada")
    monkeypatch.setattr(features, "service_client", lambda: _Svc(team_on, user_on))
    if ok:
        assert trials._team(None)["id"] == "lab"
    else:
        with pytest.raises(lab.LabError, match="isn't switched on"):
            trials._team(None)


def test_find_by_nct_or_name(monkeypatch):
    monkeypatch.setattr(
        trials,
        "_lab_trials",
        lambda _t: [
            {
                "id": "t1",
                "nct_id": "NCT03036488",
                "acronym": "KEYNOTE-522",
                "name": "KN522",
                "title": "x",
            }
        ],
    )
    assert trials._find("lab", "nct03036488")["id"] == "t1"
    assert trials._find("lab", "keynote-522")["id"] == "t1"
    assert trials._find("lab", "KN522")["id"] == "t1"
    with pytest.raises(lab.LabError, match="isn't on this lab's list"):
        trials._find("lab", "NeoTRIP")


# --- what record_trial_extraction accepts -------------------------------------------------

import copy  # noqa: E402

from paper_radar.trials.extraction import DIMENSIONS, Extraction  # noqa: E402
from tests.test_trial_extract import VALID  # noqa: E402


def _with_dimension(key, labels):
    data = copy.deepcopy(VALID)
    data["enrolment"]["dimensions"] = [
        {
            "key": key,
            "categories": [
                {
                    "label": label,
                    "eligibility": "allowed",
                    "condition": None,
                    "overall_pct": 50.0,
                    "exp_pct": 50.0,
                    "ctrl_pct": 50.0,
                }
                for label in labels
            ],
            "not_reported_pct": None,
            "assay": None,
            "source": None,
        }
    ]
    return Extraction.model_validate(data)


def test_record_refuses_categories_atlas_cant_show():
    assert trials._bad_categories(_with_dimension("nodal_status", ["N0", "N1", "N2–3"])) == []
    bad = trials._bad_categories(_with_dimension("menopausal_status", ["Premenopausal", "Post"]))
    assert bad == ["menopausal_status 'Premenopausal'"]
    # Close isn't enough: a hyphen for the en dash, or a paper's own band.
    assert trials._bad_categories(_with_dimension("nodal_status", ["N2-3"])) != []
    assert trials._bad_categories(_with_dimension("age", ["<65"])) != []


def test_the_tool_lists_every_category_it_accepts():
    doc = trials.record_trial_extraction.__doc__
    for key, (_name, labels) in DIMENSIONS.items():
        assert key in doc
        for label in labels:
            assert label in doc, (key, label)
