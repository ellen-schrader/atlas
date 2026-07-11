"""Best-effort paper metadata (title / authors / venue / year) from a URL.

Resolution strategy, tried in order of reliability (identifier-based lookups
first, page scraping last):

1. **arXiv id** -> arXiv Atom API.
2. **Nature** article URL -> derived DOI (``10.1038/<article-id>``) -> Crossref.
3. **DOI in the URL** (doi.org, science.org ``/doi/``, aacr ``/article/doi/`` ...)
   -> Crossref.
4. **PubMed PMID** -> NCBI E-utilities esummary.
5. **Landing-page citation tags** -> fetch the HTML with a browser-like
   User-Agent and read Highwire ``citation_*`` / Dublin Core / JSON-LD metadata
   (this is the same embedded metadata Zotero and Google Scholar rely on). If a
   DOI turns up in the page, Crossref is preferred for the authoritative record.

Everything is defensive: any network failure, bot-wall (HTTP 403), or unknown
scheme returns a mostly-empty record with the URL preserved, so ingest never
blocks. Publisher pages behind a bot-wall (e.g. Elsevier's Cell / ScienceDirect)
are the expected gap -- Zotero reads those through your logged-in browser
session, which a server-side client does not have. Their summaries/tags are
filled in later by the LLM enrichment stage.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
_NATURE_RE = re.compile(r"nature\.com/articles/(?P<id>[a-z0-9.\-]+)", re.IGNORECASE)
_PMID_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(?P<pmid>\d+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"(19|20)\d{2}")

_TIMEOUT = 10.0
_API_UA = "paper-radar/0.1 (mailto:mail@ellen-schrader.de)"
# A browser-like UA gets past the crudest bot filters when scraping landing pages.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_NCBI_PARAMS = "&tool=paper-radar&email=mail@ellen-schrader.de"
_MAX_HTML_BYTES = 1_000_000


@dataclass
class PaperMetadata:
    """Best-effort metadata for a single URL."""

    url: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    # "arxiv" | "crossref" | "pubmed" | "citation_meta" | "unknown"
    source: str = "unknown"


def _get(url: str, *, browser: bool = False) -> bytes | None:
    ua = _BROWSER_UA if browser else _API_UA
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted hosts)
            return resp.read(_MAX_HTML_BYTES) if browser else resp.read()
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeError,  # truncated URLs may contain non-ASCII (e.g. an ellipsis)
        ValueError,  # malformed URL
        http.client.HTTPException,
    ):
        return None


def _year_from(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def _normalize_author(name: str) -> str:
    """Turn a scraped ``"Family, Given"`` into ``"Given Family"``; leave others."""
    name = name.strip()
    if name.count(",") == 1:
        family, given = (p.strip() for p in name.split(","))
        if family and given:
            return f"{given} {family}"
    return name


# --- identifier extraction ---------------------------------------------------


def _arxiv_id(url: str) -> str | None:
    m = _ARXIV_RE.search(url)
    return m.group("id") if m else None


def _doi(text: str) -> str | None:
    """Extract a DOI from a URL or meta value.

    Publisher URLs often embed the DOI mid-path (e.g. ``/doi/10.1158/<suffix>/
    <internal-id>/<slug>``), so the raw regex over-captures. Trim at the first
    path separator / query / fragment after the suffix, keeping ``10.<reg>/<suffix>``.
    """
    m = _DOI_RE.search(text)
    if not m:
        return None
    doi = re.split(r"[?#\s]", m.group(1))[0]
    parts = doi.split("/")
    if len(parts) > 2:
        doi = "/".join(parts[:2])
    return doi.rstrip(".,);]")


def _nature_doi(url: str) -> str | None:
    """Nature article DOIs are ``10.1038/<article-id>`` where the id is in the URL."""
    m = _NATURE_RE.search(url)
    if not m:
        return None
    art = m.group("id").split("?")[0].split("#")[0]
    art = art.removesuffix(".pdf")
    return f"10.1038/{art}" if art else None


def _pmid(url: str) -> str | None:
    m = _PMID_RE.search(url)
    return m.group("pmid") if m else None


# --- API fetchers ------------------------------------------------------------


def _fetch_arxiv(arxiv_id: str, url: str) -> PaperMetadata | None:
    raw = _get(f"http://export.arxiv.org/api/query?id_list={arxiv_id}")
    if raw is None:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom"}
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return None
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    title_el = entry.find("a:title", ns)
    title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else None
    authors = [
        n.text.strip()
        for a in entry.findall("a:author", ns)
        if (n := a.find("a:name", ns)) is not None and n.text
    ]
    published = entry.find("a:published", ns)
    year = int(published.text[:4]) if published is not None and published.text else None
    return PaperMetadata(
        url=url, title=title, authors=authors, venue="arXiv", year=year, source="arxiv"
    )


def _fetch_crossref(doi: str, url: str) -> PaperMetadata | None:
    raw = _get(f"https://api.crossref.org/works/{urllib.request.quote(doi)}")
    if raw is None:
        return None
    try:
        msg = json.loads(raw).get("message", {})
    except (json.JSONDecodeError, AttributeError):
        return None
    titles = msg.get("title") or []
    authors = [
        " ".join(p for p in (a.get("given"), a.get("family")) if p) for a in msg.get("author", [])
    ]
    venue = (msg.get("container-title") or [None])[0]
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    return PaperMetadata(
        url=url,
        title=titles[0] if titles else None,
        authors=[a for a in authors if a],
        venue=venue,
        year=year,
        source="crossref",
    )


def _fetch_pubmed(pmid: str, url: str) -> PaperMetadata | None:
    endpoint = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={pmid}&retmode=json{_NCBI_PARAMS}"
    )
    raw = _get(endpoint)
    if raw is None:
        return None
    try:
        res = json.loads(raw)["result"][pmid]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if res.get("error"):
        return None
    title = (res.get("title") or "").strip().rstrip(".") or None
    authors = [a["name"] for a in res.get("authors", []) if a.get("name")]
    venue = res.get("fulljournalname") or res.get("source") or None
    year = None
    for key in ("sortpubdate", "pubdate", "epubdate"):
        if year := _year_from(res.get(key)):
            break
    return PaperMetadata(
        url=url, title=title, authors=authors, venue=venue, year=year, source="pubmed"
    )


# --- landing-page citation-tag scraping --------------------------------------


class _MetaTagParser(HTMLParser):
    """Collect ``<meta>`` tags and JSON-LD blocks from an HTML head."""

    def __init__(self) -> None:
        super().__init__()
        self.metas: list[tuple[str, str]] = []
        self.jsonld: list[str] = []
        self._in_ldjson = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = a.get("name") or a.get("property")
            content = a.get("content")
            if key and content:
                self.metas.append((key.lower(), content))
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ldjson = True
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_ldjson:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ldjson:
            self._in_ldjson = False
            self.jsonld.append("".join(self._buf))


def _jsonld_article(blocks: list[str]) -> dict | None:
    """Return the first schema.org article-ish object found in JSON-LD blocks."""
    for block in blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            candidates = data["@graph"]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type", "")
            types = typ if isinstance(typ, list) else [typ]
            if any("Article" in str(t) for t in types):
                return obj
    return None


def parse_citation_html(html: str, url: str) -> PaperMetadata | None:
    """Parse embedded citation metadata out of a landing page's HTML.

    Prefers Highwire ``citation_*`` tags, then Dublin Core, then Open Graph, then
    schema.org JSON-LD. Returns ``None`` if nothing usable (no title and no DOI)
    is found.
    """
    parser = _MetaTagParser()
    try:
        parser.feed(html)
    except (ValueError, AssertionError):
        pass
    metas = parser.metas

    def all_of(*keys: str) -> list[str]:
        wanted = {k.lower() for k in keys}
        return [c for (k, c) in metas if k in wanted]

    def first_of(*keys: str) -> str | None:
        vals = all_of(*keys)
        return vals[0] if vals else None

    title = first_of("citation_title", "dc.title", "og:title", "twitter:title")
    authors = all_of("citation_author", "dc.creator")
    if not authors and (joined := first_of("citation_authors")):
        authors = re.split(r"\s*;\s*", joined)
    venue = first_of(
        "citation_journal_title", "citation_conference_title", "prism.publicationname", "dc.source"
    )
    year = _year_from(
        first_of(
            "citation_publication_date",
            "citation_date",
            "citation_online_date",
            "prism.publicationdate",
            "dc.date",
        )
    )
    doi_raw = first_of("citation_doi", "dc.identifier", "prism.doi")
    doi = _doi(doi_raw) if doi_raw else None

    # JSON-LD fallback for anything still missing.
    if not title or not authors or not year:
        obj = _jsonld_article(parser.jsonld)
        if obj:
            title = title or obj.get("headline") or obj.get("name")
            if not authors:
                au = obj.get("author")
                au_list = au if isinstance(au, list) else [au] if au else []
                authors = [a.get("name") if isinstance(a, dict) else str(a) for a in au_list if a]
            year = year or _year_from(obj.get("datePublished") or obj.get("dateCreated"))
            if not venue:
                part = obj.get("isPartOf")
                if isinstance(part, dict):
                    venue = part.get("name")

    if not title and not doi:
        return None
    return PaperMetadata(
        url=url,
        title=" ".join(title.split()) if title else None,
        authors=[_normalize_author(a) for a in authors if a],
        venue=venue,
        year=year,
        doi=doi,
        source="citation_meta",
    )


def _scrape_landing_page(url: str) -> PaperMetadata | None:
    raw = _get(url, browser=True)
    if raw is None:
        return None
    meta = parse_citation_html(raw.decode("utf-8", "ignore"), url)
    if meta is None:
        return None
    # If the page exposed a DOI, prefer Crossref's authoritative record.
    if meta.doi and (crossref := _fetch_crossref(meta.doi, url)) is not None and crossref.title:
        return crossref
    return meta


# --- public entrypoint -------------------------------------------------------


def fetch_metadata(url: str, *, network: bool = True) -> PaperMetadata:
    """Return best-effort metadata for ``url``.

    Set ``network=False`` to skip all HTTP calls (useful in tests) -- the id
    scheme is still recognised so callers can see what *would* be fetched.
    """
    arxiv_id = _arxiv_id(url)
    nature_doi = _nature_doi(url)
    doi = _doi(url)
    pmid = _pmid(url)

    if not network:
        if arxiv_id:
            source = "arxiv"
        elif nature_doi or doi:
            source = "crossref"
        elif pmid:
            source = "pubmed"
        else:
            source = "unknown"
        return PaperMetadata(url=url, source=source)

    if arxiv_id and (meta := _fetch_arxiv(arxiv_id, url)) is not None:
        return meta
    if nature_doi and (meta := _fetch_crossref(nature_doi, url)) is not None and meta.title:
        return meta
    if doi and (meta := _fetch_crossref(doi, url)) is not None and meta.title:
        return meta
    if pmid and (meta := _fetch_pubmed(pmid, url)) is not None and meta.title:
        return meta
    if (meta := _scrape_landing_page(url)) is not None:
        return meta
    return PaperMetadata(url=url)
