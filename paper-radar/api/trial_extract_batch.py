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
import base64
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from . import trial_extract as te
from .supa import service_client
from .trial_links import active_teams

log = logging.getLogger(__name__)

MAX_PER_BATCH = 50
MAX_BATCH_BYTES = 200_000_000  # the API takes 256 MB per batch
MAX_ATTEMPTS = 2  # a failed or unusable answer is tried once more
BATCH_DISCOUNT = 0.5
STUCK = timedelta(hours=30)  # batches end within 24 h; past this, ask again
SETTLE = timedelta(minutes=30)  # a just-queued trial may be getting more files


def custom_id(team_id: str, trial_id: str) -> str:
    """A batch request id (≤64 chars, [A-Za-z0-9_-]) for one lab's trial."""
    return hashlib.sha256(f"{team_id}:{trial_id}".encode()).hexdigest()[:40]


def _rows(svc, status: str) -> list[dict[str, Any]]:
    return (
        svc.table("trial_facts")
        .select(
            "team_id, trial_id, extraction_attempts, extraction_batch_id, "
            "extraction_batch_sources, extraction_queued_at, extraction_estimate_usd"
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
        try:
            stored += _collect_one(svc, client, batch_id, rows)
        except Exception as exc:  # noqa: BLE001 — one batch must not stop the rest
            log.warning("collecting batch %s failed: %s", batch_id, exc)
    return stored


def _collect_one(svc, client, batch_id: str, rows: dict[str, dict[str, Any]]) -> int:
    """Store one batch's results once it has ended. Returns how many."""
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        created = getattr(batch, "created_at", None)
        if created and datetime.now(UTC) - created > STUCK:
            for row in rows.values():
                _retry_or_fail(svc, row, "The batch never finished. Try again.")
        return 0
    stored = 0
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


def estimate_usd(params: dict[str, Any]) -> float:
    """A cautious guess of a batch request's cost, before it runs: text at
    ~3.5 characters a token, a PDF page at ~3,000 tokens, ~10k tokens out."""
    tokens = 0.0
    for block in params["messages"][0]["content"]:
        src = block.get("source") or {}
        if src.get("type") == "text":
            tokens += len(src["data"]) / 3.5
        elif src.get("type") == "base64":
            pages = max(1, base64.b64decode(src["data"]).count(b"/Type /Page") - 1)
            tokens += pages * 3000
        elif block.get("type") == "text":
            tokens += len(block["text"]) / 3.5
    usd = tokens / 1e6 * te._PRICE_IN + 10_000 / 1e6 * te._PRICE_OUT
    return round(usd * BATCH_DISCOUNT, 4)


def _committed(svc, team_id: str) -> float:
    """Estimated cost of the lab's requests sent but not collected yet."""
    rows = (
        svc.table("trial_facts")
        .select("extraction_estimate_usd")
        .eq("team_id", team_id)
        .eq("extraction_status", "batched")
        .execute()
        .data
        or []
    )
    return sum(float(r["extraction_estimate_usd"] or 0) for r in rows)


def submit(svc, client) -> int:
    """Send queued trials as one batch. Returns how many were sent.

    Each lab spends at most what's left of its month: what it has spent, plus
    the estimates of what's still out, plus this batch's estimates. A lab over
    budget doesn't take places from the others, and a trial that can't be
    read fails alone.
    """
    active = active_teams()
    settled = datetime.now(UTC) - SETTLE
    queued = [
        r
        for r in _rows(svc, "queued")
        if r["team_id"] in active
        and (
            not r["extraction_queued_at"]
            or datetime.fromisoformat(r["extraction_queued_at"]) < settled
        )
    ]
    requests: list[dict[str, Any]] = []
    sent: list[dict[str, Any]] = []
    left: dict[str, float] = {}
    size = 0
    for row in queued:
        if len(requests) >= MAX_PER_BATCH:
            break
        team, trial = row["team_id"], row["trial_id"]
        if team not in left:
            left[team] = te.monthly_cap() - te.spent_this_month(svc, team) - _committed(svc, team)
        if left[team] <= 0:
            # Stays queued; goes out when the month turns.
            te.update_facts(svc, team, trial, {"extraction_error": te.budget_message()})
            continue
        try:
            sources, registry, blocks, listing = te.load(svc, team, trial)
            params = te.request(registry, blocks, listing)
            estimate = estimate_usd(params)
            weight = len(json.dumps(params))
        except te.ExtractionError as exc:
            te.update_facts(
                svc, team, trial, {"extraction_status": "failed", "extraction_error": str(exc)}
            )
            continue
        except Exception as exc:  # noqa: BLE001 — one trial must not stop the rest
            log.warning("preparing trial %s for extraction failed: %s", trial, exc)
            te.update_facts(
                svc,
                team,
                trial,
                {
                    "extraction_status": "failed",
                    "extraction_error": "Couldn't read the sources. Try again.",
                },
            )
            continue
        if estimate > left[team]:
            te.update_facts(svc, team, trial, {"extraction_error": te.budget_message()})
            continue
        if size + weight > MAX_BATCH_BYTES:
            break  # the rest go in the next run
        left[team] -= estimate
        size += weight
        requests.append({"custom_id": custom_id(team, trial), "params": params})
        sent.append({**row, "sources": [src["id"] for src in sources], "estimate": estimate})
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
                "extraction_estimate_usd": row["estimate"],
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
