"""Offline tests for URL metadata resolution (no network calls)."""

from __future__ import annotations

import json

from paper_radar.ingest import metadata as metadata_module
from paper_radar.ingest.metadata import (
    _clean_text,
    _doi,
    _elsevier_pii,
    _jci_doi,
    _nature_doi,
    _pmid,
    _preprint_doi,
    _url_doi,
    fetch_metadata,
    parse_citation_html,
    parse_crossref,
    parse_europepmc,
    parse_pubmed_efetch,
)


def test_clean_text_strips_jats_and_whitespace():
    out = _clean_text("<jats:p>Abstract: We  show\n\ncool &amp; new results.</jats:p>")
    assert out == "We show cool & new results."


def test_parse_crossref_extracts_abstract_doi_keywords():
    msg = {
        "title": ["A spatial atlas of breast tissue"],
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "container-title": ["Nature"],
        "issued": {"date-parts": [[2023, 5]]},
        "DOI": "10.1038/s41586-023-06124-2",
        "abstract": "<jats:p>We map the breast microenvironment.</jats:p>",
        "subject": ["Oncology", "Genomics"],
    }
    m = parse_crossref(msg, "https://x")
    assert m.title == "A spatial atlas of breast tissue"
    assert m.doi == "10.1038/s41586-023-06124-2"
    assert m.abstract == "We map the breast microenvironment."
    assert m.keywords == ["Oncology", "Genomics"]
    assert m.year == 2023


