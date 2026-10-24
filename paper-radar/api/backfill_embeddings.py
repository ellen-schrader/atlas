"""Backfill paper embeddings into pgvector (service role).

Embeds every paper still missing ``embedded_at`` (or everything with
``--all``, e.g. after switching embedding models) and writes the vectors to
``papers.embedding``. Safe to re-run; papers without title or abstract are
skipped.

Usage (from paper-radar/, with api/.env configured):

    uv run python -m api.backfill_embeddings [--all] [--batch-size 4]
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from . import embeddings
from .supa import service_client

_RATE_LIMIT_PAUSE = 60  # seconds: one full per-minute window

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


def main(argv: list[str] | None = None) -> int:
    """Returns how many papers failed, so a caller (or the exit status) can tell."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-embed every paper, not just those missing embedded_at",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=embeddings.BATCH_SIZE,
        help="papers per API request (at most embeddings.BATCH_SIZE)",
    )
    parser.add_argument(
        "--delay", type=float, default=20.0, help="Seconds between batches (3 a minute)"
    )
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
    # A chunk is one API request: a bigger one would be split by embed_texts,
    # and a failure in a later piece would throw away vectors already paid for.
    size = max(1, min(args.batch_size, embeddings.BATCH_SIZE))
    done = failed = 0
    for start in range(0, len(todo), size):
        chunk = todo[start : start + size]
        texts = [text for _, text in chunk]
        try:
            try:
                vectors = embeddings.embed_texts(texts)
            except embeddings.EmbeddingError as exc:
                if exc.status != 429:
                    raise
                # Past the client's own retries. A per-minute limit is over after
                # a full minute; if the batch still fails, it is a quota or
                # billing limit and every remaining batch would fail the same way.
                print(f"  batch at {start} rate-limited ({exc.detail or exc}); waiting 60s")
                time.sleep(_RATE_LIMIT_PAUSE)
                vectors = embeddings.embed_texts(texts)
        except embeddings.EmbeddingError as exc:
            reason = f"{exc}: {exc.detail}" if exc.detail else str(exc)
            if exc.status == 429:
                failed += len(todo) - start
                print(f"  batch at {start} failed ({reason}); stopping, re-run to retry")
                break
            failed += len(chunk)
            print(f"  batch at {start} failed ({reason}); skipping, re-run to retry")
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
    return failed


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
