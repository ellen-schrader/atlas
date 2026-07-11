"""Extract paper URLs from PDFs exported from a Microsoft Teams channel.

Two complementary sources are used and merged:

1. **Link annotations** (``page.get_links()``) -- these carry the *untruncated*
   href even when the visible text is shortened with an ellipsis, so they are
   the preferred source.
2. **Regex over the rendered text** (``page.get_text()``) -- a fallback that
   catches bare URLs that were never turned into clickable links.

Results are deduped by normalized URL. When it is cheap to do so we also grab a
nearby poster name and timestamp from the surrounding text (Teams renders these
just above each shared message).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

# A permissive http(s) URL matcher. We strip common trailing punctuation below.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Teams stamps look like "Ada Lovelace  3/14/2026 9:41 AM" or "Ada Lovelace 14 Mar 2026".
_POSTER_RE = re.compile(
    r"(?P<name>[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3})\s+"
    r"(?P<ts>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}(?:,?\s+\d{1,2}:\d{2}\s*[AP]M)?)",
)

# Trailing characters that are almost never part of the real URL.
_TRAILING_JUNK = ".,);:]}>”’'\""


@dataclass
class ExtractedURL:
    """One URL found in a PDF, with best-effort provenance."""

    url: str
    source_pdf: str
    page: int
    via: str  # "annotation" or "text"
    posted_by: str | None = None
    posted_at: str | None = None


@dataclass
class PDFExtraction:
    """All URLs extracted from a single PDF file."""

    path: str
    urls: list[ExtractedURL] = field(default_factory=list)


def _clean_url(url: str) -> str:
    """Trim whitespace and trailing punctuation from a candidate URL."""
    url = url.strip()
    while url and url[-1] in _TRAILING_JUNK:
        url = url[:-1]
    return url


def _normalize_key(url: str) -> str:
    """Key used only for dedup: lowercase host, drop trailing slash and fragment."""
    u = url.split("#", 1)[0].rstrip("/")
    return u.lower()


def _nearest_poster(text: str, span_start: int) -> tuple[str | None, str | None]:
    """Find the poster name/timestamp closest *above* a URL occurrence in text."""
    best: tuple[str | None, str | None] = (None, None)
    for m in _POSTER_RE.finditer(text, 0, span_start):
        best = (m.group("name").strip(), m.group("ts").strip())
    return best


def extract_urls_from_pdf(path: str | Path) -> PDFExtraction:
    """Extract deduped URLs (plus provenance) from one PDF."""
    path = Path(path)
    extraction = PDFExtraction(path=str(path))
    seen: set[str] = set()

    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc):
            page_no = page_index + 1
            text = page.get_text()

            # 1) Link annotations -- untruncated hrefs.
            for link in page.get_links():
                uri = link.get("uri")
                if not uri:
                    continue
                uri = _clean_url(uri)
                key = _normalize_key(uri)
                if not uri or key in seen:
                    continue
                seen.add(key)
                posted_by, posted_at = _nearest_poster(text, len(text))
                extraction.urls.append(
                    ExtractedURL(
                        url=uri,
                        source_pdf=str(path),
                        page=page_no,
                        via="annotation",
                        posted_by=posted_by,
                        posted_at=posted_at,
                    )
                )

            # 2) Regex over rendered text -- fallback for bare URLs.
            for m in _URL_RE.finditer(text):
                uri = _clean_url(m.group(0))
                key = _normalize_key(uri)
                if not uri or key in seen:
                    continue
                seen.add(key)
                posted_by, posted_at = _nearest_poster(text, m.start())
                extraction.urls.append(
                    ExtractedURL(
                        url=uri,
                        source_pdf=str(path),
                        page=page_no,
                        via="text",
                        posted_by=posted_by,
                        posted_at=posted_at,
                    )
                )

    return extraction


def extract_urls_from_dir(pdf_dir: str | Path) -> list[ExtractedURL]:
    """Extract URLs from every ``*.pdf`` under ``pdf_dir`` (deduped across files)."""
    pdf_dir = Path(pdf_dir)
    results: list[ExtractedURL] = []
    seen: set[str] = set()
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        for item in extract_urls_from_pdf(pdf).urls:
            key = _normalize_key(item.url)
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
    return results
