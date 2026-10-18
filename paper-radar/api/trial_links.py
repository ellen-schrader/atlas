"""Link a lab's papers to the trials they report (service role).

Two kinds of link (public.paper_trials):
  * 'auto': the paper's abstract or title names the trial's NCT ID. Shown as
    linked. If the lab doesn't hold that trial yet and it is a breast cancer
    trial, it is added to the lab's list (source 'paper').
  * 'suggested': the trial's short name appears in the paper's title. Waits for
    a person to confirm or reject it.

A link a person has already decided on is never touched again. Everything here
runs only for labs where the clinical trials feature is on (for the lab or for
one of its members), so other labs' papers are never scanned.

Run on its own to catch up (abstracts that arrived later, papers added before
the feature was on):  python -m api.trial_links
"""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Iterable
from typing import Any

from paper_radar.trials import FEATURE, ctgov

from . import trial_classify
from .merge_suggestions import lab_papers
from .supa import service_client

log = logging.getLogger(__name__)

_MIN_ACRONYM = 4  # shorter names ("BEST", "ACE" aside) match too much


def active_teams() -> set[str]:
    rows = service_client().rpc("feature_teams", {"f": FEATURE}).execute().data or []
    # A set-returning function comes back as bare values or as {"feature_teams": v}.
    return {r if isinstance(r, str) else r.get("feature_teams") for r in rows} - {None}


def team_active(team_id: str) -> bool:
    return team_id in active_teams()


def acronym_pattern(acronym: str | None) -> re.Pattern[str] | None:
    """A whole-word matcher for a trial's short name, or None if it's too short
    to trust. All-letter names ("ASCENT", "OlympiA") match case-sensitively, so
    an ordinary word in a title isn't taken for a trial."""
    name = (acronym or "").strip()
    if len(name) < _MIN_ACRONYM:
        return None
    flags = 0 if name.isalpha() else re.IGNORECASE
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", flags)


def _lab_trials(svc, team_id: str) -> dict[str, dict[str, Any]]:
    """The lab's trials by NCT ID: {nct_id: {id, acronym}}."""
    rows = (
        svc.table("trial_posts")
        .select("trial_id, trials(id, nct_id, acronym)")
        .eq("team_id", team_id)
        .execute()
        .data
        or []
    )
    return {r["trials"]["nct_id"]: r["trials"] for r in rows if r.get("trials")}


def _decided(svc, team_id: str, paper_ids: list[str]) -> set[tuple[str, str]]:
    """(paper_id, trial_id) pairs the lab already has any link for."""
    have: set[tuple[str, str]] = set()
    for i in range(0, len(paper_ids), 100):
        rows = (
            svc.table("paper_trials")
            .select("paper_id, trial_id")
            .eq("team_id", team_id)
            .in_("paper_id", paper_ids[i : i + 100])
            .execute()
            .data
            or []
        )
        have.update((r["paper_id"], r["trial_id"]) for r in rows)
    return have


def _removed(svc, team_id: str) -> set[str]:
    """Trials a member took off the lab's list: never added back automatically,
    and no new links to them (public.trial_removals)."""
    rows = svc.table("trial_removals").select("trial_id").eq("team_id", team_id).execute().data
    return {r["trial_id"] for r in rows or []}


class Lookup:
    """Registry answers for one run, so an NCT ID is looked up once however many
    papers name it. Once the registry fails, the rest of the run doesn't ask
    again: each attempt could wait out the full timeout."""

    def __init__(self) -> None:
        self.answers: dict[str, str | None] = {}
        self.down = False


def ensure_trial(svc, nct_id: str, lookup: Lookup) -> str | None:
    """The trials.id for `nct_id` if it is a breast cancer trial, fetching it
    from the registry if Atlas doesn't have it yet. None if there's no such
    trial, it isn't breast cancer, or the registry is down (the next run tries
    again)."""
    if nct_id in lookup.answers:
        return lookup.answers[nct_id]
    rows = svc.table("trials").select("id, breast_cancer").eq("nct_id", nct_id).execute().data
    if rows:
        found = rows[0]["id"] if rows[0]["breast_cancer"] else None
    else:
        if lookup.down:
            return None
        try:
            rec = ctgov.fetch(nct_id)
        except ctgov.RegistryError as exc:
            log.warning(
                "ClinicalTrials.gov failed on %s; skipping lookups this run: %s", nct_id, exc
            )
            lookup.down = True
            return None
        # Stored even when it isn't breast cancer, so it isn't fetched again on
        # every run. Only a lab's list makes a trial visible, and only breast
        # cancer trials go on one.
        trial_id = upsert_trial(svc, rec) if rec else None
        found = trial_id if rec and rec.is_breast_cancer else None
    lookup.answers[nct_id] = found
    return found


