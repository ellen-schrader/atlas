"""Best-effort paper metadata (title / authors / venue / year) from a URL.

Resolution strategy, tried in order of reliability (identifier-based lookups
first, page scraping last):

1. **arXiv id** -> arXiv Atom API.
2. **A DOI the URL encodes** -> Crossref. Either derived from the publisher's
   article id (Nature ``10.1038/<id>``, JCI ``10.1172/JCI<id>``) or matched in
   the path (doi.org, science.org ``/doi/``, aacr ``/article/doi/``, bioRxiv and
   medRxiv ``/content/<doi>v<n>``). See :func:`_url_doi` for the order.
3. **An Elsevier PII** (Cell Press, ScienceDirect) -> Crossref's alternative-id
   index, which holds the PII alongside the DOI Elsevier deposited with it.
4. **PubMed PMID** -> NCBI E-utilities esummary.
5. **Landing-page citation tags** -> fetch the HTML with a browser-like
   User-Agent and read Highwire ``citation_*`` / Dublin Core / JSON-LD metadata
   (this is the same embedded metadata Zotero and Google Scholar rely on). If a
   DOI turns up in the page, Crossref is preferred for the authoritative record.

Steps 1-4 are what has to carry the load in production. Step 5 looks like a
general fallback and is not one: from a datacenter address the big publishers
answer a server-side fetch with a challenge, not a page (cell.com returns 403
``cf-mitigated: challenge``; biorxiv.org rate-limits), and Zotero only gets away
with it because it reads them through your logged-in browser. So a publisher
whose URL carries no identifier resolves on the *developer's* laptop and silently
resolves to nothing once deployed -- which is why the identifier cases above are
worth the special-casing, even one journal at a time.

Everything is defensive: any network failure, bot-wall (HTTP 403), or unknown
scheme returns a mostly-empty record with the URL preserved, so ingest never
blocks. Whatever summaries/tags are still missing are filled in later by the LLM
enrichment stage.
"""

from __future__ import annotations

import html
import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from paper_radar.ingest import url_guard

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
_NATURE_RE = re.compile(r"nature\.com/articles/(?P<id>[a-z0-9.\-]+)", re.IGNORECASE)
_PMID_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(?P<pmid>\d+)", re.IGNORECASE)
# bioRxiv / medRxiv: the path is the DOI followed by a *rendition* suffix --
# "v1", "v2.full", "v1.full.pdf", "v1.supplementary-material". None of that is
# part of the registered DOI and Crossref 404s on the versioned string, so the
# generic _DOI_RE below (which happily swallows it) has to be pre-empted here.
_PREPRINT_RE = re.compile(
    r"(?:bio|med)rxiv\.org/content/(?P<doi>10\.\d{4,9}/[^/?#]+)v\d+(?:\.[a-z0-9.\-]+)?(?:[/?#]|$)",
    re.IGNORECASE,
)
# JCI derives its DOI from the article number in the URL, the way Nature does:
# jci.org/articles/view/205962 -> 10.1172/JCI205962. Worth a special case
# because the landing page is the only other place that DOI appears.
_JCI_RE = re.compile(r"(?P<insight>insight\.)?jci\.org/articles/view/(?P<id>\d+)", re.IGNORECASE)
# Elsevier (Cell Press, ScienceDirect) URLs carry a PII, never a DOI. Crossref
# indexes the PII as an alternative-id, which is the only way to resolve these
# server-side: cell.com answers a non-browser with a Cloudflare challenge (403).
# The punctuated URL form "S0092-8674(25)01309-1" is the "S0092867425013091"
# Crossref holds; both spellings (and the percent-encoded one) are accepted.
_PII_RE = re.compile(
    r"(?:/pii/|/fulltext/|/abstract/|[?&]pii=)(?:PII)?"
    r"(?P<pii>S\d{4}-?\d{4}\(?\d{2}\)?\d{4,5}-?[0-9X])(?![0-9-])",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(19|20)\d{2}")

_TIMEOUT = 10.0
_API_UA = "paper-radar/0.1 (mailto:atlas@ellen-schrader.de)"
# A browser-like UA gets past the crudest bot filters when scraping landing pages.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_NCBI_PARAMS = "&tool=paper-radar&email=atlas@ellen-schrader.de"
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
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)
    # "arxiv" | "crossref" | "pubmed" | "europepmc" | "citation_meta" | "unknown"
    source: str = "unknown"


