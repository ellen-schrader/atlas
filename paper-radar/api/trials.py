"""Clinical trials endpoints (PR 1: find a trial and add it to the lab).

Reading a lab's trials and links, linking a paper by hand, confirming or
rejecting a suggested link and removing a trial all go straight to Supabase
from the web app, where RLS checks the lab and the feature switch. This router
holds only what needs the server: calls to ClinicalTrials.gov and writes to the
shared `trials` table.

Every endpoint answers 404 unless the clinical trials feature is on for the
caller in that lab, so the feature isn't advertised while it is dark.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from paper_radar.trials import FEATURE, ctgov

from . import trial_extract, trial_links
from .deps import require_token
from .ratelimit import PerUserRateLimiter
from .supa import get_user_id, service_client, user_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/trials", tags=["trials"])

_NOT_FOUND = "Not Found"  # FastAPI's own wording for an unknown route
_TRIAL_COLUMNS = (
    "id, nct_id, acronym, title, phases, status, sponsor, conditions, enrollment, "
    "start_date, completion_date, has_results, registry_updated_at, breast_cancer"
)


def _require_feature(token: str, team_id: str) -> str:
    """The caller's id, or 404 unless the feature is on for them in this lab.
    Asked as the caller, so has_feature() checks membership too."""
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    ok = user_client(token).rpc("has_feature", {"t": team_id, "f": FEATURE}).execute().data
    if ok is not True:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return user_id


def _limit(user_id: str) -> None:
    """Each call reaches ClinicalTrials.gov: share the paper resolver's budget."""
    from .app import _resolve_limiter  # lazy: app imports this module

    _resolve_limiter.check(user_id)


class TrialHit(BaseModel):
    nct_id: str
    title: str
    acronym: str | None
    phases: list[str]
    status: str | None
    conditions: list[str]
    in_lab: bool = False


@router.get("/search", response_model=list[TrialHit])
def search_trials(
    team_id: str,
    q: str = Query(min_length=2, max_length=200),
    token: str = Depends(require_token),
) -> list[TrialHit]:
    """Breast cancer trials on ClinicalTrials.gov matching an NCT ID, a trial
    name or free text, marked if the lab already holds them."""
    user_id = _require_feature(token, team_id)
    _limit(user_id)
    try:
        hits = ctgov.search(q)
    except ctgov.RegistryError as exc:
        raise HTTPException(status_code=503, detail="ClinicalTrials.gov is unreachable.") from exc
    held = _held_ncts(token, team_id, [h.nct_id for h in hits])
    return [TrialHit(**vars(h), in_lab=h.nct_id in held) for h in hits]


def _held_ncts(token: str, team_id: str, ncts: list[str]) -> set[str]:
    if not ncts:
        return set()
    rows = (
        user_client(token)
        .table("trial_posts")
        .select("trials!inner(nct_id)")
        .eq("team_id", team_id)
        .in_("trials.nct_id", ncts)
        .execute()
        .data
        or []
    )
    return {r["trials"]["nct_id"] for r in rows if r.get("trials")}


class AddTrial(BaseModel):
    team_id: str
    nct_id: str = Field(min_length=11, max_length=20)


class AddedTrial(BaseModel):
    trial: dict[str, Any]
    already_in_lab: bool


@router.post("", response_model=AddedTrial)
def add_trial(
    req: AddTrial, background: BackgroundTasks, token: str = Depends(require_token)
) -> AddedTrial:
    """Add a trial to the lab by NCT ID, fetching it from the registry if Atlas
    doesn't have it yet, then look for lab papers that report it."""
    user_id = _require_feature(token, req.team_id)
    nct = ctgov.normalise_nct(req.nct_id)
    if not nct:
        raise HTTPException(
            status_code=400, detail="That isn't an NCT ID (NCT followed by 8 digits)."
        )

    svc = service_client()
    rows = svc.table("trials").select(_TRIAL_COLUMNS).eq("nct_id", nct).execute().data
    if rows:
        trial = rows[0]
        if not trial["breast_cancer"]:
            raise HTTPException(
                status_code=422, detail="Atlas covers breast cancer trials for now."
            )
    else:
        _limit(user_id)
        try:
            rec = ctgov.fetch(nct)
        except ctgov.RegistryError as exc:
            raise HTTPException(
                status_code=503, detail="ClinicalTrials.gov is unreachable."
            ) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail=f"{nct} isn't on ClinicalTrials.gov.")
        if not rec.is_breast_cancer:
            raise HTTPException(
                status_code=422, detail="Atlas covers breast cancer trials for now."
            )
        trial_links.upsert_trial(svc, rec)
        trial = svc.table("trials").select(_TRIAL_COLUMNS).eq("nct_id", nct).execute().data[0]

    # As the caller, so RLS checks the lab and the switch once more.
    inserted = (
        user_client(token)
        .table("trial_posts")
        .upsert(
            {
                "trial_id": trial["id"],
                "team_id": req.team_id,
                "added_by": user_id,
                "source": "manual",
            },
            on_conflict="trial_id,team_id",
            ignore_duplicates=True,
        )
        .execute()
        .data
    )
    already = not inserted
    if not already:
        background.add_task(trial_links.link_lab, req.team_id)
    return AddedTrial(trial=trial, already_in_lab=already)


# --- sources and extraction (PR 4) -------------------------------------------------

# Both reach outside and the second costs money: their own caps, per person.
_open_access_limiter = PerUserRateLimiter(
    20, 3600.0, lambda: HTTPException(status_code=429, detail="Too many lookups. Try again later.")
)
_extract_limiter = PerUserRateLimiter(
    6, 3600.0, lambda: HTTPException(status_code=429, detail="Six extractions an hour at most.")
)


class TeamOnly(BaseModel):
    team_id: str


def _require_lab_trial(token: str, team_id: str, trial_id: str) -> str:
    """The caller's id, or 404 unless the feature is on and the trial is on the
    lab's list (asked as the caller, so RLS answers)."""
    user_id = _require_feature(token, team_id)
    rows = (
        user_client(token)
        .table("trial_posts")
        .select("trial_id")
        .eq("team_id", team_id)
        .eq("trial_id", trial_id)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return user_id


class OpenAccessResult(BaseModel):
    fetched: list[str]
    closed: list[str]
    have: list[str]


@router.post("/{trial_id}/open-access", response_model=OpenAccessResult)
def fetch_open_access(
    trial_id: str, req: TeamOnly, token: str = Depends(require_token)
) -> OpenAccessResult:
    """Fetch the open-access full text of the lab papers linked to this trial
    from Europe PMC and keep it as the trial's sources."""
    user_id = _require_lab_trial(token, req.team_id, trial_id)
    _open_access_limiter.check(user_id)
    return OpenAccessResult(**trial_extract.fetch_open_access(req.team_id, trial_id))


class ExtractStarted(BaseModel):
    status: str


@router.post("/{trial_id}/extract", response_model=ExtractStarted, status_code=202)
def start_extraction(
    trial_id: str,
    req: TeamOnly,
    background: BackgroundTasks,
    token: str = Depends(require_token),
) -> ExtractStarted:
    """Have Claude extract the trial's data from its sources. Runs in the
    background; the trial page follows trial_facts.extraction_status."""
    user_id = _require_lab_trial(token, req.team_id, trial_id)
    _extract_limiter.check(user_id)
    if not trial_extract.claim(req.team_id, trial_id):
        raise HTTPException(status_code=409, detail="An extraction is already running.")
    background.add_task(trial_extract.run, req.team_id, trial_id)
    return ExtractStarted(status="running")
