"""Clean inline markup out of stored paper titles (service role, one-off).

Crossref titles keep their JATS markup (``<sup>``, ``<i>``, ``<scp>``, ``&amp;``),
which the resolver stored as is until ``metadata.clean_title``; on cards it
reads "APOE <sup>+</sup> macrophages". New papers are cleaned on the way in;
this fixes the ones already stored. A title a person has edited is left alone,
and so is one that changed while the script ran.

Usage (from paper-radar/, with the service role configured):

    uv run python -m api.clean_titles              # report only
    uv run python -m api.clean_titles --apply
"""

from __future__ import annotations

import argparse
import re

from paper_radar.ingest.metadata import clean_title

from .supa import service_client

_PAGE = 1000
_MARKUP_RE = re.compile(r"<[a-zA-Z/][^>]*>|&[a-zA-Z]+;|&#")


def _fetch_titles(svc) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("papers")
            .select("id, title, edited_fields")
            .order("id")
            .range(start, start + _PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < _PAGE:
            break
        start += _PAGE
    return rows


def plan(rows: list[dict]) -> list[tuple[dict, str]]:
    """``(row, cleaned title)`` for every title with markup that cleaning changes."""
    out = []
    for row in rows:
        title = row.get("title")
        if not title or not _MARKUP_RE.search(title):
            continue
        if "title" in (row.get("edited_fields") or []):
            continue
        cleaned = clean_title(title)
        if cleaned and cleaned != title:
            out.append((row, cleaned))
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write; without it, only report")
    args = parser.parse_args(argv)

    svc = service_client()
    changes = plan(_fetch_titles(svc))
    print(f"Titles to clean: {len(changes)}")
    for row, cleaned in changes:
        if args.apply:
            # Matching on the old title: one edited meanwhile is skipped. The
            # embedding is computed from the title, so it is queued again.
            svc.table("papers").update({"title": cleaned, "embedded_at": None}).eq(
                "id", row["id"]
            ).eq("title", row["title"]).execute()
        print(f"  {'cleaned' if args.apply else 'would clean'}: {cleaned[:90]}")
    if args.apply and changes:
        print("Now run: uv run python -m api.backfill_embeddings")


if __name__ == "__main__":
    main()