def _get(url: str, *, browser: bool = False) -> bytes | None:
    """Fetch a URL, or None on any failure.

    Every HTTP request this module makes goes through here — the identifier APIs and
    the landing-page scrape alike — so it is the one place an SSRF guard has to hold.
    `open_public_url` refuses a non-public target *and* re-checks each redirect hop,
    which a check on the submitted URL alone cannot do (urllib follows redirects
    silently, so a public URL that 302s to 169.254.169.254 would otherwise sail
    through). A blocked URL is treated as a failed fetch: ingest never blocks on a
    bad link, it just gets no metadata for it.
    """
    ua = _BROWSER_UA if browser else _API_UA
    try:
        with url_guard.open_public_url(url, headers={"User-Agent": ua}, timeout=_TIMEOUT) as resp:
            # Cap both branches: a single paper's metadata (arXiv Atom, Crossref JSON,
            # a landing page) is well under 1 MB, and now that _get follows redirects a
            # redirect to a multi-GB public stream would otherwise be read whole.
            return resp.read(_MAX_HTML_BYTES)
    except (
        url_guard.BlockedUrl,
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


def _clean_text(text: str | None) -> str | None:
    """Strip markup (JATS/HTML) and collapse whitespace in an abstract blob."""
    if not text:
        return None
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)  # drop tags (JATS <jats:p>, HTML, ...)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Some Crossref abstracts start with a literal "Abstract" heading.
    text = re.sub(r"^abstract[:\s]*", "", text, flags=re.IGNORECASE)
    return text or None


# --- identifier extraction ---------------------------------------------------


def _arxiv_id(url: str) -> str | None:
    m = _ARXIV_RE.search(url)
    return m.group("id") if m else None


def _doi(text: str, *, from_url: bool = True) -> str | None:
    """Extract a DOI from a URL or meta value.

    Publisher URLs often embed the DOI mid-path (e.g. ``/doi/10.1158/<suffix>/
    <internal-id>/<slug>``), so the raw regex over-captures. Trim at the first
    path separator / query / fragment after the suffix, keeping ``10.<reg>/<suffix>``.
    """
    m = _DOI_RE.search(text)
    if not m:
        return None
    doi = re.split(r"[?#\s]", m.group(1))[0]
    # A DOI suffix may itself contain slashes (legacy Wiley/SICI DOIs). Only trim
    # trailing path segments when parsing a publisher URL, where the extras are
    # /pdf, /full, an internal id or a slug appended after the DOI — never for a
    # bare DOI from a citation meta tag, where truncating would corrupt the DOI and
    # can merge two distinct papers onto the same key.
    if from_url:
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


def _preprint_doi(url: str) -> str | None:
    """The registered DOI behind a bioRxiv/medRxiv URL, version suffix removed."""
    m = _PREPRINT_RE.search(url)
    return m.group("doi") if m else None


def _jci_doi(url: str) -> str | None:
    """JCI article DOIs are ``10.1172/JCI<article-id>``, where the id is in the URL.

    JCI Insight is the same journal family under its own suffix:
    ``insight.jci.org/articles/view/<id>`` -> ``10.1172/jci.insight.<id>``.
    """
    m = _JCI_RE.search(url)
    if not m:
        return None
    art = m.group("id")
    return f"10.1172/jci.insight.{art}" if m.group("insight") else f"10.1172/JCI{art}"


