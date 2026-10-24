"""Search the literature sources for what is new (issue #164).

* PubMed: E-utilities esearch on the query as typed, by Entrez date, then
  efetch for titles, authors and abstracts.
* arXiv: its query API, by submission date (the query rendered by
  :func:`query.to_arxiv`).
* bioRxiv / medRxiv: the API lists everything posted between two dates and
  cannot search, so :func:`rxiv_posted` pages through a date range for the
  daily copy in ``rxiv_feed``; matching happens locally (:func:`query.matches`).

Fixed public hosts, so plain urllib like ``trials/pubmed.py``. Each source is
paced to its published limits: NCBI 3 requests/s without a key (10 with
NCBI_API_KEY), arXiv one request every 3 s.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from xml.etree import ElementTree

from paper_radar.contact import API_USER_AGENT, CONTACT_EMAIL
from paper_radar.ingest.urls import norm_doi

MAX_HITS = 200  # per source per search per run; a weekly query that finds more is too broad

_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_ARXIV = "https://export.arxiv.org/api/query"
_RXIV = "https://api.biorxiv.org/details"
_TIMEOUT = 30
_MAX_BYTES = 20_000_000


class SourceError(Exception):
    """A source could not be searched; the message says which and why."""


@dataclass
class Hit:
    """A paper a source returned, with what the inbox shows and import needs."""

    source: str  # "pubmed" | "biorxiv" | "medrxiv" | "arxiv"
    url: str
    title: str
    doi: str | None = None
    pmid: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    published_on: str | None = None  # ISO date
    abstract: str | None = None

    @property
    def key(self) -> str:
        """One paper, however many sources and searches found it."""
        return f"doi:{self.doi}" if self.doi else f"pmid:{self.pmid}"


class _Pacer:
    """At most one request per ``interval`` seconds, across threads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
            self._next = max(now, self._next) + self.interval


_ncbi = _Pacer(0.12 if os.environ.get("NCBI_API_KEY") else 0.35)
_arxiv = _Pacer(3.0)
_rxiv = _Pacer(0.5)


