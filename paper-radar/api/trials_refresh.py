"""Keep the lab's trials in step with ClinicalTrials.gov (daily).

For every trial on an active lab's list, fetch the record; when the registry's
last-update date has moved, store the new record and tell each lab that holds
the trial what changed (public.trial_events: registry_updated, status_changed,
results_posted). Only labs with the clinical trials feature on are looked at.

    python -m api.trials_refresh
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from paper_radar.trials import ctgov

from .supa import service_client
from .trial_links import active_teams, upsert_trial

log = logging.getLogger(__name__)


def _lab_trials(svc, teams: set[str]) -> dict[str, dict[str, Any]]:
    """{trial_id: {nct_id, status, has_results, registry_updated_at, teams}}."""
    rows = (
        svc.table("trial_posts")
        .select("team_id, trials(id, nct_id, status, has_results, registry_updated_at)")
        .in_("team_id", sorted(teams))
        .execute()
        .data
        or []
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = r.get("trials")
        if not t:
            continue
        entry = out.setdefault(t["id"], {**t, "teams": []})
        entry["teams"].append(r["team_id"])
    return out


def changes(old: dict[str, Any], rec: ctgov.TrialRecord) -> list[tuple[str, dict[str, Any]]]:
    """The events a new record means, compared with what Atlas had."""
    if rec.registry_updated_at is None or rec.registry_updated_at == old.get("registry_updated_at"):
        return []
    events: list[tuple[str, dict[str, Any]]] = []
    if rec.has_results and not old.get("has_results"):
        events.append(("results_posted", {}))
    if rec.status != old.get("status"):
        events.append(("status_changed", {"from": old.get("status"), "to": rec.status}))
    if not events:
        events.append(("registry_updated", {"date": rec.registry_updated_at}))
    return events


def run() -> int:
    """Returns how many trials changed."""
    teams = active_teams()
    if not teams:
        return 0
    svc = service_client()
    trials = _lab_trials(svc, teams)
    changed = 0
    for trial_id, old in trials.items():
        try:
            rec = ctgov.fetch(old["nct_id"])
        except ctgov.RegistryError as exc:
            # Down for one is down for all: stop rather than wait on each.
            log.warning("ClinicalTrials.gov failed on %s; stopping: %s", old["nct_id"], exc)
            raise SystemExit(f"ClinicalTrials.gov failed: {exc}") from exc
        if rec is None:
            continue
        events = changes(old, rec)
        if not events:
            continue
        upsert_trial(svc, rec)
        svc.table("trial_events").insert(
            [
                {"team_id": team, "trial_id": trial_id, "kind": kind, "detail": detail}
                for team in old["teams"]
                for kind, detail in events
            ]
        ).execute()
        changed += 1
        log.info("%s: %s", old["nct_id"], ", ".join(k for k, _ in events))
    return changed


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"{run()} trials changed on ClinicalTrials.gov")


if __name__ == "__main__":
    main()