def _elsevier_pii(url: str) -> str | None:
    """The PII a Cell Press / ScienceDirect URL carries, in the form Crossref indexes.

    Unquoted first so a percent-encoded ``?pii=S0092-8674%2825%2901309-1`` is seen
    the same as the plain one, then reduced to the unpunctuated spelling Crossref
    registers as the work's alternative-id.
    """
    m = _PII_RE.search(unquote(url))
    if not m:
        return None
    return re.sub(r"[^0-9A-Z]", "", m.group("pii").upper()) or None


def _is_doi_resolver(url: str) -> bool:
    """True for a doi.org/dx.doi.org link, where the path *is* the DOI by definition.

    Matters for step (2) of :func:`fetch_metadata`: a DOI merely pattern-matched out
    of a publisher path is a guess Crossref can refute, but a resolver URL's DOI is
    authoritative even when Crossref has never heard of it (DataCite registers
    Zenodo/figshare DOIs, and Crossref does not index those).
    """
    try:
        host = urlsplit(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return False
    return host in ("doi.org", "dx.doi.org")


def _url_doi(url: str) -> str | None:
    """The DOI a publisher URL encodes, or None.

    Most specific first: the publishers whose URL shape *derives* a DOI (Nature,
    JCI), then the preprint servers, then the generic "a DOI sits in the path"
    case. The order is the point -- the generic match would return the versioned
    bioRxiv string ``10.64898/2026.09.20.753045v1``, which Crossref 404s.
    """
    return _nature_doi(url) or _jci_doi(url) or _preprint_doi(url) or _doi(url)


def _pmid(url: str) -> str | None:
    m = _PMID_RE.search(url)
    return m.group("pmid") if m else None


# --- API fetchers ------------------------------------------------------------


def _fetch_arxiv(arxiv_id: str, url: str) -> PaperMetadata | None:
    raw = _get(f"http://export.arxiv.org/api/query?id_list={arxiv_id}")
    if raw is None:
        return None
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
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
    # The Atom feed already carries the abstract (<summary>) and subject categories.
    summary_el = entry.find("a:summary", ns)
    abstract = _clean_text(summary_el.text) if summary_el is not None else None
    keywords = [c.get("term") for c in entry.findall("a:category", ns) if c.get("term")]
    doi_el = entry.find("arxiv:doi", ns)
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None
    return PaperMetadata(
        url=url,
        title=title,
        authors=authors,
        venue="arXiv",
        year=year,
        doi=doi,
        abstract=abstract,
        keywords=keywords,
        source="arxiv",
    )


def parse_crossref(msg: dict, url: str) -> PaperMetadata:
    """Build a PaperMetadata from a Crossref ``message`` object."""
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
        doi=msg.get("DOI"),
        abstract=_clean_text(msg.get("abstract")),
        keywords=[s for s in (msg.get("subject") or []) if s],
        source="crossref",
    )


def _fetch_crossref(doi: str, url: str) -> PaperMetadata | None:
    raw = _get(f"https://api.crossref.org/works/{urllib.request.quote(doi)}")
    if raw is None:
        return None
    try:
        msg = json.loads(raw).get("message", {})
    except (json.JSONDecodeError, AttributeError):
        return None
    return parse_crossref(msg, url)


