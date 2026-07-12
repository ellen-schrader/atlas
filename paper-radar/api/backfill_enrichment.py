"""Backfill topical tags into papers.tags via batched LLM enrichment (service role).

Tags every paper with ``enriched_at`` null (or ``--all`` to re-tag). Batched to
keep the Claude call count low, and idempotent — re-run to fill any that failed.
Papers with no title/abstract are skipped (nothing to tag).

Usage (from paper-radar/, with ANTHROPIC_API_KEY in .env):
    uv run python -m api.backfill_enrichment [--all] [--batch-size 15] [--delay 1]
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from . import enrichment
from .supa import service_client

_PAGE = 500


def _fetch_papers(svc, re_tag_all: bool) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        query = svc.table("papers").select("id, title, abstract, enriched_at").order("created_at")
        if not re_tag_all:
            query = query.is_("enriched_at", "null")
        page = query.range(start, start + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        start += _PAGE


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="re-tag every paper, not just new")
    parser.add_argument("--batch-size", type=int, default=enrichment.BATCH_SIZE, help="papers/call")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between batches")
    args = parser.parse_args(argv)

    svc = service_client()
    rows = _fetch_papers(svc, args.all)
    todo = [r for r in rows if (r.get("title") or "").strip() or (r.get("abstract") or "").strip()]
    print(f"{len(todo)} papers to tag ({len(rows) - len(todo)} skipped: no title/abstract)")

    done = failed = 0
    for start in range(0, len(todo), args.batch_size):
        chunk = todo[start : start + args.batch_size]
        tags = enrichment.enrich_batch(chunk)
        now = datetime.now(UTC).isoformat()
        for row in chunk:
            t = tags.get(row["id"])
            if t is None:
                failed += 1
                continue
            svc.table("papers").update({"tags": t, "enriched_at": now}).eq(
                "id", row["id"]
            ).execute()
            done += 1
        print(f"  {done + failed}/{len(todo)}  tagged={done} failed={failed}")
        time.sleep(args.delay)
    print(f"Done. tagged={done} failed={failed}")


if __name__ == "__main__":
    main()
