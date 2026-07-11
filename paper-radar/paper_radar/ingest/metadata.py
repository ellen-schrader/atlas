"""Best-effort paper metadata (title / authors / venue / year) from a URL.

This is deliberately lightweight and defensive: it recognises the two id schemes
that cover most of what a biology lab shares -- arXiv ids and DOIs -- and queries
their public metadata APIs (arXiv Atom feed, Crossref JSON). Anything else, or
any network failure, returns a mostly-empty record with the URL preserved so the
pipeline never blocks on this step. Richer metadata is expected to come from the
LLM enrichment stage.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from xml.etree import ElementTree

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)

_TIMEOUT = 8.0
_HEADERS = {"User-Agent": "paper-radar/0.1 (mailto:mail@ellen-schrader.de)"}


@dataclass
class PaperMetadata:
    """Best-effort metadata for a single URL."""

    url: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    source: str = "unknown"  # "arxiv" | "crossref" | "unknown"


def _get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (trusted hosts)
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _arxiv_id(url: str) -> str | None:
    m = _ARXIV_RE.search(url)
    return m.group("id") if m else None


def _doi(url: str) -> str | None:
    m = _DOI_RE.search(url)
    # Trim trailing punctuation that regularly clings to DOIs in text.
    return m.group(1).rstrip(".,);]") if m else None


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


def fetch_metadata(url: str, *, network: bool = True) -> PaperMetadata:
    """Return best-effort metadata for ``url``.

    Set ``network=False`` to skip all HTTP calls (useful in tests) -- the id
    scheme is still recognised so callers can see what *would* be fetched.
    """
    arxiv_id = _arxiv_id(url)
    doi = _doi(url)

    if not network:
        source = "arxiv" if arxiv_id else "crossref" if doi else "unknown"
        return PaperMetadata(url=url, source=source)

    if arxiv_id and (meta := _fetch_arxiv(arxiv_id, url)) is not None:
        return meta
    if doi and (meta := _fetch_crossref(doi, url)) is not None:
        return meta
    return PaperMetadata(url=url)