def _fetch_crossref_by_pii(pii: str, url: str) -> PaperMetadata | None:
    """Resolve an Elsevier PII through Crossref's alternative-id index.

    A filter query, not a /works/<id> lookup: the PII is not a DOI, it is a
    secondary identifier Elsevier deposits alongside one.
    """
    endpoint = (
        f"https://api.crossref.org/works?filter=alternative-id:{urllib.request.quote(pii)}&rows=1"
    )
    raw = _get(endpoint)
    if raw is None:
        return None
    try:
        items = json.loads(raw)["message"]["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return parse_crossref(items[0], url) if items else None


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
    doi = next(
        (a.get("value") for a in res.get("articleids", []) if a.get("idtype") == "doi"), None
    )
    return PaperMetadata(
        url=url, title=title, authors=authors, venue=venue, year=year, doi=doi, source="pubmed"
    )


def parse_pubmed_efetch(xml: bytes) -> tuple[str | None, list[str]]:
    """Parse a PubMed efetch XML payload into ``(abstract, keywords)``.

    Abstract sections are concatenated (some articles use labelled sections);
    keywords are the article's author keywords plus MeSH descriptor names.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None, []
    parts: list[str] = []
    for el in root.iter("AbstractText"):
        label = el.get("Label")
        txt = "".join(el.itertext()).strip()
        if txt:
            parts.append(f"{label}: {txt}" if label else txt)
    abstract = _clean_text(" ".join(parts)) if parts else None
    keywords = [k for el in root.iter("Keyword") if (k := "".join(el.itertext()).strip())]
    keywords += [d for el in root.iter("DescriptorName") if (d := "".join(el.itertext()).strip())]
    # De-dup preserving order.
    seen: set[str] = set()
    keywords = [k for k in keywords if not (k.lower() in seen or seen.add(k.lower()))]
    return abstract, keywords


def _fetch_pubmed_abstract(pmid: str) -> tuple[str | None, list[str]]:
    endpoint = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pubmed&id={pmid}&rettype=abstract&retmode=xml{_NCBI_PARAMS}"
    )
    raw = _get(endpoint)
    if raw is None:
        return None, []
    return parse_pubmed_efetch(raw)


def parse_europepmc(payload: bytes | dict, url: str) -> PaperMetadata | None:
    """Parse a Europe PMC ``/search?resultType=core`` response for one work."""
    try:
        data = json.loads(payload) if isinstance(payload, bytes) else payload
        results = data["resultList"]["result"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not results:
        return None
    r = results[0]
    authors = [
        a.get("fullName")
        for a in (r.get("authorList") or {}).get("author", [])
        if a.get("fullName")
    ]
    keywords = [k for k in (r.get("keywordList") or {}).get("keyword", []) if k]
    venue = ((r.get("journalInfo") or {}).get("journal") or {}).get("title")
    return PaperMetadata(
        url=url,
        title=r.get("title", "").strip().rstrip(".") or None,
        authors=authors,
        venue=venue,
        year=_year_from(r.get("pubYear")),
        doi=r.get("doi"),
        abstract=_clean_text(r.get("abstractText")),
        keywords=keywords,
        source="europepmc",
    )


def _fetch_europepmc(doi: str, url: str) -> PaperMetadata | None:
    query = urllib.request.quote(f'DOI:"{doi}"')
    endpoint = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={query}&resultType=core&format=json&pageSize=1"
    )
    raw = _get(endpoint)
    return parse_europepmc(raw, url) if raw is not None else None


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
    doi = _doi(doi_raw, from_url=False) if doi_raw else None
    abstract = _clean_text(
        first_of("citation_abstract", "dc.description", "og:description", "description")
    )
    keywords: list[str] = all_of("dc.subject", "prism.keyword")
    for joined in all_of("citation_keywords", "keywords", "news_keywords"):
        keywords += [k.strip() for k in re.split(r"[;,]", joined) if k.strip()]

    # JSON-LD fallback for anything still missing.
    if not title or not authors or not year or not abstract:
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
            abstract = abstract or _clean_text(obj.get("abstract") or obj.get("description"))
            if not keywords and (kw := obj.get("keywords")):
                keywords = kw if isinstance(kw, list) else re.split(r"[;,]", str(kw))

    if not title and not doi:
        return None
    return PaperMetadata(
        url=url,
        title=" ".join(title.split()) if title else None,
        authors=[_normalize_author(a) for a in authors if a],
        venue=venue,
        year=year,
        doi=doi,
        abstract=abstract,
        keywords=[k.strip() for k in keywords if k and k.strip()],
        source="citation_meta",
    )


def _scrape_landing_page(url: str) -> PaperMetadata | None:
    raw = _get(url, browser=True)
    if raw is None:
        return None
    meta = parse_citation_html(raw.decode("utf-8", "ignore"), url)
    if meta is None:
        return None
    # If the page exposed a DOI, prefer Crossref's authoritative record but keep
    # any abstract/keywords the page gave us that Crossref lacks.
    if meta.doi and (crossref := _fetch_crossref(meta.doi, url)) is not None and crossref.title:
        return _merge(crossref, meta)
    return meta


def _merge(base: PaperMetadata, extra: PaperMetadata) -> PaperMetadata:
    """Fill empty fields of ``base`` from ``extra`` (never overwrite good data)."""
    for f in ("title", "venue", "year", "doi", "abstract"):
        if not getattr(base, f) and getattr(extra, f):
            setattr(base, f, getattr(extra, f))
    if not base.authors and extra.authors:
        base.authors = extra.authors
    if not base.keywords and extra.keywords:
        base.keywords = extra.keywords
    return base


# --- public entrypoint -------------------------------------------------------


def fetch_metadata(url: str, *, network: bool = True) -> PaperMetadata:
    """Return best-effort metadata for ``url``, including abstract and keywords.

    Set ``network=False`` to skip all HTTP calls (useful in tests) -- the id
    scheme is still recognised so callers can see what *would* be fetched.
    """
    arxiv_id = _arxiv_id(url)
    url_doi = _url_doi(url)
    pii = _elsevier_pii(url)
    pmid = _pmid(url)

    if not network:
        if arxiv_id:
            source = "arxiv"
        elif url_doi or pii:
            source = "crossref"
        elif pmid:
            source = "pubmed"
        else:
            source = "unknown"
        return PaperMetadata(url=url, source=source)

    # 1) Resolve core bibliographic metadata (title/authors/venue/year/doi).
    meta: PaperMetadata | None = None
    doi_refuted = False
    if arxiv_id:
        meta = _fetch_arxiv(arxiv_id, url)
    if meta is None and url_doi:
        if (m := _fetch_crossref(url_doi, url)) and m.title:
            meta = m
        elif not _is_doi_resolver(url):
            # Crossref gave us nothing for a DOI we inferred from the path. Usually
            # that means the inference was wrong; occasionally Crossref is just
            # down. Either way we have no evidence the string is a real DOI, and
            # step (2) needs evidence before writing it to the dedup key.
            doi_refuted = True
    if meta is None and pii and (m := _fetch_crossref_by_pii(pii, url)) and m.title:
        meta = m
    if meta is None and pmid and (m := _fetch_pubmed(pmid, url)) and m.title:
        meta = m
    if meta is None:
        meta = _scrape_landing_page(url)
    if meta is None:
        meta = PaperMetadata(url=url)

    # 2) Persist a URL-derived DOI when nothing refuted it, so a later doi.org
    #    post of the same paper dedupes against this one. A DOI Crossref has never
    #    heard of is worse than no DOI at all: papers.doi IS the dedup key, so
    #    storing an unresolvable string guarantees the paper comes in twice -- and
    #    it is non-null, so a bot-walled page is filed as a titleless row instead
    #    of being skipped. (This is what put bioRxiv "...v1" strings in the table.)
    if not meta.doi and url_doi and not doi_refuted:
        meta.doi = url_doi

    # 3) Backfill the abstract (and keywords) from a dedicated source if missing.
    if not meta.abstract:
        if pmid:
            abstract, keywords = _fetch_pubmed_abstract(pmid)
            if abstract:
                meta.abstract = abstract
            if keywords and not meta.keywords:
                meta.keywords = keywords
        if not meta.abstract and meta.doi and (extra := _fetch_europepmc(meta.doi, url)):
            _merge(meta, extra)

    return meta
