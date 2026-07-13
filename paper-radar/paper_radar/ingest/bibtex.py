"""Parse a BibTeX library into paper records.

The front door for getting a lab's back-catalogue in. Every reference manager a lab
already uses exports BibTeX (Zotero: right-click a collection → Export → BibTeX), and
the metadata is already structured — no PDF scraping, no regex, no publisher bot-walls.

This module only *parses*. It deliberately does no network I/O: resolving abstracts
from a DOI is `ingest.metadata.fetch_metadata`'s job, and keeping them separate is what
lets the API run a pre-flight ("here's what I'd import") without writing anything or
waiting on the network.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

import bibtexparser
from bibtexparser.bparser import BibTexParser

# BibTeX months come as "jan", "January", "1", or a raw month macro.
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
# TeX escapes and brace-protection that survive parsing: {\"o} -> ö is bibtexparser's
# job where it can, but stray braces used purely to protect capitalisation are not.
_BRACES = re.compile(r"[{}]")
_WS = re.compile(r"\s+")


@dataclass
class BibEntry:
    """One parsed BibTeX record, before any network enrichment."""

    key: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    year: int | None = None
    published_at: date | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)
    entry_type: str = "misc"

    @property
    def identifier(self) -> str | None:
        """The best URL for this entry — how the rest of the pipeline keys a paper."""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return self.url


@dataclass
class ParseResult:
    entries: list[BibEntry]
    #: Entries we could not use at all, as (key-or-position, human-readable reason).
    rejected: list[tuple[str, str]]


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    text = _BRACES.sub("", value)
    text = _WS.sub(" ", text).strip()
    return text or None


def _authors(raw: str | None) -> list[str]:
    """BibTeX authors are 'and'-separated and often 'Last, First'."""
    if not raw:
        return []
    out: list[str] = []
    for chunk in re.split(r"\s+and\s+", raw, flags=re.I):
        name = _clean(chunk)
        if not name:
            continue
        if "," in name:  # "Werb, Zena" -> "Zena Werb"
            last, _, first = name.partition(",")
            name = f"{first.strip()} {last.strip()}".strip()
        out.append(name)
    return out


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", raw)
    return int(m.group(1)) if m else None


def _month(raw: str | None) -> int | None:
    if not raw:
        return None
    text = _clean(raw)
    if not text:
        return None
    if text.isdigit():
        n = int(text)
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(text.lower()[:9]) or _MONTHS.get(text.lower()[:3])


def _published(year: int | None, month_raw: str | None, day_raw: str | None) -> date | None:
    """The publication date, at whatever precision BibTeX actually gives us.

    Almost always year-only, in which case this is YYYY-01-01. That imprecision is the
    reason publication date is stored separately from `posted_at` rather than replacing
    it: a corpus imported this way would otherwise pile hundreds of papers onto Jan 1
    and sort arbitrarily inside each year.
    """
    if not year:
        return None
    month = _month(month_raw) or 1
    day = 1
    if day_raw and (d := _clean(day_raw)) and d.isdigit():
        day = min(max(int(d), 1), calendar.monthrange(year, month)[1])
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, 1, 1)


def _doi(fields: dict[str, str]) -> str | None:
    """DOI from the `doi` field, or dug out of `url`/`note` where managers stash it."""
    for key in ("doi", "url", "note", "howpublished"):
        if m := _DOI_RE.search(fields.get(key, "") or ""):
            return m.group(1).rstrip(".,;").lower()
    return None


def _url(fields: dict[str, str]) -> str | None:
    raw = _clean(fields.get("url"))
    if raw and raw.startswith(("http://", "https://")):
        return raw
    return None


def parse_entry(fields: dict[str, str]) -> BibEntry:
    key = fields.get("ID") or fields.get("id") or ""
    year = _year(fields.get("year"))
    return BibEntry(
        key=key,
        title=_clean(fields.get("title")),
        authors=_authors(fields.get("author")),
        # Zotero writes the venue to journal/booktitle depending on entry type.
        venue=_clean(fields.get("journal") or fields.get("booktitle") or fields.get("publisher")),
        year=year,
        published_at=_published(year, fields.get("month"), fields.get("day")),
        doi=_doi(fields),
        url=_url(fields),
        abstract=_clean(fields.get("abstract")),
        keywords=[
            k for k in (_clean(x) for x in re.split(r"[;,]", fields.get("keywords", "") or "")) if k
        ],
        entry_type=(fields.get("ENTRYTYPE") or "misc").lower(),
    )


def parse_bibtex(text: str) -> ParseResult:
    """Parse a .bib file. Never raises on a malformed entry — it reports it.

    A researcher's real library will contain a few entries no parser can love. Failing
    the whole import because of three bad records out of four hundred would be the
    wrong trade: we surface them and import the rest.
    """
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = False

    try:
        db = bibtexparser.loads(text, parser=parser)
    except Exception as exc:  # noqa: BLE001 — a broken file is a user error, not a crash
        return ParseResult(entries=[], rejected=[("file", f"Could not parse the .bib file: {exc}")])

    entries: list[BibEntry] = []
    rejected: list[tuple[str, str]] = []

    for raw in db.entries:
        try:
            entry = parse_entry(raw)
        except Exception as exc:  # noqa: BLE001
            rejected.append((raw.get("ID", "?"), f"Unreadable entry: {exc}"))
            continue

        # A paper we can neither identify nor name is not importable: there is nothing
        # to dedupe on and nothing to show.
        if not entry.identifier and not entry.title:
            rejected.append((entry.key or "?", "No DOI, URL, or title — nothing to import"))
            continue
        entries.append(entry)

    return ParseResult(entries=entries, rejected=rejected)
