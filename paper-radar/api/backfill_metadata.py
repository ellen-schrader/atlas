"""Re-resolve papers the metadata resolver could not handle before (service role).

Two populations, both left behind by resolution gaps that PR #102 closed:

  * **Untitled rows** — a paper whose landing page was bot-walled and whose URL
    carried no identifier the resolver understood, so it was stored as a bare
    link. It renders as a URL everywhere and is invisible to search: no title
    means no embedding and nothing to enrich.
  * **Rendition DOIs** — a bioRxiv/medRxiv row whose ``doi`` kept the version
    suffix from the URL (``10.1101/2026.05.11.724388v1``). That string is not a
    registered DOI, and ``papers.doi`` IS the dedup key, so the same preprint
    posted later under its real DOI comes in as a second row.

Both are fixed by running the current resolver over ``papers.url`` again and
writing back what it finds. Idempotent: a row that resolves is no longer in
either population, and a row that still doesn't resolve is left exactly as it
was. Nothing is deleted and no row is ever blanked -- a field is only written
when the resolver produced a value for it.

Usage (from paper-radar/, with api/.env configured):

    uv run python -m api.backfill_metadata --dry-run     # always look first
    uv run python -m api.backfill_metadata
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import date

from paper_radar.ingest.metadata import fetch_metadata
from paper_radar.ingest.urls import norm_doi

from .supa import service_client

_PAGE = 500

# A stored DOI that is really a bioRxiv/medRxiv *rendition* of one: the version
# (and whatever the reader clicked -- ".full", ".supplementary-material") came
# along from the URL path. Anchored on the two preprint registrants on purpose:
# a trailing "v<n>" is only meaningless there, and a looser pattern would happily
# truncate a real DOI that just happens to end that way.
_RENDITION_DOI_RE = re.compile(r"^10\.(?:1101|64898)/.+?v\d+(?:\.[a-z0-9.\-]+)?$", re.IGNORECASE)

# Written back only when the resolver found something for them. `authors` and
# `keywords` are NOT NULL jsonb, so an empty list is a legitimate value to skip
# rather than write over what a human or an earlier resolver put there.
_TEXT_FIELDS = ("title", "venue", "year", "doi", "abstract")
_LIST_FIELDS = ("authors", "keywords")


def _fetch_candidates(svc) -> list[dict]:
    """Every paper that is untitled or holds a rendition DOI, oldest first.

    Filtered client-side rather than in the query: the rendition test is the
    regex above, and keeping one definition means the script can never disagree
    with itself about which rows it is fixing.

    Selects every column `plan_update` compares against, not just the two it
    filters on -- a field the script hasn't read is a field it would rewrite
    blind, which is how a hand-corrected venue gets clobbered by a resolver.
    """
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("papers")
            .select(
                "id, url, doi, title, authors, venue, year, abstract, keywords, "
                "metadata_source, published_at, edited_at, edited_fields"
            )
            .order("created_at")
            .range(start, start + _PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < _PAGE:
            break
        start += _PAGE
    return [r for r in rows if needs_backfill(r)]


def needs_backfill(row: dict) -> bool:
    """True if this row is untitled or its DOI is a preprint rendition."""
    if not (row.get("title") or "").strip():
        return True
    doi = row.get("doi")
    return bool(doi and _RENDITION_DOI_RE.match(doi))


def follow_year(patch: dict, row: dict) -> None:
    """Move ``published_at`` along with a changed ``year``, in place.

    The Papers page sorts on ``published_at``, which the bibtex migration
    backfilled from ``year`` as ``YYYY-01-01``. Correct the year without it and
    the sort disagrees with the year on screen. Only a January 1st — that
    migration's marker for "year only" — is rewritten; a date with real day
    precision came from somewhere that knew more than the year field does.
    """
    if "year" not in patch:
        return
    current = row.get("published_at")
    if isinstance(current, str):
        current = date.fromisoformat(current[:10])
    if current is not None and (current.month, current.day) != (1, 1):
        return
    year = patch["year"]
    new = date(year, 1, 1).isoformat() if year else None
    if new != (current.isoformat() if current else None):
        patch["published_at"] = new


def plan_update(
    row: dict, meta, doi_owner: str | None, held=()
) -> tuple[dict, str | None]:
    """The patch for one row, plus a note if something needed a human.

    ``held`` is the row's ``edited_fields``: keys a person has corrected by hand.
    They are left off the patch and everything else is still written — a row
    with a hand-fixed title and no abstract should still get the abstract.

    ``doi_owner`` is the id of the paper already holding the resolved DOI, if any
    (the caller looks it up). That case is a genuine duplicate -- two rows, one
    paper -- and merging it means moving paper_posts, reactions and comments,
    which is not a decision a backfill should make. The DOI is left off the patch
    so the UNIQUE constraint holds, the rest of the metadata is still written,
    and the pair is reported for a human to merge.
    """
    if not meta.title:
        return {}, "unresolved"

    patch: dict = {}
    for field in _TEXT_FIELDS:
        value = getattr(meta, field)
        if field == "doi":
            value = norm_doi(value)
        if value is not None and value != row.get(field):
            patch[field] = value
    for field in _LIST_FIELDS:
        value = getattr(meta, field)
        if value and value != row.get(field):
            patch[field] = value
    for field in held:
        patch.pop(field, None)

    note = None
    if doi_owner is not None and doi_owner != row["id"]:
        patch.pop("doi", None)
        note = f"duplicate of {doi_owner}"

    if not patch:
        # Still return the note: a row whose only change was a colliding DOI is
        # exactly the duplicate pair a person needs to hear about.
        return {}, note

    follow_year(patch, row)
    patch["metadata_source"] = meta.source
    # The embedding and the tags are both computed from title + abstract, so a
    # change to either makes them stale; the existing backfills pick the row up
    # from these nulls. Nothing else is worth a re-embed and a re-tag.
    if "title" in patch or "abstract" in patch:
        patch["embedded_at"] = None
        patch["enriched_at"] = None
    return patch, note


def _write_unless_edited(svc, row: dict, patch: dict) -> bool:
    """Write the patch only if nobody has edited the row since it was read.

    Candidates are read once, up front, and each one then waits on a network
    lookup — so a person can correct a row between the read and this write, and
    the patch was planned against the old ``edited_fields``. Matching on
    ``edited_at`` makes that a skip instead of a silent overwrite. Returns False
    when skipped.
    """
    query = svc.table("papers").update(patch).eq("id", row["id"])
    if row.get("edited_at"):
        query = query.eq("edited_at", row["edited_at"])
    else:
        query = query.is_("edited_at", "null")
    return bool(query.execute().data)


def _doi_owner(svc, doi: str | None, row_id: str) -> str | None:
    """The id of another paper already holding ``doi``, or None."""
    if not doi:
        return None
    found = svc.table("papers").select("id").eq("doi", doi).limit(1).execute().data or []
    return found[0]["id"] if found and found[0]["id"] != row_id else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--limit", type=int, help="stop after this many rows")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between lookups")
    args = parser.parse_args(argv)

    svc = service_client()
    rows = _fetch_candidates(svc)
    if args.limit:
        rows = rows[: args.limit]
    untitled = sum(1 for r in rows if not (r.get("title") or "").strip())
    print(f"{len(rows)} rows to re-resolve ({untitled} untitled, {len(rows) - untitled} bad DOI)")

    fixed = unresolved = duplicates = unchanged = 0
    for i, row in enumerate(rows, 1):
        meta = fetch_metadata(row["url"])
        owner = _doi_owner(svc, norm_doi(meta.doi), row["id"])
        patch, note = plan_update(row, meta, owner, held=row.get("edited_fields") or ())

        if note == "unresolved":
            unresolved += 1
            print(f"  [{i}/{len(rows)}] still unresolved: {row['url']}")
        elif not patch:
            if note:
                duplicates += 1
                print(f"  [{i}/{len(rows)}] {note} — merge by hand: {row['id']} {row['url']}")
            unchanged += 1
        else:
            if note:
                duplicates += 1
                print(f"  [{i}/{len(rows)}] {note} — merge by hand: {row['id']} {row['url']}")
            title = str(patch.get("title") or row.get("title"))[:60]
            if args.dry_run or _write_unless_edited(svc, row, patch):
                fixed += 1
                print(f"  [{i}/{len(rows)}] {'would fix' if args.dry_run else 'fixed'}: {title}")
            else:
                unchanged += 1
                print(f"  [{i}/{len(rows)}] skipped, edited by hand while this ran: {title}")
        time.sleep(args.delay)

    verb = "would fix" if args.dry_run else "fixed"
    print(
        f"Done. {verb}={fixed} unresolved={unresolved} unchanged={unchanged} "
        f"duplicates-needing-merge={duplicates}"
    )
    if fixed and not args.dry_run:
        print(
            "Now run: uv run python -m api.backfill_embeddings && "
            "uv run python -m api.backfill_enrichment"
        )


if __name__ == "__main__":
    main()