def test_parse_pubmed_efetch():
    xml = b"""<PubmedArticleSet><PubmedArticle><MedlineCitation>
      <Article><Abstract>
        <AbstractText Label="BACKGROUND">Tumors are complex.</AbstractText>
        <AbstractText Label="RESULTS">We found niches.</AbstractText>
      </Abstract>
      <KeywordList><Keyword>spatial transcriptomics</Keyword></KeywordList>
      </Article>
      <MeshHeadingList><MeshHeading><DescriptorName>Breast Neoplasms</DescriptorName>
      </MeshHeading></MeshHeadingList>
    </MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    abstract, keywords = parse_pubmed_efetch(xml)
    assert abstract == "BACKGROUND: Tumors are complex. RESULTS: We found niches."
    assert "spatial transcriptomics" in keywords
    assert "Breast Neoplasms" in keywords


def test_parse_europepmc():
    payload = {
        "resultList": {
            "result": [
                {
                    "title": "Fibroblast niches.",
                    "authorList": {"author": [{"fullName": "Haddad N"}]},
                    "journalInfo": {"journal": {"title": "bioRxiv"}},
                    "pubYear": "2024",
                    "doi": "10.1101/2024.02.10.579743",
                    "abstractText": "CAF niches modulate response.",
                    "keywordList": {"keyword": ["fibroblasts", "breast"]},
                }
            ]
        }
    }
    m = parse_europepmc(payload, "https://x")
    assert m is not None
    assert m.abstract == "CAF niches modulate response."
    assert m.keywords == ["fibroblasts", "breast"]
    assert m.venue == "bioRxiv"
    assert m.year == 2024


def test_doi_trims_trailing_url_path():
    # DOI embedded mid-path (aacr, oup, science) must not swallow the trailing slug.
    assert (
        _doi("https://aacrjournals.org/cd/article/doi/10.1158/2159-8290.CD-25-1459/781787/HER2-x")
        == "10.1158/2159-8290.CD-25-1459"
    )
    # A clean 2-part DOI is unchanged.
    assert _doi("https://doi.org/10.1126/science.adz9353") == "10.1126/science.adz9353"
    assert _doi("no doi here") is None


def test_doi_from_meta_keeps_slashes_in_suffix():
    # A bare DOI from a citation_doi meta tag (not a URL) may legitimately contain
    # slashes in its suffix; from_url=False must not truncate it (which would merge
    # two distinct DOIs onto the same key). The URL default still trims path segments.
    doi = "10.1234/abc/def"
    assert _doi(doi, from_url=False) == "10.1234/abc/def"
    assert _doi(doi, from_url=True) == "10.1234/abc"


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


def test_preprint_url_to_doi_strips_the_version_suffix():
    # A bioRxiv path is the DOI plus a rendition suffix, and Crossref 404s on the
    # versioned string -- which used to send every preprint down the landing-page
    # scrape and store "...v1" in papers.doi as the dedup key.
    base = "https://www.biorxiv.org/content/10.64898/2026.09.20.753045"
    real = "10.64898/2026.09.20.753045"
    assert _preprint_doi(base + "v1") == real
    assert _preprint_doi(base + "v2.full") == real
    assert _preprint_doi(base + "v1.full.pdf") == real
    assert _preprint_doi(base + "v1.supplementary-material") == real
    assert _preprint_doi(base + "v1?utm_source=x") == real
    # medRxiv is the same server, and the pre-2019 non-dated suffix still works.
    assert _preprint_doi("https://www.medrxiv.org/content/10.1101/2026.01.02.25320000v1") == (
        "10.1101/2026.01.02.25320000"
    )
    assert _preprint_doi("https://www.biorxiv.org/content/10.1101/070805v1") == "10.1101/070805"
    # Not a preprint host: leave it to the generic matcher.
    assert _preprint_doi("https://doi.org/10.1126/science.adz9353") is None


def test_jci_url_to_doi():
    assert _jci_doi("https://www.jci.org/articles/view/205962") == "10.1172/JCI205962"
    # JCI Insight is the same family under its own suffix.
    assert _jci_doi("https://insight.jci.org/articles/view/191234") == (
        "10.1172/jci.insight.191234"
    )
    assert _jci_doi("https://www.nature.com/articles/x") is None


def test_elsevier_pii_extraction():
    # Cell Press writes the PII punctuated; Crossref indexes it unpunctuated.
    pii = "S0092867425013091"
    assert _elsevier_pii("https://www.cell.com/cell/fulltext/S0092-8674(25)01309-1") == pii
    assert _elsevier_pii("https://www.cell.com/cell/abstract/S0092-8674(25)01309-1") == pii
    assert _elsevier_pii("https://www.cell.com/cell/fulltext/PIIS0092867425013091") == pii
    assert _elsevier_pii("https://www.sciencedirect.com/science/article/pii/" + pii) == pii
    assert _elsevier_pii("https://www.sciencedirect.com/science/article/abs/pii/" + pii) == pii
    # The showPdf form percent-encodes the brackets.
    assert _elsevier_pii("https://www.cell.com/action/showPdf?pii=S0092-8674%2825%2901309-1") == pii
    assert _elsevier_pii("https://www.nature.com/articles/s41586-023-06124-2") is None


def test_url_doi_prefers_the_specific_publisher_rules():
    # Order matters: the generic path matcher would return the versioned bioRxiv
    # string, and would find no DOI at all in a JCI or Nature URL.
    assert _url_doi("https://www.biorxiv.org/content/10.64898/2026.09.20.753045v1") == (
        "10.64898/2026.09.20.753045"
    )
    assert _url_doi("https://www.jci.org/articles/view/205962") == "10.1172/JCI205962"
    assert _url_doi("https://www.nature.com/articles/s41586-023-06124-2") == (
        "10.1038/s41586-023-06124-2"
    )
    # Anything without a publisher rule still falls through to the generic match.
    assert _url_doi("https://doi.org/10.1126/science.adz9353") == "10.1126/science.adz9353"
    assert _url_doi("https://example.org/thing") is None


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
    # The publishers whose URL carries an identifier are resolvable without the
    # landing page, which is the whole point -- they are unfetchable from a server.
    assert (
        fetch_metadata(
            "https://www.biorxiv.org/content/10.64898/2026.09.20.753045v1", network=False
        ).source
        == "crossref"
    )
    assert fetch_metadata("https://www.jci.org/articles/view/205962", network=False).source == (
        "crossref"
    )
    assert (
        fetch_metadata(
            "https://www.cell.com/cell/fulltext/S0092-8674(25)01309-1", network=False
        ).source
        == "crossref"
    )


def test_unresolvable_url_doi_is_not_persisted(monkeypatch):
    # papers.doi IS the dedup key, so a DOI-shaped string Crossref has never heard
    # of is worse than none: it can never match a later post of the same paper, and
    # being non-null it files a bot-walled page as a titleless row instead of a skip.
    monkeypatch.setattr(metadata_module, "_get", lambda url, browser=False: None)
    meta = fetch_metadata("https://www.science.org/doi/10.1126/science.notreal")
    assert meta.doi is None
    assert meta.title is None


def test_cell_url_resolves_from_the_pii_without_the_landing_page(monkeypatch):
    """cell.com answers a server with a Cloudflare challenge, so the PII is the
    only way in: Crossref holds it as the work's alternative-id."""
    payload = {
        "message": {
            "items": [
                {
                    "title": ["Renal PIEZO2 is an essential regulator of renin"],
                    "DOI": "10.1016/j.cell.2025.11.013",
                    "container-title": ["Cell"],
                    "issued": {"date-parts": [[2025, 11]]},
                }
            ]
        }
    }

    asked: list[str] = []

    def fake_get(url, browser=False):
        # The landing page is unreachable, exactly as in production.
        if browser:
            return None
        asked.append(url)
        if "filter=alternative-id:" in url:
            return json.dumps(payload).encode()
        return None  # the abstract backfill finds nothing; that's not this test

    monkeypatch.setattr(metadata_module, "_get", fake_get)
    meta = fetch_metadata("https://www.cell.com/cell/fulltext/S0092-8674(25)01309-1")
    assert any("filter=alternative-id:S0092867425013091" in u for u in asked)
    assert meta.title == "Renal PIEZO2 is an essential regulator of renin"
    assert meta.doi == "10.1016/j.cell.2025.11.013"
    assert meta.venue == "Cell"
    assert meta.source == "crossref"


