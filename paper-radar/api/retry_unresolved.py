"""Re-drive the inbound links Atlas couldn't read (service role).

Every @Atlas mention whose URL didn't resolve to a paper is queued in
``inbound_unresolved`` instead of being dropped. This walks the open rows and
runs the current resolver over them again — so after teaching the resolver a new
publisher, one command recovers everything that publisher had silently cost.

Rows that resolve are closed (``resolved_at``, ``resolved_paper_id``) by the
import itself; rows that still fail have their ``attempts`` bumped and stay open.
Idempotent, and safe to run as often as you like.

Nothing is posted to Teams: the inbound import writes to the lab, it does not
mirror a card back to the channel.

Usage (from paper-radar/, with api/.env configured):

    uv run python -m api.retry_unresolved --dry-run
    uv run python -m api.retry_unresolved [--reason no_identifier] [--limit 50]
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from urllib.parse import urlsplit

from .supa import service_client
from .teams_integration import import_paper_background

_PAGE = 500


def fetch_open(svc, reason: str | None = None) -> list[dict]:
    """Every unresolved row, oldest first, optionally narrowed to one reason."""
    rows: list[dict] = []
    start = 0
    while True:
        query = (
            svc.table("inbound_unresolved")
            .select("id, team_id, url, url_norm, sender_label, reason, attempts")
            .is_("resolved_at", "null")
            .order("first_seen_at")
        )
        if reason:
            query = query.eq("reason", reason)
        page = query.range(start, start + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        start += _PAGE


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.") or "(none)"
    except ValueError:
        return "(unparseable)"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, retry nothing")
    parser.add_argument("--reason", help="only rows with this reason")
    parser.add_argument("--limit", type=int, help="stop after this many rows")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between retries")
    args = parser.parse_args(argv)

    svc = service_client()
    rows = fetch_open(svc, args.reason)
    if args.limit:
        rows = rows[: args.limit]

    print(f"{len(rows)} unresolved links")
    for reason, n in Counter(r["reason"] for r in rows).most_common():
        print(f"  {n:>4}  {reason}")
    # The publisher histogram is the point of the queue as much as the retry is:
    # it says which publisher is costing the lab the most papers, i.e. what to
    # teach the resolver next.
    print("by host:")
    for host, n in Counter(_host(r["url"]) for r in rows).most_common(15):
        print(f"  {n:>4}  {host}")

    if args.dry_run:
        print("\n(dry run — nothing retried)")
        return

    print()
    recovered = still_failing = 0
    for i, row in enumerate(rows, 1):
        # Closes the queue row on success and bumps attempts on failure.
        paper_id = import_paper_background(row["team_id"], row["url"], row["sender_label"])
        if paper_id:
            recovered += 1
            print(f"  [{i}/{len(rows)}] recovered: {row['url'][:88]}")
        else:
            still_failing += 1
        time.sleep(args.delay)
    print(f"\nDone. recovered={recovered} still-unresolved={still_failing}")
    if recovered:
        print(
            "Now run: uv run python -m api.backfill_embeddings && "
            "uv run python -m api.backfill_enrichment"
        )


if __name__ == "__main__":
    main()
