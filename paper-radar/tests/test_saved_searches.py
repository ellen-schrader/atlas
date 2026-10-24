"""Saved searches without a database: run windows, sources, the job's due list."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from api import saved_searches as ss
from api import saved_searches_run as run
from paper_radar.search import query as q
from paper_radar.search import sources
from paper_radar.search.sources import Hit, SourceError

TODAY = date(2026, 10, 24)


def test_first_run_looks_back_a_week_then_since_the_last_run():
    assert ss.window(None, TODAY) == (date(2026, 10, 17), TODAY)
    assert ss.window("2026-10-17T05:40:00+00:00", TODAY) == (date(2026, 10, 16), TODAY)
    # A search paused for months does not pull in months of papers.
    assert ss.window("2026-01-01T00:00:00+00:00", TODAY) == (date(2026, 9, 26), TODAY)


def _hit(source: str, doi: str) -> Hit:
    return Hit(source=source, url=f"https://doi.org/{doi}", title=doi, doi=doi)


def test_a_failing_source_does_not_stop_the_others(monkeypatch):
    def down(*a, **k):
        raise SourceError("PubMed did not answer: timed out")

    seen: list[str] = []
    monkeypatch.setattr(sources, "search_pubmed", down)
    monkeypatch.setattr(
        sources, "search_arxiv", lambda query, *a, **k: seen.append(query) or [_hit("arxiv", "a")]
    )
    feed = [
        {
            "doi": "10.1101/1",
            "server": "biorxiv",
            "title": "Tertiary lymphoid structures",
            "abstract": "",
            "authors": [],
            "posted_on": "2026-10-20",
        },
        {
            "doi": "10.1101/2",
            "server": "medrxiv",
            "title": "Something else",
            "abstract": "",
            "authors": [],
            "posted_on": "2026-10-20",
        },
        {
            "doi": "10.1101/3",
            "server": "biorxiv",
            "title": "Tertiary lymphoid, too old",
            "abstract": "",
            "authors": [],
            "posted_on": "2026-10-01",
        },
    ]
    found, errors = ss.run_query(
        "tertiary lymphoid NOT review[pt]", ss.SOURCES, date(2026, 10, 17), TODAY, feed=feed
    )
    assert errors == {"pubmed": "PubMed did not answer: timed out"}
    assert [h.doi for h in found["arxiv"]] == ["a"]
    assert seen == ["(all:tertiary AND all:lymphoid)"]  # the filter left out
    assert [h.doi for h in found["biorxiv"]] == ["10.1101/1"]
    assert found["biorxiv"][0].venue == "bioRxiv"


def test_a_filter_only_query_runs_on_pubmed_alone(monkeypatch):
    monkeypatch.setattr(sources, "search_pubmed", lambda *a, **k: [_hit("pubmed", "p")])
    monkeypatch.setattr(sources, "search_arxiv", lambda *a, **k: pytest.fail("nothing to search"))
    found, errors = ss.run_query("review[pt]", ss.SOURCES, TODAY, TODAY, feed=[])
    assert errors == {} and found["arxiv"] == [] and found["biorxiv"] == []
    assert [h.doi for h in found["pubmed"]] == ["p"]


def test_bad_query_raises():
    with pytest.raises(q.QueryError):
        ss.run_query("(tls", ["pubmed"], TODAY, TODAY, feed=None)


def test_hits_dedupe_across_sources_and_need_an_id():
    dup = [_hit("pubmed", "10.1/x"), _hit("biorxiv", "10.1/x"), Hit("pubmed", "u", "no id")]
    assert [h.source for h in ss._dedupe(dup)] == ["pubmed"]


class _Rows:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self._data = data

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        return _Rows(self._data)


class _Svc:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables.get(name, []))


def test_due_searches(monkeypatch):
    now = datetime(2026, 10, 24, 5, 40, tzinfo=UTC)
    week_ago = (now - timedelta(days=7)).isoformat()
    yesterday = (now - timedelta(days=1)).isoformat()
    svc = _Svc(
        {
            "team_features": [{"team_id": "lab"}],
            "user_features": [{"user_id": "tester"}],
            "saved_searches": [
                {"id": "new", "team_id": "lab", "user_id": "u1", "last_run_at": None},
                {"id": "weekly", "team_id": "lab", "user_id": "u1", "last_run_at": week_ago},
                {"id": "recent", "team_id": "lab", "user_id": "u1", "last_run_at": yesterday},
                {"id": "left-lab", "team_id": "lab", "user_id": "gone", "last_run_at": None},
                {"id": "trying", "team_id": "other", "user_id": "tester", "last_run_at": None},
                {"id": "no-feature", "team_id": "other", "user_id": "u2", "last_run_at": None},
            ],
            "team_members": [
                {"team_id": "lab", "user_id": "u1"},
                {"team_id": "other", "user_id": "tester"},
                {"team_id": "other", "user_id": "u2"},
            ],
        }
    )
    assert [s["id"] for s in run.due_searches(svc, now)] == ["new", "weekly", "trying"]
