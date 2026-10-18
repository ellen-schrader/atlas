"""Offline tests for the abstract lookup and the daily abstract backfill (#136)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from api.backfill_abstracts import is_due, plan_patch
from paper_radar.ingest import metadata as metadata_module
from paper_radar.ingest.metadata import PaperMetadata, find_abstract, parse_pubmed_esearch

NOW = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)


def _row(age_days: float, checked_days_ago: float | None, **kw) -> dict:
    checked = None if checked_days_ago is None else NOW - timedelta(days=checked_days_ago)
    return {
        "id": "p1",
        "created_at": (NOW - timedelta(days=age_days)).isoformat(),
        "abstract_checked_at": checked.isoformat() if checked else None,
        **kw,
    }


# --- the retry schedule -------------------------------------------------------


def test_never_checked_is_always_due():
    # Including old papers: the first run clears the backlog once.
    for age in (0, 10, 60, 2000):
        assert is_due(_row(age, None), NOW), age


def test_first_month_is_daily():
    assert is_due(_row(5, 1), NOW)
    # A run a few minutes earlier than yesterday's still counts.
    assert is_due(_row(5, 0.9), NOW)
    assert not is_due(_row(5, 0.5), NOW)


def test_second_and_third_month_are_weekly():
    assert not is_due(_row(45, 1), NOW)
    assert not is_due(_row(45, 5), NOW)
    assert is_due(_row(45, 7), NOW)


def test_after_three_months_a_checked_paper_is_left_alone():
    # News pieces and editorials never have an abstract; stop asking about them.
    assert not is_due(_row(120, 30), NOW)
    assert not is_due(_row(2000, 365), NOW)


# --- what gets written --------------------------------------------------------


def test_found_abstract_is_written_and_queues_reembed_and_retag():
    found = PaperMetadata(url="u", abstract="We show X.", keywords=["x"], source="pubmed")
    patch = plan_patch({"id": "p1", "keywords": []}, found)
    assert patch["abstract"] == "We show X."
    assert patch["keywords"] == ["x"]
    assert patch["embedded_at"] is None and patch["enriched_at"] is None
    assert patch["abstract_checked_at"]
    # Nothing else on the row is touched, even if the source knows other fields.
    written = {"abstract", "keywords", "embedded_at", "enriched_at", "abstract_checked_at"}
    assert set(patch) == written


def test_existing_keywords_are_kept():
    found = PaperMetadata(url="u", abstract="We show X.", keywords=["x"], source="pubmed")
    patch = plan_patch({"id": "p1", "keywords": ["mine"]}, found)
    assert "keywords" not in patch


def test_nothing_found_only_stamps_the_check():
    assert set(plan_patch({"id": "p1"}, None)) == {"abstract_checked_at"}


def test_hand_edited_abstract_is_never_replaced():
    found = PaperMetadata(url="u", abstract="We show X.", source="europepmc")
    patch = plan_patch({"id": "p1", "edited_fields": ["abstract"]}, found)
    assert set(patch) == {"abstract_checked_at"}


# --- the lookup -----------------------------------------------------------------


def _epmc(abstract: str | None) -> bytes:
    result = {"title": "A paper", "doi": "10.1038/x"}
    if abstract:
        result["abstractText"] = abstract
    return json.dumps({"resultList": {"result": [result]}}).encode()


_EFETCH = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><Article><Abstract>
<AbstractText>From PubMed.</AbstractText></Abstract></Article></MedlineCitation>
</PubmedArticle></PubmedArticleSet>"""


def _esearch(*ids: str) -> bytes:
    return json.dumps({"esearchresult": {"idlist": list(ids)}}).encode()


def _stub(monkeypatch, routes: dict[str, bytes | None]) -> list[str]:
    """Answer _get by URL substring; returns the URLs asked for."""
    asked: list[str] = []

    def fake_get(url, browser=False):
        asked.append(url)
        return next((body for key, body in routes.items() if key in url), None)

    monkeypatch.setattr(metadata_module, "_get", fake_get)
    return asked


def test_europe_pmc_answers_first(monkeypatch):
    asked = _stub(monkeypatch, {"europepmc": _epmc("From Europe PMC.")})
    found = find_abstract("10.1038/x", "https://www.nature.com/articles/x")
    assert found.abstract == "From Europe PMC." and found.source == "europepmc"
    assert not any("eutils" in u for u in asked)


def test_pubmed_by_doi_fills_what_europe_pmc_lacks(monkeypatch):
    _stub(
        monkeypatch,
        {"europepmc": _epmc(None), "esearch": _esearch("123"), "efetch": _EFETCH},
    )
    found = find_abstract("10.1038/x", "https://www.nature.com/articles/x")
    assert found.abstract == "From PubMed." and found.source == "pubmed"


def test_ambiguous_pubmed_match_is_no_match():
    assert parse_pubmed_esearch(_esearch("1", "2")) is None
    assert parse_pubmed_esearch(_esearch()) is None
    assert parse_pubmed_esearch(b"not json") is None
    assert parse_pubmed_esearch(_esearch("42")) == "42"


def _page(description: str) -> bytes:
    return (
        '<html><head><meta name="citation_title" content="A paper">'
        f'<meta name="citation_abstract" content="{description}"></head></html>'
    ).encode()


def test_page_is_scraped_only_when_asked_and_only_for_a_real_abstract(monkeypatch):
    long_abstract = "We show a thing. " * 20
    asked = _stub(monkeypatch, {"example.org": _page(long_abstract)})
    assert find_abstract(None, "https://example.org/paper") is None
    assert not asked  # no DOI, no scrape: nothing to ask
    found = find_abstract(None, "https://example.org/paper", scrape=True)
    assert found and found.abstract.startswith("We show a thing.")

    # A one-line teaser is not an abstract.
    _stub(monkeypatch, {"example.org": _page("A short teaser.")})
    assert find_abstract(None, "https://example.org/paper", scrape=True) is None
