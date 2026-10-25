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
    # Three days of overlap: arXiv announces Thursday's submissions on Sunday.
    assert ss.window("2026-10-17T05:40:00+00:00", TODAY) == (date(2026, 10, 14), TODAY)
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


class _Updates:
    """Records saved_searches updates; everything else is empty."""

    def __init__(self):
        self.updates: list[dict] = []

    def table(self, name):
        outer = self

        class Q(_Query):
            def update(self, changes):
                outer.updates.append(changes)
                return self

        return Q([])


@pytest.mark.parametrize(
    ("failed_before", "error", "failed_after", "advances"),
    [
        (0, False, 0, True),  # ran: wait a week
        (0, True, 1, False),  # failed: due again tomorrow, over the same dates
        (1, True, 2, False),
        (2, True, 3, True),  # still failing: back to weekly, error kept
        (2, False, 0, True),
    ],
)
def test_failing_searches_retry_daily_then_weekly(
    monkeypatch, failed_before, error, failed_after, advances
):
    def pubmed(*a, **k):
        if error:
            raise SourceError("PubMed could not run the query: bad tag")
        return []

    monkeypatch.setattr(sources, "search_pubmed", pubmed)
    svc = _Updates()
    search = {
        "id": "s",
        "user_id": "u",
        "team_id": "t",
        "query": "tls",
        "sources": ["pubmed"],
        "last_run_at": None,
        "failed_runs": failed_before,
    }
    ss.run_saved_search(svc, search, TODAY, feed=None)
    (changes,) = svc.updates
    assert changes["failed_runs"] == failed_after
    assert ("last_run_at" in changes) is advances
    assert (changes["last_error"] is not None) is error


CANDIDATE = {
    "source": "pubmed",
    "url": "https://pubmed.ncbi.nlm.nih.gov/1/",
    "title": "From PubMed",
    "doi": "10.1/x",
    "pmid": "1",
    "authors": ["A B"],
    "venue": "J",
    "published_on": "2026-10-20",
    "abstract": "Source abstract.",
}


def test_import_falls_back_to_the_source_record_when_the_lookup_fails(monkeypatch):
    def boom(url):
        raise TimeoutError("publisher timed out")

    monkeypatch.setattr(ss, "fetch_metadata", boom)
    meta = ss._import_meta(CANDIDATE)
    assert (meta.title, meta.doi, meta.year) == ("From PubMed", "10.1/x", 2026)


def test_import_keeps_the_source_doi_and_abstract_when_the_lookup_lacks_them(monkeypatch):
    from paper_radar.ingest.metadata import PaperMetadata

    monkeypatch.setattr(
        ss, "fetch_metadata", lambda url: PaperMetadata(url=url, title="Full record", venue="Cell")
    )
    meta = ss._import_meta(CANDIDATE)
    assert (meta.title, meta.venue) == ("Full record", "Cell")
    assert meta.doi == "10.1/x" and meta.abstract == "Source abstract."


def test_the_feed_is_copied_daily_even_when_no_search_is_due(monkeypatch):
    copied: list[date] = []
    monkeypatch.setattr(run, "service_client", lambda: None)
    monkeypatch.setattr(run, "_feature_owners", lambda svc: ({"lab"}, set()))
    monkeypatch.setattr(run, "refresh_feed", lambda svc, today, dry_run: copied.append(today) or 0)
    monkeypatch.setattr(ss, "retry_stuck_imports", lambda svc, now: 0)
    monkeypatch.setattr(run, "due_searches", lambda svc, now: [])
    assert run.run() == (0, 0, 0)
    assert len(copied) == 1


def test_nothing_runs_without_the_feature(monkeypatch):
    monkeypatch.setattr(run, "service_client", lambda: None)
    monkeypatch.setattr(run, "_feature_owners", lambda svc: (set(), set()))
    monkeypatch.setattr(run, "refresh_feed", lambda *a, **k: pytest.fail("no copying"))
    assert run.run() == (0, 0, 0)


def test_sources_are_checked_and_named_by_key():
    assert ss.checked_sources(["arxiv", "PubMed", "pubmed"]) == ["pubmed", "arxiv"]
    assert ss.checked_sources(["medrxiv"]) == ["biorxiv"]  # one feed holds both
    with pytest.raises(ss.Refused, match="Unknown source 'europepmc'.*pubmed, biorxiv"):
        ss.checked_sources(["pubmed", "europepmc"])
    with pytest.raises(ss.Refused, match="Pick any of"):
        ss.checked_sources([])


def test_names_go_on_one_line():
    assert ss.checked_name("  TLS\n- fake: line ") == "TLS - fake: line"
    with pytest.raises(ss.Refused):
        ss.checked_name(" \n ")
    with pytest.raises(ss.Refused):
        ss.checked_name("x" * 121)


def test_arxiv_subjects_narrow_the_query():
    node = q.without_filters(q.parse('"flow matching" AND protein'))
    plain = q.to_arxiv(node)
    assert ss.arxiv_query(node, []) == plain
    # An archive takes in all its subcategories; a subcategory is itself.
    assert ss.arxiv_query(node, ["q-bio", "cs.LG"]) == f"{plain} AND (cat:q-bio* OR cat:cs.LG)"


def test_arxiv_subject_codes_are_checked():
    assert ss.checked_categories([" q-bio.* ", "q-bio", "cs.LG", "q-bio*"]) == ["q-bio", "cs.LG"]
    assert ss.checked_categories([]) == []
    for bad in ("cs.LG OR ti:x", "q bio", "", "cat:q-bio"):
        with pytest.raises(ss.Refused, match="arXiv subject code"):
            ss.checked_categories([bad])
    with pytest.raises(ss.Refused, match="at most"):
        ss.checked_categories([f"cs.A{chr(97 + i)}" for i in range(21)])
