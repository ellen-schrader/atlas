"""Daily: find abstracts for papers that came in without one (issue #136).

Most papers arrive with an abstract. The ones that don't are usually posted the
day they come out, before Europe PMC or PubMed have indexed them, so the lookup
at ingest finds nothing -- and BibTeX imports skip that lookup entirely. This
asks again (``find_abstract``: Europe PMC, then PubMed, both by DOI, then the
paper's own page) on a schedule that follows how indexing actually lags:

  * daily for a paper's first 30 days,
  * weekly until it is 90 days old (age counts from publication when the row
    knows it, so a BibTeX import of 2015 papers is not treated as new),
  * once, for anything older that has never been checked (the first run's
    backlog), and then never again.

News pieces, editorials and comment articles have no abstract anywhere; the
schedule is what stops the job asking about them forever.

Only the abstract is written (plus keywords, if the row had none). The rest of
the row stays as it is: a source that has the abstract may still disagree with
Crossref about the venue or the author list, and this job is not the place to
settle that. A changed abstract makes the embedding and tags stale, so it
clears ``embedded_at``/``enriched_at`` for the re-embed and re-tag that the
daily preprint-watch run does next.

Runs on the preprint-watch schedule (.github/workflows/preprint-watch.yml).
By hand (from paper-radar/, with the service role in the environment):

    uv run python -m api.backfill_abstracts --dry-run    # always look first
    uv run python -m api.backfill_abstracts
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime, timedelta

from paper_radar.ingest.metadata import find_abstract
from paper_radar.ingest.urls import norm_doi

from .backfill_metadata import _write_unless_edited
from .merge_suggestions import fold
from .supa import service_client

_PAGE = 500

_DAILY_UNTIL = timedelta(days=30)
_WEEKLY_UNTIL = timedelta(days=90)
# A little under the period, so a run that starts a few minutes earlier than
# yesterday's still counts the paper as due.
_DAILY = timedelta(hours=20)
_WEEKLY = timedelta(days=6, hours=20)


def _ts(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _born(row: dict) -> datetime:
    """When the paper came out, as far as the row can say: indexing lags
    publication, not the day a lab member happened to post it.

    ``published_at`` on January 1st is the "year only" marker, so a year counts
    as its last day -- the latest the paper could have appeared. Never later
    than ``created_at``: a paper can't come out after it was posted.
    """
    added = _ts(row["created_at"])
    published = row.get("published_at")
    if published and str(published)[5:10] != "01-01":
        out = datetime.fromisoformat(str(published)[:10]).replace(tzinfo=UTC)
    elif row.get("year"):
        out = datetime(int(row["year"]), 12, 31, tzinfo=UTC)
    else:
        return added
    return min(out, added)


def is_due(row: dict, now: datetime) -> bool:
    """Whether the schedule says to look for this paper's abstract now."""
    checked = _ts(row.get("abstract_checked_at"))
    if checked is None:
        return True
    age = now - _born(row)
    if age <= _DAILY_UNTIL:
        return now - checked >= _DAILY
    if age <= _WEEKLY_UNTIL:
        return now - checked >= _WEEKLY
    return False


def page_is_the_paper(row: dict, found) -> bool:
    """Whether a scraped page is this paper's own: same DOI, or same title.

    A stored URL can come to redirect to a login wall, a consent page or a
    journal homepage, whose long site description would otherwise be filed as
    the abstract and never looked at again.
    """
    if row.get("doi") and found.doi:
        return norm_doi(row["doi"]) == norm_doi(found.doi)
    return bool(found.title and row.get("title")) and fold(found.title) == fold(row["title"])


def plan_patch(row: dict, found) -> dict:
    """What to write for one row, given ``find_abstract``'s result (or None).

    Always stamps ``abstract_checked_at``. An abstract a person has set by hand
    (``edited_fields``) is never replaced -- the row is only marked as checked.
    """
    patch: dict = {"abstract_checked_at": datetime.now(UTC).isoformat()}
    held = row.get("edited_fields") or ()
    if found is None or not found.abstract or "abstract" in held:
        return patch
    if found.source == "page" and not page_is_the_paper(row, found):
        return patch
    patch["abstract"] = found.abstract
    if found.keywords and not row.get("keywords") and "keywords" not in held:
        patch["keywords"] = found.keywords
    # Embedding and tags are computed from title + abstract; the daily
    # backfill_embeddings / backfill_enrichment pick the row up from these nulls.
    patch["embedded_at"] = None
    patch["enriched_at"] = None
    return patch


def _fetch_candidates(svc, now: datetime) -> list[dict]:
    """Titled papers with no abstract that are due a look, stalest first.

    The database drops rows checked before and added over 90 days ago -- the
    schedule never asks about those again, and they only accumulate. The rest
    of the schedule is ``is_due``, in Python.
    """
    window = (now - _WEEKLY_UNTIL).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("papers")
            .select(
                "id, url, doi, title, keywords, year, published_at, created_at, "
                "abstract_checked_at, edited_at, edited_fields"
            )
            .or_("abstract.is.null,abstract.eq.")
            .or_(f"abstract_checked_at.is.null,created_at.gt.{window}")
            .not_.is_("title", "null")
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
    due = [r for r in rows if (r.get("title") or "").strip() and is_due(r, now)]
    # Never-checked first, then longest ago, so a run cut short by its time
    # budget hands the next run different papers.
    due.sort(key=lambda r: r.get("abstract_checked_at") or "")
    return due


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--limit", type=int, help="look up at most this many papers")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between papers")
    parser.add_argument(
        "--budget-minutes", type=float, default=8, help="stop starting new lookups after this"
    )
    args = parser.parse_args(argv)

    svc = service_client()
    rows = _fetch_candidates(svc, datetime.now(UTC))
    if args.limit:
        rows = rows[: args.limit]
    print(f"{len(rows)} paper(s) without an abstract are due a look")

    deadline = time.monotonic() + args.budget_minutes * 60
    found_n = missing = skipped = failed = 0
    for i, row in enumerate(rows, 1):
        if time.monotonic() > deadline:
            print(f"  time budget spent; {len(rows) - i + 1} left for the next run")
            break
        title = (row.get("title") or "")[:60]
        try:
            found = find_abstract(row.get("doi"), row["url"])
            patch = plan_patch(row, found)
            if "abstract" in patch:
                found_n += 1
                verb = "would add" if args.dry_run else "added"
                print(f"  [{i}/{len(rows)}] {verb} ({found.source}): {title}")
            else:
                missing += 1
            if not args.dry_run and not _write_unless_edited(svc, row, patch):
                skipped += 1
                print(f"  [{i}/{len(rows)}] skipped, edited by hand while this ran: {title}")
        except Exception as exc:  # noqa: BLE001 -- one bad paper must not stop the run
            failed += 1
            print(f"  ! {row['id']} failed, left for the next run: {exc}")
        time.sleep(args.delay)

    verb = "would add" if args.dry_run else "added"
    print(
        f"Done. {verb}={found_n} still-missing={missing} skipped-edited={skipped} failed={failed}"
    )
    if failed:
        # Red in GitHub Actions, so a broken run is noticed; the next run retries.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
