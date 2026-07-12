"""Backfill paper embeddings into pgvector (service role).

Embeds every paper still missing ``embedded_at`` (or everything with
``--all``, e.g. after switching embedding models) and writes the vectors to
``papers.embedding``. Safe to re-run; papers without title or abstract are
skipped.

Usage (from paper-radar/, with api/.env configured):

    uv run python -m api.backfill_embeddings [--all] [--batch-size 64]
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from . import embeddings
from .supa import service_client

_PAGE = 500


def _fetch_papers(svc, re_embed_all: bool) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        query = svc.table("papers").select("id, title, abstract").order("created_at")
        if not re_embed_all:
            query = query.is_("embedded_at", "null")
        page = query.range(start, start + _PAGE - 1).execute().data or []
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        start += _PAGE


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-embed every paper, not just those missing embedded_at",
    )
    parser.add_argument("--batch-size", type=int, default=16, help="papers per API request")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between batches")
    args = parser.parse_args(argv)

    svc = service_client()
    rows = _fetch_papers(svc, args.all)
    todo = [(row, embeddings.paper_text(row["title"], row["abstract"])) for row in rows]
    skipped = sum(1 for _, text in todo if not text)
    todo = [(row, text) for row, text in todo if text]
    print(f"{len(todo)} papers to embed ({skipped} skipped: no title/abstract)")

    # Each batch's rows are written as soon as it embeds, so a mid-run failure
    # keeps all prior progress — re-running resumes (embedded_at is null only for
    # the rest). Batches are paced to stay under the API's per-minute limit.
    done = failed = 0
    for start in range(0, len(todo), args.batch_size):
        chunk = todo[start : start + args.batch_size]
        try:
            vectors = embeddings.embed_texts([text for _, text in chunk])
        except embeddings.EmbeddingError as exc:
            failed += len(chunk)
            print(f"  batch at {start} failed ({exc}); skipping, re-run to retry")
            continue
        now = datetime.now(UTC).isoformat()
        for (row, _), vector in zip(chunk, vectors, strict=True):
            svc.table("papers").update({"embedding": vector, "embedded_at": now}).eq(
                "id", row["id"]
            ).execute()
        done += len(chunk)
        print(f"  {done}/{len(todo)}")
        time.sleep(args.delay)
    print(f"Done. embedded={done} failed={failed}")


if __name__ == "__main__":
    main()
