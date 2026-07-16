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
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

from .urls import _clean_url, _normalize_key

__all__ = [
    "ExtractedURL",
    "PDFExtraction",
    "_clean_url",
    "_normalize_key",
    "extract_urls_from_dir",
    "extract_urls_from_pdf",
]

# Teams timestamp formats, tried in order. European day-first is preferred (this
# lab's exports use DD/MM/YYYY); US month-first is a last-resort fallback.
_STAMP_FORMATS = (
    "%d/%m/%Y %H:%M",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
)

# A permissive http(s) URL matcher. We strip common trailing punctuation below.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Teams stamps look like "Ellen Schrader 17/12/2025 17:14" (24h, European) or
# "Ada Lovelace 3/14/2026 9:41 AM" (12h). Time (with or without AM/PM) is optional.
_POSTER_RE = re.compile(
    r"(?P<name>[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3})\s+"
    r"(?P<ts>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}(?:,?\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?)",
)

# A *primary* Teams post header renders the sender's name and timestamp as two
# separate text runs on the *same line* (name, then timestamp just to its
# right), so the single-line _POSTER_RE — which wants them in one run — never
# matches it and only catches the inline reply/edit stamps. These match a run
# that is *only* a name and a run that is *only* a timestamp, which
# _page_poster_stamps pairs by vertical position.
_NAME_ONLY_RE = re.compile(r"[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){0,3}")
_TS_ONLY_RE = re.compile(
    r"\d{1,2}[/.]\d{1,2}[/.]\d{2,4}(?:,?\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?"
)

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


def _page_poster_stamps(page: fitz.Page) -> list[tuple[float, str, str]]:
    """Collect ``(y_top, name, timestamp)`` poster stamps on a page, sorted by y.

    Teams renders each message with the sender's name + timestamp on its own line
    above the message body, so a stamp's vertical position lets us attribute the
    links below it to the right person.
    """
    # Collect (x0, y_top, text) runs.
    runs: list[tuple[float, float, str]] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            txt = "".join(span["text"] for span in line.get("spans", [])).strip()
            if txt:
                runs.append((line["bbox"][0], line["bbox"][1], txt))

    stamps: list[tuple[float, str, str]] = []

    # 1) Inline stamps ("Name DD/MM/YYYY HH:MM") — reply/edit markers on one run.
    for _x, y, txt in runs:
        m = _POSTER_RE.search(txt)
        if m:
            stamps.append((y, m.group("name").strip(), m.group("ts").strip()))

    # 2) Primary post headers: a name-only run and a timestamp-only run on the
    #    same visual line (Teams lays them side by side). Pair each bare
    #    timestamp with the nearest bare-name run just to its left at the same y.
    names = [(x, y, t) for x, y, t in runs if _NAME_ONLY_RE.fullmatch(t)]
    for tx, ty, tt in runs:
        if not _TS_ONLY_RE.fullmatch(tt):
            continue
        candidates = [(nx, ny, nt) for nx, ny, nt in names if abs(ny - ty) <= 3.0 and nx < tx]
        if candidates:
            nx, ny, nt = max(candidates, key=lambda c: c[0])  # closest to the left
            stamps.append((min(ny, ty), nt, tt))

    stamps.sort(key=lambda s: s[0])
    return stamps


def _poster_for_y(stamps: list[tuple[float, str, str]], y: float) -> tuple[str | None, str | None]:
    """Return the poster stamp closest *above* vertical position ``y`` (or None)."""
    best: tuple[str | None, str | None] = (None, None)
    for sy, name, ts in stamps:
        if sy <= y + 2.0:  # small tolerance: stamp and its link often share a line
            best = (name, ts)
        else:
            break
    return best


def _nearest_poster_in_text(text: str, span_start: int) -> tuple[str | None, str | None]:
    """Fallback for bare-text URLs: nearest poster stamp earlier in reading order."""
    best: tuple[str | None, str | None] = (None, None)
    for m in _POSTER_RE.finditer(text, 0, span_start):
        best = (m.group("name").strip(), m.group("ts").strip())
    return best


def parse_posted_at(stamp: str | None) -> datetime | None:
    """Parse a Teams timestamp string (e.g. ``16/10/2025 10:26``) to a datetime.

    Returns ``None`` when the string is missing or in an unrecognised format.
    """
    if not stamp:
        return None
    stamp = stamp.strip()
    for fmt in _STAMP_FORMATS:
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def extract_urls_from_pdf(path: str | Path) -> PDFExtraction:
    """Extract deduped URLs (plus provenance) from one PDF."""
    path = Path(path)
    extraction = PDFExtraction(path=str(path))
    seen: set[str] = set()

    with fitz.open(path) as doc:
        for page_index, page in enumerate(doc):
            page_no = page_index + 1
            text = page.get_text()
            stamps = _page_poster_stamps(page)

            # 1) Link annotations -- untruncated hrefs. Attribute each to the
            #    nearest poster stamp above the link's vertical position.
            for link in page.get_links():
                uri = link.get("uri")
                if not uri:
                    continue
                uri = _clean_url(uri)
                key = _normalize_key(uri)
                if not uri or key in seen:
                    continue
                seen.add(key)
                link_y = link["from"].y0 if link.get("from") is not None else 0.0
                posted_by, posted_at = _poster_for_y(stamps, link_y)
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
                posted_by, posted_at = _nearest_poster_in_text(text, m.start())
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
