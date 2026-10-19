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

from paper_radar.ingest.urls import _normalize_key
from paper_radar.trials import FEATURE, cited, ctgov, jats, pubmed
from paper_radar.trials.extraction import clean_anchor, clean_quote

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
        background.add_task(trial_links.link_lab, req.team_id, trial["id"])
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
    closed: list[str]  # no free full text: a PDF to upload
    have: list[str]
    unconfirmed: list[str] = []  # suggested links, left out until confirmed


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


class StartExtraction(BaseModel):
    team_id: str
    # "batch": queued, half price, within hours. "now": full price, a minute.
    mode: str = Field(default="batch", pattern="^(batch|now)$")


@router.post("/{trial_id}/extract", response_model=ExtractStarted, status_code=202)
def start_extraction(
    trial_id: str,
    req: StartExtraction,
    background: BackgroundTasks,
    token: str = Depends(require_token),
) -> ExtractStarted:
    """Have Claude extract the trial's data from its sources: queued for the
    next batch, or now. The trial page follows trial_facts.extraction_status."""
    user_id = _require_lab_trial(token, req.team_id, trial_id)
    _extract_limiter.check(user_id)
    if req.mode == "batch":
        if not trial_extract.queue(req.team_id, trial_id):
            raise HTTPException(status_code=409, detail="It's already queued or running.")
        return ExtractStarted(status="queued")
    reason = trial_extract.over_budget(service_client(), req.team_id)
    if reason:
        raise HTTPException(status_code=402, detail=reason)
    if not trial_extract.claim(req.team_id, trial_id):
        raise HTTPException(status_code=409, detail="An extraction is already running.")
    background.add_task(trial_extract.run, req.team_id, trial_id)
    return ExtractStarted(status="running")


# One click gets data for a whole collection, so it has its own cap rather
# than spending the per-trial ones.
_get_data_limiter = PerUserRateLimiter(
    10, 3600.0, lambda: HTTPException(status_code=429, detail="Too many requests. Try again later.")
)


class GetData(BaseModel):
    team_id: str
    trial_ids: list[str] = Field(min_length=1, max_length=trial_extract.MAX_GET_DATA)


class GotData(BaseModel):
    queued: list[str]
    need_pdf: list[str]  # no files and no free full text
    unconfirmed: list[str] = []  # only suggested papers: confirm one first
    skipped: list[str]  # had data, or already on the way


@router.post("/get-data", response_model=GotData)
def get_data(req: GetData, token: str = Depends(require_token)) -> GotData:
    """For the trials without data among these (a collection's): fetch their
    open-access full text and queue them for the next batch, in one request."""
    user_id = _require_feature(token, req.team_id)
    _get_data_limiter.check(user_id)
    ids = list(dict.fromkeys(req.trial_ids))
    on_list = {
        r["trial_id"]
        for r in user_client(token)
        .table("trial_posts")
        .select("trial_id")
        .eq("team_id", req.team_id)
        .in_("trial_id", ids)
        .execute()
        .data
        or []
    }
    if on_list != set(ids):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    # The batch checks the cap again before sending; asked here too so a lab
    # at its cap hears so now, not hours later on each trial's page.
    reason = trial_extract.over_budget(service_client(), req.team_id)
    if reason:
        raise HTTPException(status_code=402, detail=reason)
    return GotData(**trial_extract.get_data(req.team_id, ids))


# --- what a source points at ------------------------------------------------------------


class CitedOut(BaseModel):
    parts: list[cited.Citation]
    # The article on PMC, to open in full; each element's id is its anchor there.
    article_url: str | None
    # Whether the source's quote is in what's shown (None: it has no quote).
    quote_found: bool | None = None


