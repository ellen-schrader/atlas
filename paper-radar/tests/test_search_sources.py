"""Source replies parsed into hits (no network)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from paper_radar.search import sources

PUBMED_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">42910499</PMID>
      <Article>
        <Journal><Title>FASEB journal</Title>
          <JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
        <ArticleTitle>Architectural <i>regulation</i> of T cells.</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">HCC develops.</AbstractText>
          <AbstractText>TLS matter.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Abdullah</LastName><ForeName>Mutaman</ForeName></Author>
          <Author><LastName>Zulkifle</LastName><Initials>N</Initials></Author>
          <Author><CollectiveName>TLS Consortium</CollectiveName></Author>
        </AuthorList>
        <ArticleDate DateType="Electronic">
          <Year>2026</Year><Month>10</Month><Day>3</Day>
        </ArticleDate>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="pubmed">42910499</ArticleId>
      <ArticleId IdType="doi">10.1096/FJ.202603114R</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>1</PMID><Article><ArticleTitle>No DOI</ArticleTitle></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_pubmed_articles():
    first, second = sources.parse_pubmed_articles(PUBMED_XML)
    assert first.pmid == "42910499" and first.doi == "10.1096/fj.202603114r"
    assert first.title == "Architectural regulation of T cells."
    assert first.authors == ["Mutaman Abdullah", "N Zulkifle", "TLS Consortium"]
    assert first.abstract == "BACKGROUND: HCC develops. TLS matter."
    assert first.published_on == "2026-10-03" and first.venue == "FASEB journal"
    assert first.url == "https://pubmed.ncbi.nlm.nih.gov/42910499/"
    assert first.key == "doi:10.1096/fj.202603114r"
    # Without a DOI the PMID is the key.
    assert second.doi is None and second.key == "pmid:1"


def test_pubmed_malformed_reply():
    with pytest.raises(sources.SourceError):
        sources.parse_pubmed_articles(b"<oops")


def test_pubmed_query_error_is_reported(monkeypatch):
    reply = json.dumps({"esearchresult": {"ERROR": "Invalid query"}}).encode()
    monkeypatch.setattr(sources, "_fetch", lambda url, pacer, what: reply)
    with pytest.raises(sources.SourceError, match="Invalid query"):
        sources.search_pubmed("((", date(2026, 10, 1), date(2026, 10, 8))


ARXIV_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2609.05182v2</id>
    <published>2026-09-04T14:17:03Z</published>
    <title>Conserved Immune
      Topology</title>
    <summary>  Pathology foundation models.  </summary>
    <author><name>Ada Lovelace</name></author>
  </entry>
</feed>"""


def test_arxiv_feed():
    (hit,), total = sources.parse_arxiv_feed(ARXIV_XML)
    assert total == 1
    assert hit.url == "https://arxiv.org/abs/2609.05182"  # version dropped
    assert hit.doi == "10.48550/arxiv.2609.05182"  # as metadata.py stores arXiv papers
    assert (
        hit.title == "Conserved Immune Topology" and hit.abstract == "Pathology foundation models."
    )
    assert hit.authors == ["Ada Lovelace"] and hit.published_on == "2026-09-04"


def test_rxiv_page_keeps_first_versions_only():
    page = json.dumps(
        {
            "messages": [{"status": "ok", "total": "40", "count": 3}],
            "collection": [
                {
                    "doi": "10.64898/2026.10.14.759109",
                    "title": "Localization  accuracy",
                    "authors": "Chapman, K. B.; Hell, S. W.",
                    "date": "2026-10-16",
                    "version": "1",
                    "category": "biophysics",
                    "abstract": "The two methods.",
                    "server": "bioRxiv",
                },
                {"doi": "10.1101/x", "title": "Revised", "version": "2", "server": "bioRxiv"},
                {"doi": "10.1101/y", "title": "Elsewhere", "version": "1", "server": "Other"},
            ],
        }
    ).encode()
    papers, count, total = sources.parse_rxiv_page(page)
    assert (count, total) == (3, 40)
    (p,) = papers
    assert p.server == "biorxiv" and p.title == "Localization accuracy"
    assert p.authors == ["Chapman, K. B.", "Hell, S. W."] and p.posted_on == "2026-10-16"


def test_rxiv_pages_until_the_total(monkeypatch):
    seen: list[str] = []

    def fetch(url, pacer, what):
        seen.append(url.rsplit("/", 1)[-1])
        n = 2 if len(seen) < 3 else 1
        rows = [
            {
                "doi": f"10.1101/{len(seen)}.{i}",
                "title": "t",
                "version": "1",
                "server": "medRxiv",
                "date": "2026-10-20",
            }
            for i in range(n)
        ]
        return json.dumps({"messages": [{"total": "5"}], "collection": rows}).encode()

    monkeypatch.setattr(sources, "_fetch", fetch)
    pages = list(sources.rxiv_posted("medrxiv", date(2026, 10, 17), date(2026, 10, 24)))
    assert seen == ["0", "2", "4"] and sum(len(p) for p in pages) == 5