def upsert_trial(svc, rec: ctgov.TrialRecord) -> str:
    """Store a registry record (insert or refresh) and return its id."""
    rows = svc.table("trials").upsert(rec.row(), on_conflict="nct_id").execute().data
    return rows[0]["id"]


def link_papers(
    team_id: str,
    papers: Iterable[dict[str, Any]],
    *,
    lookup: Lookup | None = None,
) -> int:
    """Link these lab papers ({id, title, abstract}) to trials. Returns the
    number of new links."""
    svc = service_client()
    papers = [p for p in papers if p.get("id")]
    if not papers:
        return 0
    lookup = lookup or Lookup()
    trials = _lab_trials(svc, team_id)
    removed = _removed(svc, team_id)
    have = _decided(svc, team_id, [p["id"] for p in papers])
    posted: set[str] = {t["id"] for t in trials.values()}
    patterns = [(t["id"], acronym_pattern(t.get("acronym"))) for t in trials.values()]

    new_links: dict[tuple[str, str], dict[str, Any]] = {}
    for p in papers:
        text = f"{p.get('title') or ''}\n{p.get('abstract') or ''}"
        for nct in ctgov.find_nct_ids(text):
            trial_id = trials[nct]["id"] if nct in trials else ensure_trial(svc, nct, lookup)
            if not trial_id or trial_id in removed:
                continue
            if trial_id not in posted:
                svc.table("trial_posts").upsert(
                    {"trial_id": trial_id, "team_id": team_id, "source": "paper"},
                    on_conflict="trial_id,team_id",
                    ignore_duplicates=True,
                ).execute()
                posted.add(trial_id)
            key = (p["id"], trial_id)
            if key not in have:
                new_links[key] = {"source": "nct_in_abstract", "status": "auto"}
        for trial_id, pattern in patterns:
            key = (p["id"], trial_id)
            if (
                pattern
                and key not in have
                and key not in new_links
                and pattern.search(p.get("title") or "")
            ):
                new_links[key] = {"source": "acronym_in_title", "status": "suggested"}

    if not new_links:
        return 0
    svc.table("paper_trials").upsert(
        [
            {"team_id": team_id, "paper_id": paper_id, "trial_id": trial_id, **link}
            for (paper_id, trial_id), link in new_links.items()
        ],
        on_conflict="team_id,paper_id,trial_id",
        ignore_duplicates=True,
    ).execute()
    return len(new_links)


def link_paper(team_id: str, paper_id: str) -> None:
    """Background task after a paper is posted. Failures are logged; the daily
    run catches up."""
    try:
        if not team_active(team_id):
            return
        rows = (
            service_client()
            .table("papers")
            .select("id, title, abstract")
            .eq("id", paper_id)
            .execute()
            .data
        )
        link_papers(team_id, rows or [])
    except Exception as exc:  # noqa: BLE001 — a background task must not raise
        log.warning("linking paper %s to trials failed: %s", paper_id, exc)
        return
    trial_classify.classify_lab(team_id)  # trials the paper added; never raises


def _lab_papers(svc, team_id: str) -> list[dict[str, Any]]:
    return lab_papers(svc, team_id, columns="id, title, abstract")


def link_lab(team_id: str) -> None:
    """Background task after a trial is added to a lab, or many papers at once
    (a BibTeX import): one pass over all the lab's papers."""
    try:
        if not team_active(team_id):
            return
        link_papers(team_id, _lab_papers(service_client(), team_id))
    except Exception as exc:  # noqa: BLE001 — a background task must not raise
        log.warning("linking lab %s papers to trials failed: %s", team_id, exc)
    trial_classify.classify_lab(team_id)  # never raises


def run() -> int:
    """Every active lab, every paper. Returns the number of new links. A lab
    that fails is logged and skipped; the others still run."""
    svc = service_client()
    lookup = Lookup()
    total = 0
    failed = 0
    for team_id in sorted(active_teams()):
        try:
            n = link_papers(team_id, _lab_papers(svc, team_id), lookup=lookup)
        except Exception as exc:  # noqa: BLE001 — one lab must not stop the rest
            log.warning("lab %s: linking failed: %s", team_id, exc)
            failed += 1
            continue
        classified = trial_classify.classify_lab(team_id)
        log.info("lab %s: %d new trial links, %d trials classified", team_id, n, classified)
        total += n
    if failed:
        raise SystemExit(f"{failed} lab(s) failed; see the log")
    return total


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"{run()} new trial links")


if __name__ == "__main__":
    main()