def _fetch(url: str, pacer: _Pacer, what: str) -> bytes:
    pacer.wait()
    req = urllib.request.Request(url, headers={"User-Agent": API_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 — fixed https hosts
            return resp.read(_MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise SourceError(f"{what} did not answer: {exc}") from exc


def _text(el: ElementTree.Element | None) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


# --- PubMed --------------------------------------------------------------------------


def _ncbi_params(params: dict[str, str]) -> str:
    extra = {"tool": "paper-radar", "email": CONTACT_EMAIL}
    if key := os.environ.get("NCBI_API_KEY"):
        extra["api_key"] = key
    return urllib.parse.urlencode({**params, **extra})


def parse_pubmed_articles(xml: bytes) -> list[Hit]:
    """Hits from an efetch ``PubmedArticleSet``."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise SourceError(f"PubMed sent a malformed reply: {exc}") from exc
    hits = []
    for art in root.iter("PubmedArticle"):
        pmid = _text(art.find("MedlineCitation/PMID"))
        title = _text(art.find(".//ArticleTitle"))
        if not pmid or not title:
            continue
        doi = next(
            (
                _text(i)
                for i in art.iterfind(".//PubmedData/ArticleIdList/ArticleId")
                if i.get("IdType") == "doi"
            ),
            None,
        )
        authors = []
        for a in art.iterfind(".//AuthorList/Author"):
            if name := _text(a.find("CollectiveName")):
                authors.append(name)
            elif last := _text(a.find("LastName")):
                fore = _text(a.find("ForeName")) or _text(a.find("Initials"))
                authors.append(f"{fore} {last}".strip())
        parts = []
        for el in art.iterfind(".//Abstract/AbstractText"):
            if txt := _text(el):
                label = el.get("Label")
                parts.append(f"{label}: {txt}" if label else txt)
        published = None
        if (ad := art.find(".//ArticleDate")) is not None:
            y, m, d = (_text(ad.find(k)) for k in ("Year", "Month", "Day"))
            if y.isdigit() and m.isdigit() and d.isdigit():
                published = f"{y}-{int(m):02d}-{int(d):02d}"
        if published is None and (year := _text(art.find(".//JournalIssue/PubDate/Year"))):
            published = f"{year}-01-01" if year.isdigit() else None
        hits.append(
            Hit(
                source="pubmed",
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                title=title,
                doi=norm_doi(doi),
                pmid=pmid,
                authors=authors,
                venue=_text(art.find(".//Journal/Title")) or None,
                published_on=published,
                abstract=" ".join(parts) or None,
            )
        )
    return hits


def search_pubmed(query: str, since: date, until: date, limit: int = MAX_HITS) -> list[Hit]:
    """Papers PubMed added (Entrez date) between ``since`` and ``until``, inclusive."""
    raw = _fetch(
        f"{_EUTILS}/esearch.fcgi?"
        + _ncbi_params(
            {
                "db": "pubmed",
                "term": query,
                "datetype": "edat",
                "mindate": since.strftime("%Y/%m/%d"),
                "maxdate": until.strftime("%Y/%m/%d"),
                "retmax": str(limit),
                "sort": "pub_date",
                "retmode": "json",
            }
        ),
        _ncbi,
        "PubMed",
    )
    try:
        result = json.loads(raw).get("esearchresult") or {}
    except ValueError as exc:
        raise SourceError("PubMed sent a malformed reply.") from exc
    if error := result.get("ERROR"):
        raise SourceError(f"PubMed could not run the query: {error}")
    ids = [i for i in result.get("idlist") or [] if str(i).isdigit()]
    if not ids:
        return []
    xml = _fetch(
        f"{_EUTILS}/efetch.fcgi?"
        + _ncbi_params({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}),
        _ncbi,
        "PubMed",
    )
    return parse_pubmed_articles(xml)


# --- arXiv ---------------------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom", "os": "http://a9.com/-/spec/opensearch/1.1/"}


def parse_arxiv_feed(xml: bytes) -> tuple[list[Hit], int]:
    """(hits, total results) from an arXiv Atom page."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise SourceError(f"arXiv sent a malformed reply: {exc}") from exc
    total_el = root.find("os:totalResults", _ATOM)
    total = int(total_el.text) if total_el is not None and (total_el.text or "").isdigit() else 0
    hits = []
    for entry in root.iterfind("a:entry", _ATOM):
        raw_id = _text(entry.find("a:id", _ATOM)).rsplit("/abs/", 1)[-1]
        arxiv_id = raw_id.rsplit("v", 1)[0] if raw_id[-1:].isdigit() and "v" in raw_id else raw_id
        title = _text(entry.find("a:title", _ATOM))
        if not arxiv_id or not title or arxiv_id.startswith("http"):
            continue
        hits.append(
            Hit(
                source="arxiv",
                url=f"https://arxiv.org/abs/{arxiv_id}",
                title=title,
                # arXiv's own DOI, as metadata.py stores arXiv papers.
                doi=f"10.48550/arxiv.{arxiv_id.lower()}",
                authors=[
                    n
                    for a in entry.iterfind("a:author", _ATOM)
                    if (n := _text(a.find("a:name", _ATOM)))
                ],
                venue="arXiv",
                published_on=_text(entry.find("a:published", _ATOM))[:10] or None,
                abstract=_text(entry.find("a:summary", _ATOM)) or None,
            )
        )
    return hits, total


def search_arxiv(search_query: str, since: date, until: date, limit: int = MAX_HITS) -> list[Hit]:
    """Papers submitted to arXiv between ``since`` and ``until``, inclusive."""
    window = f"submittedDate:[{since:%Y%m%d}0000 TO {until:%Y%m%d}2359]"
    hits: list[Hit] = []
    start = 0
    while len(hits) < limit:
        page = min(100, limit - len(hits))
        params = urllib.parse.urlencode(
            {
                "search_query": f"({search_query}) AND {window}",
                "start": str(start),
                "max_results": str(page),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
        found, total = parse_arxiv_feed(_fetch(f"{_ARXIV}?{params}", _arxiv, "arXiv"))
        hits.extend(found)
        start += page
        if not found or start >= total:
            break
    return hits[:limit]


# --- bioRxiv / medRxiv ----------------------------------------------------------------


@dataclass
class RxivPaper:
    doi: str
    server: str  # "biorxiv" | "medrxiv"
    title: str
    abstract: str | None
    authors: list[str]
    category: str | None
    posted_on: str  # ISO date


def parse_rxiv_page(payload: bytes) -> tuple[list[RxivPaper], int, int]:
    """(first versions on the page, records on the page, total records)."""
    try:
        data = json.loads(payload)
        status = (data.get("messages") or [{}])[0]
        rows = data.get("collection") or []
    except (ValueError, AttributeError) as exc:
        raise SourceError("bioRxiv sent a malformed reply.") from exc
    total = int(status.get("total") or 0)
    papers = []
    for r in rows:
        # A revision is not new; its first version was offered when it was posted.
        if str(r.get("version")) != "1" or not r.get("doi") or not r.get("title"):
            continue
        server = str(r.get("server") or "").lower()
        if server not in ("biorxiv", "medrxiv"):
            continue
        papers.append(
            RxivPaper(
                doi=norm_doi(r["doi"]) or r["doi"],
                server=server,
                title=" ".join(str(r["title"]).split()),
                abstract=" ".join(str(r.get("abstract") or "").split()) or None,
                authors=[a.strip() for a in str(r.get("authors") or "").split(";") if a.strip()],
                category=r.get("category") or None,
                posted_on=str(r.get("date") or ""),
            )
        )
    return papers, len(rows), total


def rxiv_posted(server: str, since: date, until: date) -> Iterator[list[RxivPaper]]:
    """Every first version posted on ``server`` between two dates, a page at a time."""
    cursor = 0
    while True:
        papers, count, total = parse_rxiv_page(
            _fetch(f"{_RXIV}/{server}/{since:%Y-%m-%d}/{until:%Y-%m-%d}/{cursor}", _rxiv, server)
        )
        yield papers
        cursor += count
        if count == 0 or cursor >= total:
            return