def test_pii_lookup_tolerates_an_empty_crossref_result(monkeypatch):
    # An unknown PII returns items: [] -- not an error, just nothing to use.
    monkeypatch.setattr(
        metadata_module,
        "_get",
        lambda url, browser=False: json.dumps({"message": {"items": []}}).encode(),
    )
    meta = fetch_metadata("https://www.sciencedirect.com/science/article/pii/S0092867425013091")
    assert meta.title is None


def test_doi_resolver_url_keeps_its_doi_when_crossref_has_nothing(monkeypatch):
    # On a doi.org link the path IS the DOI, so Crossref drawing a blank proves
    # nothing -- DataCite registers Zenodo/figshare DOIs and Crossref never sees them.
    monkeypatch.setattr(metadata_module, "_get", lambda url, browser=False: None)
    assert fetch_metadata("https://doi.org/10.5281/zenodo.1234567").doi == "10.5281/zenodo.1234567"


HIGHWIRE_HTML = """
<html><head>
<meta name="citation_title" content="Spatial architecture of the breast tumor microenvironment">
<meta name="citation_author" content="Schrader, Ellen">
<meta name="citation_author" content="Khan, Atif">
<meta name="citation_journal_title" content="Nature Methods">
<meta name="citation_publication_date" content="2026/03/11">
<meta name="citation_doi" content="10.1038/s41592-026-00000-0">
<meta name="citation_keywords" content="spatial biology; breast cancer, imaging">
<meta name="description" content="We profile the tumor microenvironment at single-cell resolution.">
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
    assert meta.keywords == ["spatial biology", "breast cancer", "imaging"]
    assert meta.abstract == "We profile the tumor microenvironment at single-cell resolution."


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
