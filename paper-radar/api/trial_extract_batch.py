"""Queued extractions through the Message Batches API: half price, within hours.

Every two hours (.github/workflows/trial-extraction.yml):
  1. collect: for each batch Atlas sent, once it has ended, store each
     result (or retry it once in the next batch, or mark it failed);
  2. submit: send the queued trials of labs still under their monthly
     budget as one new batch.

Same request as "Extract now" (api/trial_extract.request) except that batches
take no server-side fallback: a refusal is reported, and "Extract now" (which
has one) is the way round it.

    python -m api.trial_extract_batch
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from . import trial_extract as te
from .supa import service_client
from .trial_links import active_teams

log = logging.getLogger(__name__)

MAX_PER_BATCH = 50
MAX_ATTEMPTS = 2  # a failed or unusable answer is tried once more
BATCH_DISCOUNT = 0.5
STUCK = timedelta(hours=30)  # batches end within 24 h; past this, ask again


def custom_id(team_id: str, trial_id: str) -> str:
    """A batch request id (≤64 chars, [A-Za-z0-9_-]) for one lab's trial."""
    return hashlib.sha256(f"{team_id}:{trial_id}".encode()).hexdigest()[:40]


def _rows(svc, status: str) -> list[dict[str, Any]]:
    return (
        svc.table("trial_facts")
        .select(
            "team_id, trial_id, extraction_attempts, extraction_batch_id, "
            "extraction_batch_sources, extraction_queued_at"
        )
        .eq("extraction_status", status)
        .order("extraction_queued_at")
        .execute()
        .data
        or []
    )


def _retry_or_fail(svc, row: dict[str, Any], reason: str) -> None:
    if row["extraction_attempts"] < MAX_ATTEMPTS:
        te.update_facts(
            svc,
            row["team_id"],
            row["trial_id"],
            {"extraction_status": "queued", "extraction_batch_id": None},
        )
    else:
        te.update_facts(
            svc,
            row["team_id"],
            row["trial_id"],
            {
                "extraction_status": "failed",
                "extraction_error": reason,
                "extraction_batch_id": None,
            },
        )


def collect(svc, client) -> int:
    """Store the results of ended batches. Returns how many were stored."""
    batched = _rows(svc, "batched")
    by_batch: dict[str, dict[str, dict[str, Any]]] = {}
    for row in batched:
        by_batch.setdefault(row["extraction_batch_id"], {})[
            custom_id(row["team_id"], row["trial_id"])
        ] = row
    stored = 0
    for batch_id, rows in by_batch.items():
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            created = getattr(batch, "created_at", None)
            if created and datetime.now(UTC) - created > STUCK:
                for row in rows.values():
                    _retry_or_fail(svc, row, "The batch never finished. Try again.")
            continue
        for item in client.messages.batches.results(batch_id):
            row = rows.pop(item.custom_id, None)
            if row is None:
                continue  # removed from the lab meanwhile
            if item.result.type != "succeeded":
                _retry_or_fail(svc, row, f"The batch request {item.result.type}. Try again.")
                continue
            msg = item.result.message
            usd = round(te._cost(msg.usage) * BATCH_DISCOUNT, 4)
            te.record_spend(svc, row["team_id"], row["trial_id"], usd, msg.model, "batch")
            result, _call, why = te.answer(msg)
            if result is None:
                _retry_or_fail(svc, row, why or "Claude's answer was unusable.")
                continue
            # The files as the request read them, so "Doc 2" stays the second.
            sources = [{"id": i} for i in row.get("extraction_batch_sources") or []]
            te.store(svc, row["team_id"], row["trial_id"], result, msg.model, usd, sources, "batch")
            stored += 1
        # Requests with no result at all (shouldn't happen): try again.
        for row in rows.values():
            _retry_or_fail(svc, row, "The batch lost this request. Try again.")
    return stored


def submit(svc, client) -> int:
    """Send queued trials as one batch. Returns how many were sent."""
    active = active_teams()
    queued = [r for r in _rows(svc, "queued") if r["team_id"] in active][:MAX_PER_BATCH]
    requests: list[dict[str, Any]] = []
    sent: list[dict[str, Any]] = []
    budget_note: dict[str, str | None] = {}
    for row in queued:
        team, trial = row["team_id"], row["trial_id"]
        if team not in budget_note:
            budget_note[team] = te.over_budget(svc, team)
        if budget_note[team]:
            # Stays queued; goes out when the month turns.
            te.update_facts(svc, team, trial, {"extraction_error": budget_note[team]})
            continue
        try:
            sources, registry, blocks, listing = te.load(svc, team, trial)
        except te.ExtractionError as exc:
            te.update_facts(
                svc, team, trial, {"extraction_status": "failed", "extraction_error": str(exc)}
            )
            continue
        requests.append(
            {"custom_id": custom_id(team, trial), "params": te.request(registry, blocks, listing)}
        )
        sent.append({**row, "sources": [src["id"] for src in sources]})
    if not requests:
        return 0
    batch = client.messages.batches.create(requests=requests)
    for row in sent:
        te.update_facts(
            svc,
            row["team_id"],
            row["trial_id"],
            {
                "extraction_status": "batched",
                "extraction_batch_id": batch.id,
                "extraction_batch_sources": row["sources"],
                "extraction_attempts": row["extraction_attempts"] + 1,
                "extraction_error": None,
            },
        )
    log.info("sent %d extractions in batch %s", len(sent), batch.id)
    return len(sent)


def run() -> tuple[int, int]:
    svc = service_client()
    client = te.client()
    return collect(svc, client), submit(svc, client)


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stored, sent = run()
    print(f"{stored} extractions stored, {sent} sent")


if __name__ == "__main__":
    main()
