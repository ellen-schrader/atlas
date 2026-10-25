"""Run the saved searches that are due and file what is new (issue #164).

Daily, in the preprint-watch workflow, for labs where the saved_searches
feature is on for anyone:

1. Copy the bioRxiv/medRxiv preprints posted since the last copy into
   ``rxiv_feed`` (their API can only list by date), and drop ones past a month.
2. Finish imports the API was stopped in the middle of.
3. Run each active search last run a week ago or more, for an owner who is
   still in the lab and has the feature, and file the papers the lab does not
   have as suggestions for them (api/saved_searches.py).
4. Embed the papers people are waiting on, newest first, for up to
   EMBED_BUDGET, so the page can sort them by fit (Voyage's free tier allows
   ~12 a minute; what is left waits for tomorrow).

A run that fails on a source records it on the search (shown in settings),
files what the other sources found, and leaves the search due, so the next
day's run tries again over the same dates.

Usage (from paper-radar/, with api/.env configured):

    uv run python -m api.saved_searches_run [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import UTC, date, datetime, timedelta

from paper_radar.search import sources
from paper_radar.search.sources import SourceError

from . import saved_searches as ss
from .supa import service_client

log = logging.getLogger(__name__)

DUE_AFTER = timedelta(days=6, hours=12)  # weekly, whatever time yesterday's run took
FEED_KEEP_DAYS = 35
TIME_BUDGET = 15 * 60  # seconds; the rest wait for tomorrow
EMBED_BUDGET = 10 * 60  # seconds of embedding a day


def _feature_owners(svc) -> tuple[set[str], set[str]]:
    """(labs with the feature, people with it) -- a search runs if either holds."""
    teams = svc.table("team_features").select("team_id").eq("feature", ss.FEATURE).execute()
    users = svc.table("user_features").select("user_id").eq("feature", ss.FEATURE).execute()
    return {r["team_id"] for r in teams.data or []}, {r["user_id"] for r in users.data or []}


def due_searches(svc, now: datetime) -> list[dict]:
    teams, users = _feature_owners(svc)
    if not teams and not users:
        return []
    rows = (
        svc.table("saved_searches")
        .select(ss._SEARCH_COLUMNS)
        .eq("active", True)
        .order("last_run_at", desc=False, nullsfirst=True)
        .execute()
        .data
        or []
    )
    cutoff = now - DUE_AFTER
    rows = [
        r
        for r in rows
        if (r["team_id"] in teams or r["user_id"] in users)
        and (not r["last_run_at"] or datetime.fromisoformat(r["last_run_at"]) <= cutoff)
    ]
    if not rows:
        return []
    members = (
        svc.table("team_members")
        .select("team_id, user_id")
        .in_("team_id", list({r["team_id"] for r in rows}))
        .execute()
        .data
        or []
    )
    still_in = {(m["team_id"], m["user_id"]) for m in members}
    return [r for r in rows if (r["team_id"], r["user_id"]) in still_in]


def refresh_feed(svc, today: date, *, dry_run: bool) -> int:
    """Copy new bioRxiv/medRxiv first versions into rxiv_feed. Returns how many."""
    latest = (
        svc.table("rxiv_feed").select("posted_on").order("posted_on", desc=True).limit(1).execute()
    ).data
    since = today - timedelta(days=ss.WINDOW_DAYS + 1)
    if latest:
        # Two days back: bioRxiv posts a day's papers over the following day.
        since = max(since, date.fromisoformat(latest[0]["posted_on"]) - timedelta(days=2))
    copied = 0
    for server in ("biorxiv", "medrxiv"):
        try:
            for page in sources.rxiv_posted(server, since, today):
                if page and not dry_run:
                    svc.table("rxiv_feed").upsert(
                        [
                            {
                                "doi": p.doi,
                                "server": p.server,
                                "title": p.title,
                                "abstract": p.abstract,
                                "authors": p.authors[:100],
                                "category": p.category,
                                "posted_on": p.posted_on,
                            }
                            for p in page
                            if p.posted_on
                        ],
                        on_conflict="doi",
                    ).execute()
                copied += len(page)
        except SourceError as exc:
            # Searches still run on what was copied before; tomorrow catches up.
            log.warning("copying %s failed: %s", server, exc)
    if not dry_run:
        old = (today - timedelta(days=FEED_KEEP_DAYS)).isoformat()
        svc.table("rxiv_feed").delete().lt("posted_on", old).execute()
    return copied


def run(*, dry_run: bool = False) -> tuple[int, int, int]:
    """(searches run, new suggestions, searches with an error)."""
    svc = service_client()
    now = datetime.now(UTC)
    if not any(_feature_owners(svc)):
        return 0, 0, 0
    # Every day, not only when a search is due: a search saved today, and the
    # preview, match against this copy.
    copied = refresh_feed(svc, now.date(), dry_run=dry_run)
    print(f"bioRxiv/medRxiv: {copied} new preprints copied")
    if not dry_run and (retried := ss.retry_stuck_imports(svc, now)):
        print(f"  {retried} interrupted imports retried")
    ran, new, failed = _run_due(svc, now, dry_run=dry_run)
    if not dry_run:
        print(f"  {ss.embed_candidates(svc, EMBED_BUDGET)} suggested papers embedded")
    return ran, new, failed


def _run_due(svc, now: datetime, *, dry_run: bool) -> tuple[int, int, int]:
    searches = due_searches(svc, now)
    if not searches:
        return 0, 0, 0
    feed_since = min(ss.window(s["last_run_at"], now.date())[0] for s in searches)
    feed = ss.rxiv_feed(svc, feed_since) if any("biorxiv" in s["sources"] for s in searches) else []
    started = time.monotonic()
    ran = new = failed = 0
    for search in searches:
        if time.monotonic() - started > TIME_BUDGET:
            print(f"  time budget spent; {len(searches) - ran} searches wait for tomorrow")
            break
        ran += 1
        try:
            if dry_run:
                since, until = ss.window(search["last_run_at"], now.date())
                found, errors = ss.run_query(
                    search["query"],
                    search["sources"],
                    since,
                    until,
                    feed=feed,
                    arxiv_categories=search.get("arxiv_categories") or (),
                )
                counts = ", ".join(f"{s}={len(h)}" for s, h in found.items())
                print(f"  {search['id']}: would file from {counts}; errors: {errors or 'none'}")
                failed += bool(errors)
                continue
            added, error = ss.run_saved_search(svc, search, now.date(), feed)
        except Exception as exc:
            failed += 1
            print(f"  ! {search['id']} failed, left for the next run: {exc}")
            continue
        new += added
        failed += bool(error)
        print(f"  {search['id']}: {added} new" + (f" ({error})" if error else ""))
    return ran, new, failed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ran, new, failed = run(dry_run=args.dry_run)
    print(
        f"Done ({'dry run' if args.dry_run else 'did'}): searches={ran} new={new} failed={failed}"
    )
    # A source being down is recorded on each search and retried next week; it
    # is not a reason to fail the workflow and bury the other steps' results.


if __name__ == "__main__":
    main()
