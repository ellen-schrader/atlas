"""Clinical trials, PR 6: the daily registry refresh and the PubMed hint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.trials as trials_api
from api import trials_refresh as tr
from api.app import app
from paper_radar.trials import ctgov, pubmed


def rec(**k) -> ctgov.TrialRecord:
    base = dict(
        nct_id="NCT00000001",
        title="T",
        status="RECRUITING",
        has_results=False,
        registry_updated_at="2026-10-01",
    )
    return ctgov.TrialRecord(**{**base, **k})


OLD = {"status": "RECRUITING", "has_results": False, "registry_updated_at": "2026-09-01"}


def test_no_events_when_the_registry_hasnt_moved():
    assert tr.changes({**OLD, "registry_updated_at": "2026-10-01"}, rec()) == []
    assert tr.changes(OLD, rec(registry_updated_at=None)) == []


def test_events_say_what_changed():
    assert tr.changes(OLD, rec()) == [("registry_updated", {"date": "2026-10-01"})]
    assert tr.changes(OLD, rec(status="COMPLETED")) == [
        ("status_changed", {"from": "RECRUITING", "to": "COMPLETED"})
    ]
    assert [k for k, _ in tr.changes(OLD, rec(status="COMPLETED", has_results=True))] == [
        "results_posted",
        "status_changed",
    ]


class _Svc:
    def __init__(self, posts):
        self.posts = posts
        self.inserts: list = []

    def table(self, name):
        svc = self

        class Q:
            def __getattr__(self, _a):
                return lambda *a, **k: self

            def insert(self, rows):
                svc.inserts.append((name, rows))
                return self

            def execute(self):
                return SimpleNamespace(data=svc.posts if name == "trial_posts" else [])

        return Q()


@pytest.fixture(autouse=True)
def no_open_access(monkeypatch):
    """run() ends by fetching open access; these tests are about the registry."""
    from api import trial_extract

    monkeypatch.setattr(trial_extract, "fetch_missing_open_access", lambda _teams: 0)


def test_run_tells_every_lab_holding_the_trial(monkeypatch):
    t = {"id": "t1", "nct_id": "NCT00000001", **OLD}
    svc = _Svc([{"team_id": "a", "trials": t}, {"team_id": "b", "trials": t}])
    monkeypatch.setattr(tr, "service_client", lambda: svc)
    monkeypatch.setattr(tr, "active_teams", lambda: {"a", "b"})
    monkeypatch.setattr(tr, "upsert_trial", lambda _s, _r: "t1")
    monkeypatch.setattr(ctgov, "fetch", lambda _n: rec(status="COMPLETED"))
    assert tr.run() == 1
    [(table, rows)] = svc.inserts
    assert table == "trial_events"
    assert {(r["team_id"], r["kind"]) for r in rows} == {
        ("a", "status_changed"),
        ("b", "status_changed"),
    }


def test_run_skips_one_bad_record_but_stops_when_the_registry_is_down(monkeypatch):
    posts = [
        {"team_id": "a", "trials": {"id": f"t{i}", "nct_id": f"NCT0000000{i}", **OLD}}
        for i in range(5)
    ]
    monkeypatch.setattr(tr, "service_client", lambda: _Svc(posts))
    monkeypatch.setattr(tr, "active_teams", lambda: {"a"})
    monkeypatch.setattr(tr, "upsert_trial", lambda _s, _r: None)
    asked = []

    def flaky(nct):
        asked.append(nct)
        if nct == "NCT00000000":
            raise ctgov.RegistryError("record too large")
        return None

    monkeypatch.setattr(ctgov, "fetch", flaky)
    assert tr.run() == 0
    assert len(asked) == 5  # the bad one was skipped, the rest still checked

    def down(nct):
        asked.append(nct)
        raise ctgov.RegistryError("503")

    asked.clear()
    monkeypatch.setattr(ctgov, "fetch", down)
    with pytest.raises(SystemExit):
        tr.run()
    assert len(asked) == tr.MAX_FAILURES


def test_events_are_stored_before_the_record(monkeypatch):
    t = {"id": "t1", "nct_id": "NCT00000001", **OLD}
    order = []
    svc = _Svc([{"team_id": "a", "trials": t}])
    real_table = svc.table

    def table(name):
        q = real_table(name)
        if name == "trial_events":
            order.append("events")
        return q

    svc.table = table
    monkeypatch.setattr(tr, "service_client", lambda: svc)
    monkeypatch.setattr(tr, "active_teams", lambda: {"a"})
    monkeypatch.setattr(tr, "upsert_trial", lambda _s, _r: order.append("record"))
    monkeypatch.setattr(ctgov, "fetch", lambda _n: rec())
    tr.run()
    assert order == ["events", "record"]


def test_run_does_nothing_without_active_labs(monkeypatch):
    monkeypatch.setattr(tr, "active_teams", lambda: set())
    monkeypatch.setattr(tr, "service_client", lambda: pytest.fail("must not read"))
    assert tr.run() == 0


# --- PubMed -------------------------------------------------------------------------


def test_papers_naming(monkeypatch):
    calls = []

    def get(path, params):
        calls.append((path, params))
        if path == "esearch.fcgi":
            return {"esearchresult": {"count": "9", "idlist": ["39282906", "x"]}}
        return {
            "result": {
                "39282906": {
                    "title": "Overall Survival with Pembrolizumab",
                    "source": "N Engl J Med",
                    "pubdate": "2024 Nov 28",
                    "articleids": [{"idtype": "doi", "value": "10.1056/NEJMoa2409932"}],
                }
            }
        }

    monkeypatch.setattr(pubmed, "_get", get)
    count, papers = pubmed.papers_naming("NCT03036488")
    assert count == 9
    assert [(p.pmid, p.doi, p.year) for p in papers] == [
        ("39282906", "10.1056/nejmoa2409932", "2024")
    ]
    assert calls[0][1]["term"] == "NCT03036488[si]"
    with pytest.raises(ValueError):
        pubmed.papers_naming("NCT1; drop")


def test_pubmed_endpoint_leaves_out_papers_the_lab_has(monkeypatch):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    monkeypatch.setattr(trials_api._pubmed_limiter, "check", lambda _u: None)

    class Rows:
        def __init__(self, data):
            self.data = data

        def __getattr__(self, _a):
            return lambda *a, **k: self

        def execute(self):
            return SimpleNamespace(data=self.data)

    monkeypatch.setattr(
        trials_api,
        "service_client",
        lambda: SimpleNamespace(table=lambda _n: Rows([{"nct_id": "NCT03036488"}])),
    )
    monkeypatch.setattr(
        trials_api,
        "user_client",
        # One answer for both lookups: a paper held by DOI, one by its PubMed page.
        lambda _t: SimpleNamespace(
            table=lambda _n: Rows(
                [
                    {"papers": {"doi": "10.1/held", "url_norm": "x"}},
                    {"papers": {"doi": None, "url_norm": "//pubmed.ncbi.nlm.nih.gov/3"}},
                ]
            )
        ),
    )
    monkeypatch.setattr(
        pubmed,
        "papers_naming",
        lambda _n: (
            5,
            [
                pubmed.PubMedPaper("1", "Held", None, None, "10.1/held"),
                pubmed.PubMedPaper("2", "New", "J", "2025", "10.1/new"),
                pubmed.PubMedPaper("3", "Held, no DOI", None, None, None),
            ],
        ),
    )
    r = TestClient(app).get(
        "/trials/t1/pubmed", params={"team_id": "lab"}, headers={"Authorization": "Bearer t"}
    )
    assert r.status_code == 200
    body = r.json()
    assert (body["count"], body["checked"]) == (5, 3)
    assert [p["pmid"] for p in body["not_in_lab"]] == ["2"]
