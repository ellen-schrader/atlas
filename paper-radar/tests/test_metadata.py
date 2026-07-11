"""Offline tests for URL metadata resolution (no network calls)."""

from __future__ import annotations

from paper_radar.ingest.metadata import (
    _doi,
    _nature_doi,
    _pmid,
    fetch_metadata,
    parse_citation_html,
)


def test_doi_trims_trailing_url_path():
    # DOI embedded mid-path (aacr, oup, science) must not swallow the trailing slug.
    assert (
        _doi("https://aacrjournals.org/cd/article/doi/10.1158/2159-8290.CD-25-1459/781787/HER2-x")
        == "10.1158/2159-8290.CD-25-1459"
    )
    # A clean 2-part DOI is unchanged.
    assert _doi("https://doi.org/10.1126/science.adz9353") == "10.1126/science.adz9353"
    assert _doi("no doi here") is None


def test_nature_url_to_doi():
    assert _nature_doi("https://www.nature.com/articles/s41586-023-06124-2") == (
        "10.1038/s41586-023-06124-2"
    )
    # news articles (d-prefixed) and .pdf suffixes still resolve.
    assert _nature_doi("https://www.nature.com/articles/d41586-026-02057-8?utm_source=x") == (
        "10.1038/d41586-026-02057-8"
    )
    assert _nature_doi("https://www.nature.com/articles/s41592-025-02926-6.pdf") == (
        "10.1038/s41592-025-02926-6"
    )
    assert _nature_doi("https://www.cell.com/whatever") is None


def test_pmid_extraction():
    assert _pmid("https://pubmed.ncbi.nlm.nih.gov/41401806/") == "41401806"
    assert _pmid("https://www.nature.com/articles/x") is None


def test_fetch_metadata_offline_source_detection():
    # network=False recognises the scheme without any HTTP.
    assert fetch_metadata("https://arxiv.org/abs/2306.11207", network=False).source == "arxiv"
    assert (
        fetch_metadata("https://www.nature.com/articles/s41586-023-06124-2", network=False).source
        == "crossref"
    )
    assert (
        fetch_metadata("https://pubmed.ncbi.nlm.nih.gov/41401806/", network=False).source
        == "pubmed"
    )
    assert fetch_metadata("https://example.org/thing", network=False).source == "unknown"


HIGHWIRE_HTML = """
<html><head>
<meta name="citation_title" content="Spatial architecture of the breast tumor microenvironment">
<meta name="citation_author" content="Schrader, Ellen">
<meta name="citation_author" content="Khan, Atif">
<meta name="citation_journal_title" content="Nature Methods">
<meta name="citation_publication_date" content="2026/03/11">
<meta name="citation_doi" content="10.1038/s41592-026-00000-0">
</head><body>...</body></html>
"""


def test_parse_highwire_tags():
    meta = parse_citation_html(HIGHWIRE_HTML, "https://example.org/paper")
    assert meta is not None
    assert meta.title == "Spatial architecture of the breast tumor microenvironment"
    # "Family, Given" is normalised to "Given Family".
    assert meta.authors == ["Ellen Schrader", "Atif Khan"]
    assert meta.venue == "Nature Methods"
    assert meta.year == 2026
    assert meta.doi == "10.1038/s41592-026-00000-0"


JSONLD_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": "ScholarlyArticle",
 "headline": "Fibroblast niches shape drug response",
 "author": [{"name": "N. Haddad"}, {"name": "E. Moreau"}],
 "datePublished": "2024-02-10",
 "isPartOf": {"name": "bioRxiv"}}
</script>
</head><body></body></html>
"""


def test_parse_jsonld_fallback():
    meta = parse_citation_html(JSONLD_HTML, "https://example.org/x")
    assert meta is not None
    assert meta.title == "Fibroblast niches shape drug response"
    assert meta.authors == ["N. Haddad", "E. Moreau"]
    assert meta.year == 2024
    assert meta.venue == "bioRxiv"


def test_parse_returns_none_when_empty():
    assert parse_citation_html("<html><head></head><body>hi</body></html>", "u") is None