@router.get("/{trial_id}/sources/{source_id}/cited", response_model=CitedOut)
def source_cited(
    trial_id: str,
    source_id: str,
    team_id: str,
    where: str = Query(default="", max_length=500),
    anchor: str | None = None,
    quote: str | None = None,
    token: str = Depends(require_token),
) -> CitedOut:
    """The tables, figures and sections an extracted value's source names
    ("Results (Patient disposition); Table 1"), from one of the trial's
    full-text (JATS) files, ready to show beside the value."""
    _require_lab_trial(token, team_id, trial_id)
    rows = (
        user_client(token)
        .table("trial_sources")
        .select("storage_path, media_type")
        .eq("id", source_id)
        .eq("team_id", team_id)
        .eq("trial_id", trial_id)
        .execute()
        .data
    )
    if not rows or rows[0]["media_type"] != "application/xml":
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    bucket = service_client().storage.from_(trial_extract.BUCKET)
    try:
        xml = bucket.download(rows[0]["storage_path"])
    except Exception as exc:  # gone from storage, or storage is down
        log.warning("Couldn't read trial source %s: %s", source_id, exc)
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc
    try:
        article = cited.Article(xml)
    except jats.NotJats as exc:
        # 415, not 422: a 422 is also FastAPI's answer to a malformed request.
        detail = "That file can't be read as an article."
        raise HTTPException(status_code=415, detail=detail) from exc
    # Anchor and quote only help find the value: an odd one is ignored, not refused.
    anchor, quote = clean_anchor(anchor), clean_quote(quote)
    parts = article.cite_all(where, anchor, quote)
    pmcid = article.pmcid
    return CitedOut(
        parts=parts,
        article_url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else None,
        # Found where the source said, not elsewhere; None when there's no quote to find.
        quote_found=(
            any(p.quote and not p.elsewhere for p in parts) if cited.quote_pattern(quote) else None
        ),
    )


# --- PubMed (PR 6) -----------------------------------------------------------------


class PubMedPaperOut(BaseModel):
    pmid: str
    title: str
    journal: str | None
    year: str | None
    doi: str | None


class PubMedHint(BaseModel):
    count: int
    checked: int  # how many of `count` were compared with the library
    not_in_lab: list[PubMedPaperOut]
    search_url: str


# PubMed's own budget, so checking papers doesn't eat the open-access one.
_pubmed_limiter = PerUserRateLimiter(
    30,
    3600.0,
    lambda: HTTPException(status_code=429, detail="Too many PubMed lookups. Try again later."),
)


@router.get("/{trial_id}/pubmed", response_model=PubMedHint)
def pubmed_hint(trial_id: str, team_id: str, token: str = Depends(require_token)) -> PubMedHint:
    """Papers on PubMed that name this trial and aren't in the lab's library."""
    user_id = _require_lab_trial(token, team_id, trial_id)
    _pubmed_limiter.check(user_id)
    rows = service_client().table("trials").select("nct_id").eq("id", trial_id).execute().data
    nct = rows[0]["nct_id"]
    try:
        count, papers = pubmed.papers_naming(nct)
    except pubmed.PubMedError as exc:
        raise HTTPException(status_code=503, detail="PubMed is unreachable.") from exc
    # Held by DOI, or by its PubMed page (papers added from PubMed without one).
    dois = sorted({p.doi for p in papers if p.doi})
    pages = {_normalize_key(f"https://pubmed.ncbi.nlm.nih.gov/{p.pmid}/"): p.pmid for p in papers}
    held_dois: set[str] = set()
    held_pmids: set[str] = set()
    uc = user_client(token)
    if dois:
        for r in (
            uc.table("paper_posts")
            .select("papers!inner(doi)")
            .eq("team_id", team_id)
            .in_("papers.doi", dois)
            .execute()
            .data
            or []
        ):
            held_dois.add((r["papers"]["doi"] or "").lower())
    for r in (
        uc.table("paper_posts")
        .select("papers!inner(url_norm)")
        .eq("team_id", team_id)
        .in_("papers.url_norm", sorted(pages))
        .execute()
        .data
        or []
    ):
        held_pmids.add(pages.get(r["papers"]["url_norm"], ""))
    return PubMedHint(
        count=count,
        checked=len(papers),
        not_in_lab=[
            PubMedPaperOut(**vars(p))
            for p in papers
            if not ((p.doi and p.doi in held_dois) or p.pmid in held_pmids)
        ],
        search_url=f"https://pubmed.ncbi.nlm.nih.gov/?term={nct}%5Bsi%5D",
    )


# --- extraction budget (PR 7) ---------------------------------------------------------


class Budget(BaseModel):
    spent_usd: float
    cap_usd: float


@router.get("/budget", response_model=Budget)
def extraction_budget(team_id: str, token: str = Depends(require_token)) -> Budget:
    """What the lab's extractions cost this month, and its monthly cap."""
    _require_feature(token, team_id)
    return Budget(
        spent_usd=round(trial_extract.spent_this_month(service_client(), team_id), 2),
        cap_usd=trial_extract.monthly_cap(),
    )
