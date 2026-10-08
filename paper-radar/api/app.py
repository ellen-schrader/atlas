"""Atlas API.

A thin FastAPI service in front of the existing ``paper_radar`` ingest logic.

  * ``POST /resolve``         — URL → metadata + dedup key (no writes).
  * ``POST /posts``           — post a paper into a lab: verify the caller's
    Supabase JWT, upsert the global ``papers`` row (service role, dedup on
    DOI/url_norm), insert the ``paper_post`` as that user so RLS enforces
    membership, and embed the paper in the background.
  * ``POST /search/semantic`` — embed a query and rank the lab's posts by
    cosine similarity (``match_papers`` RPC, caller's RLS).
  * ``GET  /overview``        — 2-D t-SNE layout + clusters of the lab's papers.

Enrichment (summary/tags) still lands later in a worker.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StringConstraints

from paper_radar.ingest import bibtex as bib
from paper_radar.ingest import url_guard
from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.urls import _clean_url, _normalize_key, coerce_fetch_url, norm_doi

from . import embeddings, enrichment, integrations, maps, teams_integration
from . import map_summary as map_summary_mod
from . import overview as overview_mod
from .backfill_metadata import _doi_owner, follow_year, plan_update
from .config import get_api_settings
from .deps import require_token
from .supa import get_user_id, service_client, user_client

# Uvicorn configures only its own loggers, so without a root handler the app's
# INFO-level diagnostics (inbound webhook traces, import skips) never reach the
# container logs — Python's last-resort handler emits WARNING and above only.
# basicConfig is a no-op when a root handler already exists (e.g. under pytest).
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")
# One line per Supabase round-trip is noise, not signal, at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

app = FastAPI(title="Atlas API", version="0.1.0")

# The Vite dev server calls this cross-origin. Origins are configurable
# (CORS_ORIGINS, comma-separated) so dev on an alternate port and the deployed
# frontend host (plan §12) don't need a code change; defaults to Vite's 5173.
_origins = [
    o.strip() for o in (get_api_settings().cors_origins or "http://localhost:5173").split(",")
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(maps.router)
app.include_router(integrations.router)


# --- schemas ---------------------------------------------------------------


class ResolveRequest(BaseModel):
    url: str
    network: bool = True  # set false in tests to skip all HTTP lookups


class ResolvedPaper(BaseModel):
    """Best-effort metadata for a URL, plus the dedup key used for `papers`."""

    url: str
    url_norm: str
    title: str | None = None
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    abstract: str | None = None
    keywords: list[str] = []
    source: str = "unknown"


# Where a paper's metadata came from. Client-supplied, so it's an enum, not free
# text — `metadata_source` is provenance, and a caller must not be able to write
# "crossref" onto a record it invented.
MetadataSource = Literal[
    "arxiv", "crossref", "pubmed", "europepmc", "citation_meta", "manual", "unknown"
]

# List bounds cap the number of items, not their size — so bound the items too, or a
# single 100MB author name still gets through.
Author = Annotated[str, StringConstraints(max_length=300)]
Keyword = Annotated[str, StringConstraints(max_length=200)]


class PaperFields(BaseModel):
    """Metadata the user has seen and approved in the Add-paper dialog.

    Sent back with the post so the server stores exactly what was on screen. It
    also covers the case the resolver cannot: a bot-walled publisher (Cell,
    ScienceDirect) returns an empty record, and the user types the title and
    authors in by hand.

    Every field is bounded. These land in `papers` verbatim, so without limits one
    member could write an arbitrarily large abstract — the same hazard
    MAX_BIBTEX_BYTES guards on the import path.
    """

    title: str | None = Field(default=None, max_length=2_000)
    authors: list[Author] = Field(default=[], max_length=1_000)
    venue: str | None = Field(default=None, max_length=500)
    # papers.year is int4; an out-of-range value would fail the insert as a 500.
    year: int | None = Field(default=None, ge=1000, le=2200)
    doi: str | None = Field(default=None, max_length=255)
    abstract: str | None = Field(default=None, max_length=100_000)
    keywords: list[Keyword] = Field(default=[], max_length=200)
    # A resolver ("crossref", …) if the user accepted what it found as-is;
    # "manual" if they typed or corrected any of it.
    source: MetadataSource = "manual"


class PostRequest(BaseModel):
    url: str = Field(max_length=2_000)
    team_id: str
    note: str | None = Field(default=None, max_length=5_000)
    # Omitted (the CLI, older clients) => resolve the URL server-side, as before.
    fields: PaperFields | None = None


class PostResponse(BaseModel):
    post_id: str
    paper_id: str
    already_posted: bool
    paper: ResolvedPaper


# Explicit paper columns for hydration — never `papers(*)`, which would drag
# the 1024-dim embedding into every response.
PAPER_COLUMNS = (
    "id, url, doi, title, authors, abstract, venue, year, keywords, tags, "
    "code_url, data_url, enriched_at, edited_by, edited_at, edited_fields"
)
POST_COLUMNS = f"id, posted_at, note, posted_by, posted_by_label, tags, papers({PAPER_COLUMNS})"


class SemanticSearchRequest(BaseModel):
    query: str
    team_id: str
    limit: int = Field(default=20, ge=1, le=50)


class SemanticHit(BaseModel):
    similarity: float
    post: dict  # a paper_posts row with the joined paper (POST_COLUMNS)


class SemanticSearchResponse(BaseModel):
    results: list[SemanticHit]


class OverviewPoint(BaseModel):
    paper_id: str
    x: float
    y: float
    title: str | None = None
    venue: str | None = None
    year: int | None = None
    keywords: list[str] = []
    tags: list[str] = []  # LLM topical tags (papers.tags)
    lab: str | None = None  # last author — proxy for the source lab (§4.1a)
    cluster: int
    reactions: int = 0
    comments: int = 0


class Cluster(BaseModel):
    id: int
    label: str
    description: str = ""
    size: int


class OverviewStats(BaseModel):
    over_time: list[dict]  # [{month: "2026-03", count: N}]
    by_venue: list[dict]  # [{venue, count}] top venues
    by_year: list[dict]  # [{year, count}]
    by_lab: list[dict]  # [{lab, count}] top last-authors (proxy for source lab)
    by_tag: list[dict]  # [{tag, count}] top LLM tags


class OverviewResponse(BaseModel):
    points: list[OverviewPoint]
    clusters: list[Cluster]
    stats: OverviewStats
    total: int  # posts in the lab
    embedded: int  # posts whose paper has an embedding (points returned)


# The token dependency lives in `deps.py` (imported above) so routers can share it
# without importing this module; `require_token` is re-exported here for the many
# endpoints below that depend on it.

# --- rate limiting ---------------------------------------------------------


class _PerUserRateLimiter:
    """Sliding-window cap, keyed by user.

    In-process, so it bounds one worker rather than the fleet — enough to stop a single
    caller looping an endpoint that makes an outbound request every time, which is what
    /resolve does. Multi-process (gunicorn -w N, or several Fly machines) multiplies the
    effective cap by the process count; a fleet-wide limit wants a shared store (Redis).

    FastAPI runs these sync endpoints in a threadpool, so `check` is called from several
    threads at once. Without the lock the read-modify-write races (two callers both see
    room and both append, defeating the cap) and the eviction rebuild can hit
    "dictionary changed size during iteration"; the lock makes each check atomic.
    """

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < self.window]
            if len(events) >= self.max_events:
                raise HTTPException(status_code=429, detail="Too many lookups — give it a minute.")
            events.append(now)
            self._events[key] = events
            # Don't let the map grow without bound as users come and go.
            if len(self._events) > 10_000:
                self._events = {
                    k: v for k, v in self._events.items() if v and now - v[-1] < self.window
                }


# Someone adding papers by hand does a handful a minute. 30 is far above real use and
# far below what would make the endpoint useful as a scanner.
_resolve_limiter = _PerUserRateLimiter(max_events=30, window_seconds=60.0)

# Paid outbound work a caller can trigger repeatedly on a shared key: query
# embeddings (Voyage) and the map summary (Anthropic, heavier). Generous but
# bounded, so one account can't drain the quota/budget for every tenant.
_query_limiter = _PerUserRateLimiter(max_events=40, window_seconds=60.0)
_summary_limiter = _PerUserRateLimiter(max_events=10, window_seconds=60.0)

# Upper bound on the (service-role) similarity scan, so /similarity can't be used
# to force an unbounded cosine scan of a whole team corpus. Covers any real lab.
_SIMILARITY_MAX_PAPERS = 10_000


def _validated_fetch_url(raw: str) -> str:
    """Coerce + clean + SSRF-check a URL we're about to fetch, as a 400 on rejection.

    `coerce_fetch_url` first turns a bare DOI / `doi:` handle / scheme-less link into
    a real https URL — otherwise everything the add-paper box invites besides a full
    URL dies here with "Only http(s) links can be fetched." The guard then runs on
    the coerced form, so this widens what's accepted, not what's fetched.

    `resolve=False` keeps this to the syntactic checks (scheme, literal internal IP,
    internal name) for a fast, clean 400 — the DNS-resolution check runs again inside
    `fetch_metadata` (which every fetch path shares), so a public name pointing at an
    internal address is still caught there without resolving the host twice here.
    """
    try:
        return _clean_url(url_guard.validate_public_url(coerce_fetch_url(raw), resolve=False))
    except url_guard.BlockedUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_DANGEROUS_URL_SCHEMES = {"javascript", "data", "vbscript", "file", "blob"}


def _reject_dangerous_url(raw: str) -> None:
    """Block href-executable schemes before storing a URL the web client renders
    as a link. http/https and scheme-less strings (bare DOIs, hand-typed links)
    pass through so the by-hand post path still works; javascript:/data:/etc. do
    not — defence-in-depth against stored XSS (the client also sanitises hrefs at
    render time via safeHref)."""
    if ":" not in raw:
        return
    head = raw.split(":", 1)[0]
    scheme = "".join(c for c in head if c.isprintable() and not c.isspace()).lower()
    if scheme in _DANGEROUS_URL_SCHEMES:
        raise HTTPException(status_code=400, detail="Unsupported link scheme")


# --- helpers ---------------------------------------------------------------


def _resolved(meta: PaperMetadata, url: str, url_norm: str) -> ResolvedPaper:
    fields = {k: v for k, v in asdict(meta).items() if k != "url"}
    return ResolvedPaper(url=meta.url, url_norm=url_norm, **fields)


def _repair_untitled(row: dict, meta: PaperMetadata) -> bool:
    """Backfill a canonical paper that was stored without a title. Returns True if repaired.

    A bot-walled URL posted before this dialog existed is a row whose title is
    null and which therefore renders as a bare URL everywhere. If someone now
    supplies the title by hand, adopt it — otherwise the manual path would
    silently do nothing for the very papers it exists to fix. Only ever fills a
    blank; it never overwrites metadata a resolver already got right.
    """
    if row.get("title") or not meta.title:
        return False
    # A person has corrected this row's title. It can't be blank in that case
    # (the edit endpoint refuses that), but the hold is the rule, not the blank.
    if "title" in (row.get("edited_fields") or []):
        return False
    patch = {
        "title": meta.title,
        "metadata_source": meta.source,
        # Repairing the title makes the paper embeddable for the first time.
        "embedded_at": None,
    }
    for key in ("authors", "keywords"):
        value = getattr(meta, key)
        if value:
            patch[key] = value
    for key in ("venue", "year", "doi", "abstract"):
        value = getattr(meta, key)
        if value is not None:
            patch[key] = value
    # A row can be untitled and still have hand-corrected fields (the API allows
    # editing venue or year without a title); those are not the resolver's to fill.
    for key in row.get("edited_fields") or []:
        patch.pop(key, None)
    try:
        service_client().table("papers").update(patch).eq("id", row["id"]).execute()
    except Exception as exc:  # a unique-DOI clash shouldn't fail the post
        log.warning("repairing untitled paper %s failed: %s", row["id"], exc)
        return False
    return True


# The folding moved to paper_radar.ingest.urls so every reader and writer of
# papers.doi (this module, the inbound-webhook fast path, the PDF importer)
# shares one normalizer; the old name stays for this module's many call sites.
_norm_doi = norm_doi


def _upsert_paper(meta: PaperMetadata, url: str, url_norm: str) -> tuple[str, bool]:
    """Find the canonical paper (by url_norm, then DOI) or insert it. Service role.

    Returns ``(paper_id, needs_embedding)`` — an existing row may still lack an
    embedding (posted before embeddings landed, or a previous embed failed).
    """
    svc = service_client()

    found = (
        svc.table("papers")
        .select("id, title, embedded_at, edited_fields")
        .eq("url_norm", url_norm)
        .limit(1)
        .execute()
    )
    if found.data:
        row = found.data[0]
        return row["id"], _repair_untitled(row, meta) or row["embedded_at"] is None
    doi = _norm_doi(meta.doi)
    if doi:
        by_doi = (
            svc.table("papers")
            .select("id, title, embedded_at, edited_fields")
            .eq("doi", doi)
            .limit(1)
            .execute()
        )
        if by_doi.data:
            row = by_doi.data[0]
            return row["id"], _repair_untitled(row, meta) or row["embedded_at"] is None

    row = {
        "url": url,
        "url_norm": url_norm,
        "doi": doi,
        "title": meta.title,
        "authors": meta.authors,
        "abstract": meta.abstract,
        "venue": meta.venue,
        "year": meta.year,
        "keywords": meta.keywords,
        "metadata_source": meta.source,
    }
    try:
        inserted = svc.table("papers").insert(row).execute()
        return inserted.data[0]["id"], True
    except Exception:
        # Lost a race on the url_norm unique constraint — re-read the winner.
        again = svc.table("papers").select("id").eq("url_norm", url_norm).limit(1).execute()
        if again.data:
            return again.data[0]["id"], False
        raise


def _embed_and_store(paper_id: str, title: str | None, abstract: str | None) -> None:
    """Background task: embed one paper and store the vector (service role).

    Failures are logged, never raised — the backfill script retries anything
    still missing ``embedded_at``.
    """
    text = embeddings.paper_text(title, abstract)
    if not text:
        return
    try:
        vector = embeddings.embed_texts([text])[0]
        service_client().table("papers").update(
            {"embedding": vector, "embedded_at": datetime.now(UTC).isoformat()}
        ).eq("id", paper_id).is_("embedded_at", "null").execute()
    except Exception as exc:
        log.warning("embedding paper %s failed (backfill will retry): %s", paper_id, exc)


def _enrich_and_store(paper_id: str, title: str | None, abstract: str | None) -> None:
    """Background task: tag one paper and store the tags (service role).

    No-ops without an Anthropic key; failures are logged, not raised — the
    enrichment backfill retries anything still missing ``enriched_at``.
    """
    tags = enrichment.enrich_batch([{"id": paper_id, "title": title, "abstract": abstract}])
    if paper_id not in tags:
        return
    try:
        service_client().table("papers").update(
            {"tags": tags[paper_id], "enriched_at": datetime.now(UTC).isoformat()}
        ).eq("id", paper_id).is_("enriched_at", "null").execute()
    except Exception as exc:
        log.warning("enriching paper %s failed (backfill will retry): %s", paper_id, exc)


def _create_post(
    token: str,
    team_id: str,
    paper_id: str,
    user_id: str,
    note: str | None,
    source: str = "web",
):
    """Insert the paper_post as the user (RLS enforces membership).

    `source` records how the paper got here ("web" | "bibtex" | "teams_pdf"), so a
    400-paper import can be told apart from 400 people posting. Returns
    ``(id, already, source)`` — the row's actual value, so callers can gate side
    effects on it (the Teams mirror fires only for 'web' posts).
    """
    uc = user_client(token)

    existing = (
        uc.table("paper_posts")
        .select("id, source")
        .eq("paper_id", paper_id)
        .eq("team_id", team_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"], True, existing.data[0]["source"]

    row = {
        "paper_id": paper_id,
        "team_id": team_id,
        "posted_by": user_id,
        "source": source,
        "note": note,
    }
    try:
        inserted = uc.table("paper_posts").insert(row).execute()
    except Exception as exc:
        # RLS denial (not a member of the lab) surfaces as 42501.
        if getattr(exc, "code", None) == "42501":
            raise HTTPException(status_code=403, detail="You are not a member of this lab") from exc
        raise HTTPException(status_code=400, detail=f"Could not post paper: {exc}") from exc
    return inserted.data[0]["id"], False, row["source"]


# --- routes ----------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/resolve", response_model=ResolvedPaper)
def resolve(req: ResolveRequest, token: str = Depends(require_token)) -> ResolvedPaper:
    """Resolve a pasted URL to metadata + its normalized dedup key.

    Makes the server fetch a URL the caller chose, so it is an SSRF sink and is
    guarded on three sides:

      * **Authenticated.** It used to be open to the internet, which made it a free
        port scanner for whatever network the API runs in. It needs an account now —
        that doesn't fix SSRF (a member can still call it) but it ends drive-by use
        and puts a user id next to every fetch in the log.
      * **Validated**, so a blocked URL is an honest 400 rather than a silently empty
        record that looks like an ordinary bot-walled publisher.
      * **Rate-limited**, because each call costs an outbound request.

    The fetch itself is guarded again inside `fetch_metadata` — that's the layer that
    catches a redirect to an internal address, which no check on the submitted URL can.
    """
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Validate before spending quota: a blocked/malformed URL never fetches, so it
    # shouldn't cost the caller one of their 30/min. The limiter bounds outbound work.
    url = _validated_fetch_url(req.url)
    _resolve_limiter.check(user_id)
    meta = fetch_metadata(url, network=req.network)
    return _resolved(meta, url, _normalize_key(url))


@app.post("/posts", response_model=PostResponse)
def create_post(
    req: PostRequest, background: BackgroundTasks, token: str = Depends(require_token)
) -> PostResponse:
    """Post a paper into a lab (JWT-verified; membership checked before any write)."""
    # Checked up front, not left to RLS on the paper_post insert below. `_upsert_paper`
    # runs first and writes `papers` with the service role — and since it can now
    # *repair* an existing row (not just insert a new one), an RLS denial arriving
    # afterwards would be too late: a non-member's metadata would already be on a row
    # every other lab sharing that paper can see.
    user_id = _require_member(token, req.team_id)

    if req.fields is not None:
        # The web dialog resolved first and posts back what the user approved: we store
        # what they saw and never re-fetch (which would overwrite a hand-typed title
        # with the empty record a bot-walled publisher returns). No outbound request, so
        # no SSRF check and no rate limit. We still reject href-executable schemes
        # (javascript:/data:/…) so a hand-entered link can't become stored XSS, while
        # a bare DOI or a bot-walled publisher page (both scheme-less/http) still posts.
        _reject_dangerous_url(req.url)
        # Normalise the same way the fetch path does (bare DOI -> doi.org, scheme-less
        # -> https) so a non-web caller that posts fields with a bare DOI still stores a
        # real URL and dedupes against the same paper added via /resolve. Pure string
        # work, no network — the SSRF concerns that gate _validated_fetch_url don't apply.
        url = _clean_url(coerce_fetch_url(req.url))
        meta = PaperMetadata(url=url, **req.fields.model_dump())
    else:
        # No fields: this resolves the URL server-side — the same SSRF sink as /resolve,
        # so it gets the same rate limit and validation. Membership narrows who can reach
        # it; it doesn't make the fetch safe or free. Validate before the limiter, so a
        # blocked URL doesn't spend quota.
        url = _validated_fetch_url(req.url)
        _resolve_limiter.check(user_id)
        meta = fetch_metadata(url)
    url_norm = _normalize_key(url)
    paper_id, needs_embedding = _upsert_paper(meta, url, url_norm)
    post_id, already, post_source = _create_post(token, req.team_id, paper_id, user_id, req.note)

    # Embed + tag after responding so posting stays fast; each no-ops without
    # its key, and the backfill scripts cover anything skipped.
    if needs_embedding and get_api_settings().voyage_api_key:
        background.add_task(_embed_and_store, paper_id, meta.title, meta.abstract)
    if needs_embedding:
        background.add_task(_enrich_and_store, paper_id, meta.title, meta.abstract)

    # Mirror new web posts to the lab's Teams channel (no-op for unmapped labs;
    # failures are logged inside, never surfaced). Loop guard: only source='web'
    # posts mirror, so Teams-ingested posts (source='teams', M2) can never echo
    # back into the channel they came from.
    if not already and post_source == "web":
        background.add_task(
            teams_integration.notify_paper_posted,
            req.team_id,
            url=url,
            paper_id=paper_id,
            title=meta.title,
            authors=meta.authors,
            venue=meta.venue,
            year=meta.year,
            abstract=meta.abstract,
            note=req.note,
            posted_by_id=user_id,
        )

    return PostResponse(
        post_id=post_id,
        paper_id=paper_id,
        already_posted=already,
        paper=_resolved(meta, url, url_norm),
    )


# --- correcting a paper ----------------------------------------------------
#
# `papers` is global: one row serves every lab holding the paper, so a correction
# lands for all of them. Two operations, deliberately separate (see
# docs/paper-metadata-editing-plan.md): Re-resolve, for "the resolver was broken
# and has since been fixed", and fix-by-hand, for "no registry will ever have
# this". Both ask `can_edit_paper` as the caller and write through
# `apply_paper_edit` as the service role, so the authorization rule exists once
# and every write carries its history and concurrency check atomically.

# What a person may correct. Not `doi` or `url`: both are unique dedup keys, and
# changing one can collide with another row or split one paper into two
# identities across labs. That is a merge, not an edit.
EDITABLE_FIELDS = ("title", "authors", "venue", "year", "abstract", "code_url", "data_url")

# Everything an edit compares against or reports back. Never `*`: the embedding.
_EDIT_COLUMNS = (
    "id, url, doi, title, authors, venue, year, abstract, keywords, code_url, data_url, "
    "metadata_source, published_at, edited_by, edited_at, edited_fields"
)


class PaperEditRequest(BaseModel):
    """A hand correction. Only the fields present are considered.

    ``expected_edited_at`` is the row's ``edited_at`` as the form was rendered from
    it — required, and null is a real value ("never edited when I loaded it").
    """

    expected_edited_at: datetime | None
    title: str | None = Field(default=None, max_length=2_000)
    authors: list[Author] = Field(default=[], max_length=1_000)
    venue: str | None = Field(default=None, max_length=500)
    year: int | None = Field(default=None, ge=1000, le=2200)
    abstract: str | None = Field(default=None, max_length=100_000)
    code_url: str | None = Field(default=None, max_length=2_000)
    data_url: str | None = Field(default=None, max_length=2_000)


class ReresolveRequest(BaseModel):
    expected_edited_at: datetime | None
    # Re-resolve takes whatever the publisher says, including over fields a person
    # corrected. When there are any, the caller must say so — enforced here, not
    # only as a confirm in the web client, so no other client can skip it.
    discard_edits: bool = False


class PaperEditResponse(BaseModel):
    # "updated" | "unchanged" | "unresolved" (the publisher gave us nothing usable)
    status: Literal["updated", "unchanged", "unresolved"]
    paper: dict
    # Re-resolve found a DOI another row already holds: the rest was written, the
    # DOI was not, and the pair needs merging by a person.
    duplicate_of: str | None = None


def _require_paper_editor(token: str, paper_id: str) -> str:
    """The caller's id, or 403 — asked of the database as the caller.

    One answer for "no such paper" and "not yours", so the endpoint is not an
    oracle for which papers other labs hold.
    """
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    allowed = user_client(token).rpc("can_edit_paper", {"p_paper": paper_id}).execute().data
    if allowed is not True:
        raise HTTPException(
            status_code=403,
            detail="Only whoever shared this paper, or an owner of a lab holding it, "
            "can correct it.",
        )
    return user_id


def _load_paper(paper_id: str) -> dict:
    found = (
        service_client().table("papers").select(_EDIT_COLUMNS).eq("id", paper_id).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="That paper no longer exists.")
    return found.data[0]


def _is_stale(row: dict, expected: datetime | None) -> bool:
    return _parse_ts(row.get("edited_at")) != expected


_STALE = "Someone else changed this paper since you opened it. Reload to see their version."


def _apply_edit(
    paper_id: str, user_id: str, kind: str, expected: datetime | None, patch: dict, held: list[str]
) -> None:
    """Write through apply_paper_edit; its errors become honest HTTP answers."""
    try:
        service_client().rpc(
            "apply_paper_edit",
            {
                "p_paper": paper_id,
                "p_editor": user_id,
                "p_kind": kind,
                "p_expected": expected.isoformat() if expected else None,
                "p_patch": patch,
                "p_held": held,
            },
        ).execute()
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == "40001":
            raise HTTPException(status_code=409, detail=_STALE) from exc
        if code == "P0002":  # no_data_found
            raise HTTPException(status_code=404, detail="That paper no longer exists.") from exc
        if code == "23505":  # unique_violation — the DOI guard lost a race
            raise HTTPException(
                status_code=409, detail="Another paper already holds that DOI."
            ) from exc
        raise


def _rederive(background: BackgroundTasks, paper_id: str, patch: dict, row: dict) -> None:
    """Re-embed and re-tag after a change to what they are computed from.

    Only title and abstract feed them. Re-tagging rewrites `papers.tags`, which
    every lab holding the paper sees, so fixing a code link must not trigger it.
    """
    if "title" not in patch and "abstract" not in patch:
        return
    title = patch.get("title", row.get("title"))
    abstract = patch.get("abstract", row.get("abstract"))
    if get_api_settings().voyage_api_key:
        background.add_task(_embed_and_store, paper_id, title, abstract)
    background.add_task(_enrich_and_store, paper_id, title, abstract)


def _clean_edit(req: PaperEditRequest) -> dict:
    """The supplied fields, trimmed, with blanks as null — or a 400."""
    out: dict = {}
    for field in EDITABLE_FIELDS:
        if field not in req.model_fields_set:
            continue
        value = getattr(req, field)
        if field == "authors":
            value = [a.strip() for a in value if a.strip()]
        elif isinstance(value, str):
            value = value.strip() or None
        if field in ("code_url", "data_url") and value:
            _reject_dangerous_url(value)
        out[field] = value
    if "title" in out and not out["title"]:
        # An untitled row is what the resolver backfills — clearing a title by hand
        # would hand the row straight back to the machinery this edit overrides.
        raise HTTPException(status_code=400, detail="A paper needs a title.")
    return out


@app.patch("/papers/{paper_id}", response_model=PaperEditResponse)
def fix_paper(
    paper_id: str,
    req: PaperEditRequest,
    background: BackgroundTasks,
    token: str = Depends(require_token),
) -> PaperEditResponse:
    """Correct a paper's metadata by hand, for every lab that holds it.

    Only fields that actually change are written, and only those become held —
    re-saving the form untouched must not opt the rest of the row out of backfill.
    """
    user_id = _require_paper_editor(token, paper_id)
    supplied = _clean_edit(req)
    row = _load_paper(paper_id)
    if _is_stale(row, req.expected_edited_at):
        raise HTTPException(status_code=409, detail=_STALE)

    patch = {k: v for k, v in supplied.items() if v != row.get(k)}
    if not patch:
        return PaperEditResponse(status="unchanged", paper=row)

    held = sorted(set(row.get("edited_fields") or []) | set(patch))
    follow_year(patch, row)
    # Provenance only — what the backfill respects is `edited_fields`.
    patch["metadata_source"] = "manual"
    if "title" in patch or "abstract" in patch:
        patch["embedded_at"] = None
        patch["enriched_at"] = None

    _apply_edit(paper_id, user_id, "edit", req.expected_edited_at, patch, held)
    _rederive(background, paper_id, patch, row)
    return PaperEditResponse(status="updated", paper=_load_paper(paper_id))


@app.post("/papers/{paper_id}/resolve", response_model=PaperEditResponse)
def reresolve_paper(
    paper_id: str,
    req: ReresolveRequest,
    background: BackgroundTasks,
    token: str = Depends(require_token),
) -> PaperEditResponse:
    """Fetch the paper's metadata again and take what the publisher says.

    The right fix when the resolver was the problem and has since been fixed.
    Never blanks a field (an empty answer leaves the old value), and asking for it
    clears every hand hold — which is why it must be asked for explicitly when
    there are any.
    """
    user_id = _require_paper_editor(token, paper_id)
    row = _load_paper(paper_id)
    # Both checked before the fetch, so a request that cannot succeed costs no
    # outbound call and no rate-limit quota.
    if _is_stale(row, req.expected_edited_at):
        raise HTTPException(status_code=409, detail=_STALE)
    held = row.get("edited_fields") or []
    if held and not req.discard_edits:
        raise HTTPException(
            status_code=409,
            detail="Fields corrected by hand would be overwritten: " + ", ".join(held) + ".",
        )

    # Same SSRF guard and the same budget as /resolve: this is the same outbound
    # fetch, and must not be an unmetered door into it.
    url = _validated_fetch_url(row["url"])
    _resolve_limiter.check(user_id)
    meta = fetch_metadata(url)

    owner = _doi_owner(service_client(), _norm_doi(meta.doi), paper_id)
    patch, note = plan_update(row, meta, owner)
    if note == "unresolved":
        return PaperEditResponse(status="unresolved", paper=row)
    duplicate_of = owner if note else None
    if not patch and not held:
        return PaperEditResponse(status="unchanged", paper=row, duplicate_of=duplicate_of)

    _apply_edit(paper_id, user_id, "resolve", req.expected_edited_at, patch, [])
    _rederive(background, paper_id, patch, row)
    return PaperEditResponse(
        status="updated" if patch else "unchanged",
        paper=_load_paper(paper_id),
        duplicate_of=duplicate_of,
    )


@app.post("/search/semantic", response_model=SemanticSearchResponse)
def semantic_search(
    req: SemanticSearchRequest, token: str = Depends(require_token)
) -> SemanticSearchResponse:
    """Rank the lab's posts against a free-text query by embedding similarity.

    The query is embedded here (the embedding key is server-side only); the
    ranking RPC runs as the caller, so RLS scopes results to their labs.
    """
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    _query_limiter.check(user_id)  # bound the paid embedding call
    try:
        query_vector = embeddings.embed_query(query)
    except embeddings.EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=f"Embeddings unavailable: {exc}") from exc

    uc = user_client(token)
    matches = (
        uc.rpc(
            "match_papers",
            {"p_team": req.team_id, "p_query": query_vector, "p_limit": req.limit},
        )
        .execute()
        .data
        or []
    )
    if not matches:
        return SemanticSearchResponse(results=[])

    similarity = {m["post_id"]: m["similarity"] for m in matches}
    posts = (
        uc.table("paper_posts").select(POST_COLUMNS).in_("id", list(similarity)).execute().data
        or []
    )
    by_id = {p["id"]: p for p in posts}
    return SemanticSearchResponse(
        results=[
            SemanticHit(similarity=similarity[m["post_id"]], post=by_id[m["post_id"]])
            for m in matches
            if m["post_id"] in by_id
        ]
    )


class SimilarityRequest(BaseModel):
    query: str
    team_id: str


class SimilarityResponse(BaseModel):
    # cosine similarity of every embedded paper in the lab to the query, in
    # [-1, 1]. Powers the map's "Relevance" color mode (rank-scaled client-side).
    similarities: dict[str, float]


@app.post("/similarity", response_model=SimilarityResponse)
def similarity(req: SimilarityRequest, token: str = Depends(require_token)) -> SimilarityResponse:
    """Similarity of *all* the lab's embedded papers to a query (not just top-N).

    The authenticated role's PostgREST caps RPC returns, so we can't get every
    paper's score via the user client. Instead we gate on RLS — a non-member can
    see no posts in the team — then run the (uncapped) ranking with the service
    client, scoped to that same team_id. A non-member gets an empty result.
    """
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    query = req.query.strip()
    if not query:
        return SimilarityResponse(similarities={})

    uc = user_client(token)
    visible = (
        uc.table("paper_posts").select("id").eq("team_id", req.team_id).limit(1).execute().data
    )
    if not visible:  # not a member (RLS returns nothing), or an empty lab
        return SimilarityResponse(similarities={})

    _query_limiter.check(user_id)  # bound the paid embedding call
    try:
        query_vector = embeddings.embed_query(query)
    except embeddings.EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=f"Embeddings unavailable: {exc}") from exc

    rows = (
        service_client()
        .rpc(
            "match_papers",
            {"p_team": req.team_id, "p_query": query_vector, "p_limit": _SIMILARITY_MAX_PAPERS},
        )
        .execute()
        .data
        or []
    )
    return SimilarityResponse(similarities={r["paper_id"]: r["similarity"] for r in rows})


def _last_author_lab(authors: list) -> str | None:
    """Last author as a rough proxy for 'the lab that produced the paper' (§4.1a)."""
    return authors[-1] if authors else None


# PostgREST caps a single response at max_rows (supabase/config.toml: 1000). Page
# through so aggregates see every row instead of a silent first-1000 slice once a
# lab grows past that. _IN_BATCH keeps a paper_id `in_` list within URL limits.
_PAGE_SIZE = 1000
_IN_BATCH = 300


def _chunks(seq: list, n: int):
    """Yield `seq` in lists of at most n."""
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _fetch_all(make_query) -> list[dict]:
    """Collect every row of a PostgREST select, one page at a time. `make_query`
    returns a fresh (unexecuted) query builder each call and must impose a stable
    order so pages don't overlap or skip. Advances by the number of rows actually
    returned (not by _PAGE_SIZE) so it stays correct even if the server's max-rows
    is below _PAGE_SIZE, and stops only on an empty page."""
    out: list[dict] = []
    start = 0
    while True:
        page = make_query().range(start, start + _PAGE_SIZE - 1).execute().data or []
        if not page:
            return out
        out.extend(page)
        start += len(page)


def _engagement_counts(uc, team_id: str, paper_ids: list[str]) -> dict[str, tuple[int, int]]:
    """(reactions, comments) per paper for the team, RLS-scoped. {} if no ids."""
    if not paper_ids:
        return {}
    counts: dict[str, list[int]] = {pid: [0, 0] for pid in paper_ids}
    # Count reactions/comments for exactly the shown papers — batched so a large id
    # list stays within URL limits, and paged so a hot paper isn't capped at
    # PostgREST max-rows. Scoping to paper_ids keeps a map (which shows a subset)
    # from scanning the whole lab's engagement.
    for batch in _chunks(paper_ids, _IN_BATCH):
        for r in _fetch_all(
            lambda b=batch: uc.table("reactions")
            .select("paper_id")
            .eq("team_id", team_id)
            .in_("paper_id", b)
            .order("id")
        ):
            if r["paper_id"] in counts:
                counts[r["paper_id"]][0] += 1
        for c in _fetch_all(
            lambda b=batch: uc.table("comments")
            .select("paper_id")
            .eq("team_id", team_id)
            .in_("paper_id", b)
            .order("id")
        ):
            if c["paper_id"] in counts:
                counts[c["paper_id"]][1] += 1
    return {k: (v[0], v[1]) for k, v in counts.items()}


def _compute_stats(rows: list[dict]) -> OverviewStats:
    """Aggregate the lab's posts (joined papers) into the stat panels."""
    over_time: Counter = Counter()
    by_venue: Counter = Counter()
    by_year: Counter = Counter()
    by_lab: Counter = Counter()
    by_tag: Counter = Counter()
    for r in rows:
        p = r.get("papers") or {}
        if r.get("posted_at"):
            over_time[r["posted_at"][:7]] += 1  # YYYY-MM
        if p.get("venue"):
            by_venue[p["venue"]] += 1
        if p.get("year"):
            by_year[p["year"]] += 1
        lab = _last_author_lab(p.get("authors") or [])
        if lab:
            by_lab[lab] += 1
        for tag in p.get("tags") or []:
            by_tag[tag] += 1
    return OverviewStats(
        over_time=[{"month": m, "count": n} for m, n in sorted(over_time.items())],
        by_venue=[{"venue": v, "count": n} for v, n in by_venue.most_common(10)],
        by_year=[{"year": y, "count": n} for y, n in sorted(by_year.items())],
        by_lab=[{"lab": lab, "count": n} for lab, n in by_lab.most_common(10)],
        by_tag=[{"tag": t, "count": n} for t, n in by_tag.most_common(15)],
    )


# Explicit columns for the overview: the post date + the paper's metadata and
# embedding. Shared by the whole-lab overview and the scoped map overview.
_OVERVIEW_COLS = (
    "paper_id, posted_at, "
    "papers(id, title, venue, year, keywords, tags, authors, embedding, embedded_at)"
)

# Cap on members pulled per map surface (scatter / list / summary). A map with
# more members than this is truncated to the top by seed similarity; kept in one
# place so the three endpoints agree and the bound is documented.
_MAP_MEMBER_LIMIT = 500


def _build_overview(uc: object, team_id: str, rows: list[dict]) -> OverviewResponse:
    """Turn paper_posts rows (with joined papers) into the 2-D layout + clusters +
    stats. `cached_layout` keys on the papers' content signature, so passing a
    *subset* (a map's members) yields that subset's own layout and sub-themes."""
    total = len(rows)
    stats = _compute_stats(rows)
    papers = [r["papers"] for r in rows if r.get("papers") and r["papers"].get("embedding")]
    if not papers:
        return OverviewResponse(points=[], clusters=[], stats=stats, total=total, embedded=0)
    papers.sort(key=lambda p: p["id"])  # deterministic layout/cluster order

    point_by_id, clusters = overview_mod.cached_layout(team_id, papers)
    eng = _engagement_counts(uc, team_id, [p["id"] for p in papers])
    points = [
        OverviewPoint(
            paper_id=p["id"],
            x=point_by_id[p["id"]]["x"],
            y=point_by_id[p["id"]]["y"],
            cluster=point_by_id[p["id"]]["cluster"],
            title=p.get("title"),
            venue=p.get("venue"),
            year=p.get("year"),
            keywords=p.get("keywords") or [],
            tags=p.get("tags") or [],
            lab=_last_author_lab(p.get("authors") or []),
            reactions=eng.get(p["id"], (0, 0))[0],
            comments=eng.get(p["id"], (0, 0))[1],
        )
        for p in papers
    ]
    return OverviewResponse(
        points=points,
        clusters=[Cluster(**c) for c in clusters],
        stats=stats,
        total=total,
        embedded=len(papers),
    )


@app.get("/overview", response_model=OverviewResponse)
def overview(team_id: str, token: str = Depends(require_token)) -> OverviewResponse:
    """Insights overview for a lab: 2-D layout + named clusters + stats (RLS-scoped).

    The layout (t-SNE) + clustering + cluster names are cached per team by the
    embedded set; engagement and stats are computed fresh so they stay live.
    """
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uc = user_client(token)
    rows = _fetch_all(
        lambda: uc.table("paper_posts").select(_OVERVIEW_COLS).eq("team_id", team_id).order("id")
    )
    return _build_overview(uc, team_id, rows)


# Only for *displaying* the effective floor when a map hasn't overridden it; the
# actual filtering default lives in the map_members / map_member_stats SQL. Keep the
# two in sync (both 0.35) or the shown threshold won't match what's filtered.
_DEFAULT_MIN_SIMILARITY = 0.35


class MapOverviewResponse(OverviewResponse):
    map_id: str
    name: str
    seed: str
    visibility: str
    created_by: str  # so the client can gate edit controls to the creator
    new_this_week: int  # members posted in the last 7 days
    min_similarity: float  # the map's relevance floor
    below_threshold: int  # embedded papers that fall just under the floor
    excluded_count: int  # papers the owner has dismissed from the map


@app.get("/maps/{map_id}/overview", response_model=MapOverviewResponse)
def map_overview(map_id: str, token: str = Depends(require_token)) -> MapOverviewResponse:
    """The scoped map: a t-SNE + sub-themes over just the map's member papers.

    Membership comes from the `map_members` RPC (seed similarity ≥ floor, + pins,
    − excludes); RLS on `maps` means a caller who can't see the map gets a 404.
    """
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uc = user_client(token)

    rows = (
        uc.table("maps")
        .select("id, team_id, name, seed, visibility, config, created_by")
        .eq("id", map_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")
    m = rows[0]
    cfg = m.get("config") or {}
    min_sim = float(cfg.get("min_similarity", _DEFAULT_MIN_SIMILARITY))
    excluded_count = len(cfg.get("excluded") or [])
    stat = uc.rpc("map_member_stats", {"p_map": map_id}).execute().data or []
    below = (stat[0].get("below", 0) if stat else 0) or 0

    members = (
        uc.rpc("map_members", {"p_map": map_id, "p_limit": _MAP_MEMBER_LIMIT})
        .execute().data or []
    )
    member_ids = [x["paper_id"] for x in members]
    if not member_ids:
        base = OverviewResponse(
            points=[], clusters=[], stats=_compute_stats([]), total=0, embedded=0
        )
        return MapOverviewResponse(
            **base.model_dump(), map_id=map_id, name=m["name"], seed=m["seed"],
            visibility=m["visibility"], created_by=m["created_by"], new_this_week=0,
            min_similarity=min_sim, below_threshold=below, excluded_count=excluded_count,
        )

    post_rows = (
        uc.table("paper_posts").select(_OVERVIEW_COLS)
        .eq("team_id", m["team_id"]).in_("paper_id", member_ids)
        .execute().data or []
    )
    base = _build_overview(uc, m["team_id"], post_rows)
    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    new_this_week = sum(1 for r in post_rows if (r.get("posted_at") or "") >= cutoff)
    return MapOverviewResponse(
        **base.model_dump(), map_id=map_id, name=m["name"], seed=m["seed"],
        visibility=m["visibility"], created_by=m["created_by"], new_this_week=new_this_week,
        min_similarity=min_sim, below_threshold=below, excluded_count=excluded_count,
    )


class MapPaper(BaseModel):
    post_id: str
    paper_id: str
    title: str | None = None
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    similarity: float | None = None  # relevance to the map's seed
    reactions: int = 0
    comments: int = 0
    read_status: str | None = None  # 'unread'|'reading'|'read'|None, for the caller
    posted_at: str | None = None
    pinned: bool = False


class MapPapersResponse(BaseModel):
    total: int
    papers: list[MapPaper]
    labs: list[dict]  # [{lab, count}] over the member set


@app.get("/maps/{map_id}/papers", response_model=MapPapersResponse)
def map_papers(
    map_id: str, sort: str = "importance", token: str = Depends(require_token)
) -> MapPapersResponse:
    """The map's member papers, ranked, with the caller's read-state and relevance,
    plus the labs driving the topic. The client filters (unread / search / lab) and
    the sub-themes come from /maps/{id}/overview, so this endpoint stays cheap."""
    uid = get_user_id(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uc = user_client(token)

    rows = uc.table("maps").select("team_id").eq("id", map_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")
    team_id = rows[0]["team_id"]

    members = (
        uc.rpc("map_members", {"p_map": map_id, "p_limit": _MAP_MEMBER_LIMIT})
        .execute().data or []
    )
    if not members:
        return MapPapersResponse(total=0, papers=[], labs=[])
    sim_by_pid = {x["paper_id"]: x["similarity"] for x in members}
    pinned_by_pid = {x["paper_id"]: x.get("pinned", False) for x in members}
    paper_ids = list(sim_by_pid)

    meta = {
        p["id"]: p
        for p in (
            uc.table("papers").select("id, title, authors, venue, year, doi")
            .in_("id", paper_ids).execute().data or []
        )
    }
    posts = {
        p["paper_id"]: p
        for p in (
            uc.table("paper_posts").select("id, paper_id, posted_at")
            .eq("team_id", team_id).in_("paper_id", paper_ids).execute().data or []
        )
    }
    eng = _engagement_counts(uc, team_id, paper_ids)
    read = {
        r["paper_id"]: r["status"]
        for r in (
            uc.table("paper_status").select("paper_id, status")
            .eq("team_id", team_id).eq("user_id", uid).in_("paper_id", paper_ids)
            .execute().data or []
        )
    }

    now = datetime.now(UTC)
    max_eng = max([eng.get(pid, (0, 0))[0] + eng.get(pid, (0, 0))[1] for pid in paper_ids] + [1])
    scored: list[tuple[float, MapPaper]] = []
    for pid in paper_ids:
        p = meta.get(pid)
        if not p:
            continue
        post = posts.get(pid, {})
        r_, c_ = eng.get(pid, (0, 0))
        sim = sim_by_pid.get(pid) or 0.0
        recency = _recency_decay(_parse_ts(post.get("posted_at")), now)
        importance = sim + 0.15 * ((r_ + c_) / max_eng) + 0.08 * recency
        scored.append(
            (
                importance,
                MapPaper(
                    post_id=post.get("id", ""), paper_id=pid, title=p.get("title"),
                    authors=p.get("authors") or [], venue=p.get("venue"), year=p.get("year"),
                    doi=p.get("doi"), similarity=sim, reactions=r_, comments=c_,
                    read_status=read.get(pid), posted_at=post.get("posted_at"),
                    pinned=bool(pinned_by_pid.get(pid, False)),
                ),
            )
        )

    if sort == "recent":
        scored.sort(key=lambda t: (t[1].posted_at or ""), reverse=True)
    elif sort == "discussed":
        scored.sort(key=lambda t: (t[1].reactions + t[1].comments), reverse=True)
    else:  # importance (default)
        scored.sort(key=lambda t: t[0], reverse=True)
    papers = [t[1] for t in scored]

    lab_counts: Counter = Counter()
    for mp in papers:
        lab = _last_author_lab(mp.authors)
        if lab:
            lab_counts[lab] += 1
    labs = [{"lab": lab, "count": n} for lab, n in lab_counts.most_common(8)]
    return MapPapersResponse(total=len(papers), papers=papers, labs=labs)


class MapSummary(BaseModel):
    text: str
    cited_ids: list[str] = []
    n_papers: int = 0
    ai: bool = False  # true = LLM-synthesized; false = recency fallback / none
    generated_at: str | None = None


_SUMMARY_MAX_PAPERS = 8  # abstracts sent to the model
_SUMMARY_MIN_PAPERS = 3  # below this a topic is too thin to summarize


@app.get("/maps/{map_id}/summary", response_model=MapSummary)
def get_map_summary(map_id: str, token: str = Depends(require_token)) -> MapSummary:
    """The cached AI summary, if one has been generated. RLS 404s a hidden map."""
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    rows = (
        user_client(token).table("maps").select("ai_summary").eq("id", map_id).limit(1)
        .execute().data or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")
    cached = rows[0].get("ai_summary")
    return MapSummary(**cached) if cached else MapSummary(text="")


@app.post("/maps/{map_id}/summary", response_model=MapSummary)
def make_map_summary(
    map_id: str, force: bool = False, token: str = Depends(require_token)
) -> MapSummary:
    """Generate (and cache) a grounded, cited summary of the map's recent papers.

    On demand only — never on page load — so the model cost is paid when a member
    asks. Any member of a visible map may refresh this shared summary, so the cache
    write uses the service client after RLS has confirmed the caller can see the map.
    """
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uc = user_client(token)

    rows = (
        uc.table("maps").select("team_id, seed, ai_summary").eq("id", map_id).limit(1).execute().data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")
    team_id, seed = rows[0]["team_id"], rows[0]["seed"]

    # Return the cached summary unless the caller explicitly forces a refresh —
    # POST previously re-called the LLM (Anthropic) on every request.
    cached = rows[0].get("ai_summary")
    if cached and not force:
        return MapSummary(**cached)
    _summary_limiter.check(user_id)  # bound the paid LLM call

    members = (
        uc.rpc("map_members", {"p_map": map_id, "p_limit": _MAP_MEMBER_LIMIT})
        .execute().data or []
    )
    sim = {m["paper_id"]: m["similarity"] for m in members}
    paper_ids = list(sim)
    papers = (
        uc.table("papers").select("id, title, abstract, year")
        .in_("id", paper_ids).execute().data or []
        if paper_ids
        else []
    )
    posts = {
        p["paper_id"]: p.get("posted_at")
        for p in (
            uc.table("paper_posts").select("paper_id, posted_at")
            .eq("team_id", team_id).in_("paper_id", paper_ids).execute().data or []
        )
    }
    # most recent, then most relevant — this is a "what's *new*" brief.
    papers.sort(key=lambda p: (posts.get(p["id"]) or "", sim.get(p["id"]) or 0), reverse=True)
    top = [
        {
            "paper_id": p["id"],
            "title": p.get("title"),
            "abstract": p.get("abstract"),
            "year": p.get("year"),
        }
        for p in papers[:_SUMMARY_MAX_PAPERS]
    ]

    if len(top) < _SUMMARY_MIN_PAPERS:
        result = {
            "text": f"Only {len(top)} paper(s) in this map so far — too little to summarize yet.",
            "cited_ids": [], "n_papers": len(top), "ai": False,
        }
    else:
        result = map_summary_mod.generate_summary(seed, top)
    result["generated_at"] = datetime.now(UTC).isoformat()

    # Cache is best-effort: the summary is already computed, so a write failure (e.g.
    # a missing service_role grant) must not 500 the request — return it uncached and
    # log. Derived data, not user content; the RLS select above already gated access.
    try:
        service_client().table("maps").update({"ai_summary": result}).eq("id", map_id).execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not cache map summary for %s: %s", map_id, exc)
    return MapSummary(**result)


# --- profile embedding + recommendations -----------------------------------


def _parse_vec(value: object) -> list[float] | None:
    """PostgREST returns a `vector` column as a JSON string; normalize to a list."""
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value  # type: ignore[return-value]


def _l2norm(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


# Engagement weights for the taste centroid. Not all engagement is endorsement:
# an explicit save or a reaction is a strong "I want more like this"; a plain
# `read` only means "consumed" (preference unknown), so it barely nudges taste; a
# 🤔 reaction is skeptical, not enthusiastic. Weights are decayed by age so recent
# interests outweigh old ones.
_W_REACTION = 1.0
_W_SKEPTIC = 0.3  # 🤔
_W_COMMENT = 0.75
_W_BOOKMARK = 1.5  # paper_status.saved — an explicit, deliberate save
_W_READ = 0.25  # read / reading — consumed, but says little about preference
_HALFLIFE_DAYS = 90.0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_decay(ts: datetime | None, now: datetime) -> float:
    """Half-life decay: a signal loses half its weight every _HALFLIFE_DAYS."""
    if ts is None:
        return 1.0
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _HALFLIFE_DAYS)


def _engagement_weights(
    uc, user_id: str, team_id: str, anchors: dict[str, str] | None = None
) -> dict[str, float]:
    """Per-paper positive-interest weight for the user in this lab, blending signal
    strength (save > reaction > comment > read) with recency decay.

    Pass ``anchors`` to also collect, from the same rows, each paper's strongest
    kind of engagement for the recommendation reasons (see _ANCHOR_RANK)."""
    now = datetime.now(UTC)
    weights: dict[str, float] = {}

    def add(paper_id: str, w: float) -> None:
        weights[paper_id] = weights.get(paper_id, 0.0) + w

    def anchor(paper_id: str, kind: str) -> None:
        if anchors is None:
            return
        if paper_id not in anchors or _ANCHOR_RANK[kind] < _ANCHOR_RANK[anchors[paper_id]]:
            anchors[paper_id] = kind

    for r in (
        uc.table("reactions")
        .select("paper_id, emoji, created_at")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    ):
        base = _W_SKEPTIC if r.get("emoji") == "🤔" else _W_REACTION
        add(r["paper_id"], base * _recency_decay(_parse_ts(r.get("created_at")), now))
        # 🤔 is skeptical: it nudges taste, but "which you reacted to" would read
        # as an endorsement.
        if r.get("emoji") != "🤔":
            anchor(r["paper_id"], "similar_reacted")
    for c in (
        uc.table("comments")
        .select("paper_id, created_at")
        .eq("team_id", team_id)
        .eq("author_id", user_id)
        .execute()
        .data
        or []
    ):
        add(c["paper_id"], _W_COMMENT * _recency_decay(_parse_ts(c.get("created_at")), now))
        anchor(c["paper_id"], "similar_discussed")
    for s in (
        uc.table("paper_status")
        .select("paper_id, saved, status, updated_at")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    ):
        # Not saved and never started means the row says nothing — it is what
        # un-saving a paper, or un-marking it read, leaves behind. Scoring it as
        # _W_READ would let *discarding* a paper feed the taste vector as though
        # it had been consumed. Harmless while the client deleted those rows on
        # the way past; since 20261007130000 they are kept on purpose, so the
        # same question has to be asked here.
        if not s.get("saved") and s.get("status") == "unread":
            continue
        # Keyed off `saved`, not a status value. Since the two-axis split
        # (20261006120000) a save is a boolean that survives being read, so the
        # old `status == "to_read"` test would never fire again and every saved
        # paper would quietly collapse to the much weaker _W_READ.
        base = _W_BOOKMARK if s.get("saved") else _W_READ
        add(s["paper_id"], base * _recency_decay(_parse_ts(s.get("updated_at")), now))
        if s.get("saved"):
            anchor(s["paper_id"], "similar_saved")
        elif s.get("status") == "read":
            anchor(s["paper_id"], "similar_read")
        elif s.get("status") == "reading":
            anchor(s["paper_id"], "similar_reading")
    return weights


def _taste_vector(
    uc, user_id: str, weights: dict[str, float], loaded: dict | None = None
) -> list[float] | None:
    """Per-user taste vector: a confidence-weighted blend of the profile embedding
    and a recency-/strength-weighted engagement centroid over ``weights``
    (the caller's `_engagement_weights`, computed once per request).

    The engagement side's weight grows with how many papers the user has actually
    engaged with, so a single incidental interaction can't hijack the feed while
    the profile carries a sparse user. Missing either side falls back to the other;
    missing both returns None (cold start → recency fallback).

    Pass ``loaded`` (a dict) to keep what was fetched for the recommendation
    reasons, instead of fetching it again: "vecs" (paper id → unit vector),
    "titles", "profile_md" and "has_profile"."""
    prof = (
        uc.table("profiles").select("profile_vec, profile_md, interests").eq("id", user_id).limit(1)
        .execute().data or []
    )
    profile_vec = _parse_vec(prof[0]["profile_vec"]) if prof else None
    if loaded is not None:
        loaded["profile_md"] = (prof[0].get("profile_md") or "") if prof else ""
        loaded["has_profile"] = profile_vec is not None
        loaded["follows"] = _follows(prof[0] if prof else None)
        loaded.setdefault("vecs", {})
        loaded.setdefault("titles", {})
    profile_np = (
        _l2norm(np.asarray(profile_vec, dtype=np.float32)) if profile_vec is not None else None
    )

    centroid_np = None
    n_engaged = 0
    if weights:
        rows = (
            uc.table("papers").select("id, title, embedding").in_("id", list(weights))
            .execute().data or []
        )
        acc: np.ndarray | None = None
        wsum = 0.0
        for r in rows:
            w = weights.get(r["id"], 0.0)
            if w <= 0 or not r.get("embedding"):
                continue
            v = _l2norm(np.asarray(_parse_vec(r["embedding"]), dtype=np.float32))
            if loaded is not None:
                loaded["vecs"][r["id"]] = v
                loaded["titles"][r["id"]] = r.get("title")
            acc = w * v if acc is None else acc + w * v
            wsum += w
            n_engaged += 1
        if acc is not None and wsum > 0:
            centroid_np = _l2norm(acc / wsum)

    if profile_np is None and centroid_np is None:
        return None
    if centroid_np is None:
        return profile_np.tolist()  # type: ignore[union-attr]
    if profile_np is None:
        return centroid_np.tolist()

    # Both present: trust engagement more the more of it there is (capped so the
    # profile always keeps a voice). n=1 → ~0.2, n=4 → 0.5, large → 0.7.
    eng_conf = min(0.7, n_engaged / (n_engaged + 4.0))
    return _l2norm((1 - eng_conf) * profile_np + eng_conf * centroid_np).tolist()


class ProfileRequest(BaseModel):
    profile_md: str


class ProfileResponse(BaseModel):
    ok: bool
    embedded: bool  # whether profile_vec was (re)computed


@app.post("/profile", response_model=ProfileResponse)
def update_profile(req: ProfileRequest, token: str = Depends(require_token)) -> ProfileResponse:
    """Save the caller's profile description and (re)embed it into profile_vec.

    profile_md is saved as the user (RLS); the vector is written with the service
    client. Centralizing the embed on save keeps profile_vec fresh for
    recommendations — like /posts embeds a paper on ingest."""
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    md = req.profile_md
    user_client(token).table("profiles").update({"profile_md": md}).eq("id", user_id).execute()

    text = md.strip()
    if not text:
        service_client().table("profiles").update({"profile_vec": None}).eq("id", user_id).execute()
        return ProfileResponse(ok=True, embedded=False)
    if not get_api_settings().voyage_api_key:
        return ProfileResponse(ok=True, embedded=False)  # md saved; vector left as-is
    _query_limiter.check(user_id)  # bound the paid embedding call
    try:
        # The profile describes what the user wants to read — embed it as a query
        # (papers are documents), the retrieval-tuned pairing for profile→paper.
        vector = embeddings.embed_texts([text], input_type="query")[0]
    except embeddings.EmbeddingError as exc:
        # The description saved fine; recommendations just won't reflect it yet.
        log.warning("embedding profile for %s failed: %s", user_id, exc)
        return ProfileResponse(ok=True, embedded=False)
    service_client().table("profiles").update({"profile_vec": vector}).eq("id", user_id).execute()
    return ProfileResponse(ok=True, embedded=True)


class Recommendation(BaseModel):
    similarity: float
    post: dict  # a paper_posts row with the joined paper (POST_COLUMNS)
    # Why this paper: {kind, ref_id, ref_label, extra_labels?}. Kinds and their
    # rules are documented above _REASON_MIN_SIMILARITY. None only if working the
    # reasons out failed.
    reason: dict | None = None


class RecommendationsResponse(BaseModel):
    results: list[Recommendation]
    cold_start: bool  # true when there was no taste signal (recency fallback used)


def _hydrate(
    uc, order_ids: list[str], sims: dict[str, float], cold: bool
) -> RecommendationsResponse:
    """Fetch POST_COLUMNS for the given post ids and return them in order."""
    if not order_ids:
        return RecommendationsResponse(results=[], cold_start=cold)
    posts = uc.table("paper_posts").select(POST_COLUMNS).in_("id", order_ids).execute().data or []
    by_id = {p["id"]: p for p in posts}
    return RecommendationsResponse(
        results=[
            Recommendation(similarity=sims.get(pid, 0.0), post=by_id[pid])
            for pid in order_ids
            if pid in by_id
        ],
        cold_start=cold,
    )


def _reading_list_ranked(
    uc, user_id: str, team_id: str, taste, limit: int
) -> RecommendationsResponse:
    """The user's saved papers, ranked by taste similarity."""
    saved = (
        uc.table("paper_status")
        .select("paper_id")
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("saved", True)
        .order("updated_at", desc=True)
        .execute()
        .data
        or []
    )
    paper_ids = [r["paper_id"] for r in saved]
    if not paper_ids:
        return RecommendationsResponse(results=[], cold_start=taste is None)

    posts = (
        uc.table("paper_posts")
        .select(POST_COLUMNS)
        .eq("team_id", team_id)
        .in_("paper_id", paper_ids)
        .execute()
        .data
        or []
    )
    post_by_paper = {p["papers"]["id"]: p for p in posts if p.get("papers")}

    if taste is None:  # no taste signal — keep the date-added order
        order = [post_by_paper[pid]["id"] for pid in paper_ids if pid in post_by_paper]
        return _hydrate(uc, order[:limit], {}, cold=True)

    taste_np = _l2norm(np.asarray(taste, dtype=np.float32))
    emb = uc.table("papers").select("id, embedding").in_("id", paper_ids).execute().data or []
    scored: list[tuple[float, str]] = []
    for e in emb:
        if not e.get("embedding") or e["id"] not in post_by_paper:
            continue
        v = _l2norm(np.asarray(_parse_vec(e["embedding"]), dtype=np.float32))
        scored.append((float(np.dot(taste_np, v)), post_by_paper[e["id"]]["id"]))
    scored.sort(reverse=True)
    order = [pid for _, pid in scored][:limit]
    sims = {pid: s for s, pid in scored}
    return _hydrate(uc, order, sims, cold=False)


def _follows(profile: dict | None) -> list[str]:
    """The tags the caller follows (profiles.interests), as clean strings."""
    raw = (profile or {}).get("interests") or []
    if not isinstance(raw, list):
        return []
    return [t.strip() for t in raw if isinstance(t, str) and t.strip()]


def _followed_hits(post: dict, follows: list[str]) -> list[str]:
    """The followed tags this post carries, by post_tags(): its lab tags if it
    has any, else the paper's own — the rule every tag surface uses."""
    if not follows:
        return []
    tags = post.get("tags") or (post.get("papers") or {}).get("tags") or []
    wanted = set(follows)
    return [t for t in tags if t in wanted]


def _recency_fallback(
    uc, team_id: str, seen: set[str], limit: int, follows: list[str] | None = None
) -> RecommendationsResponse:
    """Cold start (no profile, no engagement): recent unseen posts, newest first —
    with posts carrying a followed tag first, if the caller follows any.

    ``seen`` is the engaged-paper set the discover feed excludes (the SQL RPC does
    this server-side; here it comes from the request's `_engagement_weights` keys —
    every engagement row gets a nonzero weight, so the keys are exactly the seen set)."""
    rows = (
        uc.table("paper_posts")
        .select("id, paper_id, posted_at, tags, papers(tags)")
        .eq("team_id", team_id)
        .order("posted_at", desc=True)
        # A wider window when there are follows, so a followed-tag paper from a
        # few weeks back can still lead.
        .limit(limit * (10 if follows else 4))
        .execute()
        .data
        or []
    )
    unseen = [r for r in rows if r["paper_id"] not in seen]
    # sorted() is stable, so newest-first holds within each group.
    unseen = sorted(unseen, key=lambda r: not _followed_hits(r, follows or []))
    return _hydrate(uc, [r["id"] for r in unseen[:limit]], {}, cold=True)


# Every recommendation says why it is there (docs/dashboard.md §3.4), using the
# most specific reason that is true of how it was ranked:
#
#   1. engagement  "Similar to X, which you saved / reacted to / discussed / read /
#      are reading" —
#      the engaged paper nearest to it, if that paper is genuinely close (below
#      _REASON_MIN_SIMILARITY, naming one paper would be a claim the embeddings
#      don't support). Today most engagement happens in Teams, so this is rare
#      until it syncs into Atlas; it needs no change when it does.
#   1b. tag        "Tagged spatial-transcriptomics, which you follow" — a followed
#      tag the paper carries (profiles.interests). Certain, so it beats the
#      profile text match.
#   2. profile     "Matches spatial transcriptomics in your research profile" —
#      the paper's tags that the profile text mentions, else just "Matches your
#      research profile". Only when the caller has a profile vector, i.e. the
#      profile actually took part in the ranking.
#   3. new         "New in {lab} · shared by Sara" — the cold-start fallback,
#      which is newest-first.
#
# A taste built from engagement alone with no close paper gets "engagement"
# ("In line with your activity in Atlas") rather than a stretched "Similar to".
_REASON_MIN_SIMILARITY = 0.5
# When one paper carries several kinds of engagement, the strongest names it.
_ANCHOR_RANK = {
    "similar_saved": 0,
    "similar_reacted": 1,
    "similar_discussed": 2,
    "similar_read": 3,
    "similar_reading": 4,
}


def _pick_reason(
    vec: np.ndarray, anchors: list[tuple[str, str, str, np.ndarray]]
) -> dict | None:
    """The anchor (kind, paper_id, title, unit vector) nearest to ``vec`` (a unit
    vector), as a reason dict — or None when none clears _REASON_MIN_SIMILARITY."""
    best: tuple[float, tuple[str, str, str, np.ndarray]] | None = None
    for a in anchors:
        sim = float(np.dot(vec, a[3]))
        if best is None or sim > best[0]:
            best = (sim, a)
    if best is None or best[0] < _REASON_MIN_SIMILARITY:
        return None
    kind, paper_id, title, _ = best[1]
    return {"kind": kind, "ref_id": paper_id, "ref_label": title}


def _profile_tags(profile_md: str, tags: list[str]) -> list[str]:
    """The tags the profile text names as a phrase: "spatial-transcriptomics"
    matches "spatial transcriptomic(s)", "t-cell-exhaustion" matches "T cell
    exhaustion" but not "B cell … exhaustion", and "cell" doesn't match
    "cellular". Each word may take a plural "s" either way round."""
    text = profile_md.lower()
    out: list[str] = []
    for tag in tags:
        words = [w for w in re.split(r"[-_\s/]+", tag.lower()) if w]
        if not words:
            continue
        phrase = r"[\s\-/]+".join(re.escape(w.removesuffix("s")) + "s?" for w in words)
        if re.search(r"(?<![a-z0-9])" + phrase + r"(?![a-z0-9])", text):
            out.append(tag)
    return out


def _recommendation_reasons(
    uc, posts: list[dict], anchors: dict[str, str], loaded: dict
) -> dict[str, dict]:
    """paper_id → reason for each recommended post (rules 1–2 above; rule 3 is
    _new_reasons). Every post gets one: engagement if a paper is close enough,
    else profile, else the generic engagement line.

    ``anchors`` and ``loaded`` come from _engagement_weights / _taste_vector, so
    the engaged papers' embeddings aren't fetched twice; only the (≤ 50)
    recommended papers' embeddings are read here."""
    paper_ids = [p["papers"]["id"] for p in posts]
    if not paper_ids:
        return {}
    vecs: dict[str, np.ndarray] = loaded.get("vecs", {})
    titles: dict[str, str | None] = loaded.get("titles", {})
    rec_vecs = {
        p["id"]: _l2norm(np.asarray(_parse_vec(p["embedding"]), dtype=np.float32))
        for p in (
            uc.table("papers").select("id, embedding").in_("id", paper_ids).execute().data or []
        )
        if p.get("embedding")
    }
    candidates = [
        (kind, pid, titles[pid], vecs[pid])
        for pid, kind in anchors.items()
        # An untitled anchor can't be named on the card.
        if pid in vecs and titles.get(pid)
    ]
    # The profile only explains a card if it took part in the ranking (a vector)
    # and there is still text behind it.
    profile_md = loaded.get("profile_md") or ""
    use_profile = bool(loaded.get("has_profile") and profile_md.strip())

    follows: list[str] = loaded.get("follows") or []

    reasons: dict[str, dict] = {}
    for post in posts:
        pid = post["papers"]["id"]
        reason = _pick_reason(rec_vecs[pid], candidates) if pid in rec_vecs else None
        if reason is None:
            reason = _tag_reason(post, follows)
        if reason is None and use_profile:
            tags = post.get("tags") or post["papers"].get("tags") or []
            hits = _profile_tags(profile_md, tags)
            reason = {
                "kind": "profile",
                "ref_id": None,
                "ref_label": hits[0] if hits else "",
                "extra_labels": hits[1:2],
            }
        if reason is None:
            reason = {"kind": "engagement", "ref_id": None, "ref_label": ""}
        reasons[pid] = reason
    return reasons


def _tag_reason(post: dict, follows: list[str]) -> dict | None:
    """'Tagged X (and Y), which you follow' — certain, so it outranks the profile
    text match; a close engaged paper is still more specific and comes first."""
    hits = _followed_hits(post, follows)
    if not hits:
        return None
    return {"kind": "tag", "ref_id": None, "ref_label": hits[0], "extra_labels": hits[1:2]}


def _new_reasons(
    uc, user_id: str, posts: list[dict], follows: list[str] | None = None
) -> dict[str, dict]:
    """Rule 3: the cold-start fallback is newest-first, so say that, and who
    shared it ("you" for the caller's own posts) — unless it leads because of a
    followed tag, which is the truer reason."""
    ids = list({p["posted_by"] for p in posts if p.get("posted_by")})
    names = (
        {
            r["id"]: r.get("display_name")
            for r in uc.table("profiles").select("id, display_name").in_("id", ids)
            .execute().data or []
        }
        if ids
        else {}
    )

    def who(post: dict) -> str:
        if post.get("posted_by") == user_id:
            return "you"
        return post.get("posted_by_label") or names.get(post.get("posted_by")) or ""

    return {
        p["papers"]["id"]: _tag_reason(p, follows or [])
        or {"kind": "new", "ref_id": None, "ref_label": who(p)}
        for p in posts
    }


def _attach_reasons(result: RecommendationsResponse, reasons: dict[str, dict]) -> None:
    for r in result.results:
        r.reason = reasons.get(r.post["papers"]["id"])


@app.get("/recommendations", response_model=RecommendationsResponse)
def recommendations(
    team_id: str,
    scope: str = "discover",
    limit: int = 12,
    token: str = Depends(require_token),
) -> RecommendationsResponse:
    """Personalized papers for the caller in a lab, ranked by a taste vector.

    scope=discover: unseen papers ranked by taste (excludes read/engaged, RLS-scoped).
    scope=reading_list: the caller's saved papers ranked by taste.
    Falls back to recency when there's no taste signal yet."""
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if scope not in ("discover", "reading_list"):
        raise HTTPException(status_code=400, detail="scope must be 'discover' or 'reading_list'")
    limit = max(1, min(limit, 50))

    uc = user_client(token)
    anchors: dict[str, str] = {}
    loaded: dict = {}
    weights = _engagement_weights(uc, user_id, team_id, anchors)
    taste = _taste_vector(uc, user_id, weights, loaded)

    if scope == "reading_list":
        return _reading_list_ranked(uc, user_id, team_id, taste, limit)

    if taste is None:
        follows = loaded.get("follows") or []
        result = _recency_fallback(uc, team_id, set(weights), limit, follows)
        try:
            _attach_reasons(
                result, _new_reasons(uc, user_id, [r.post for r in result.results], follows)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("recommendation reasons failed for %s: %s", user_id, exc)
        return result

    matches = (
        uc.rpc(
            "recommend_papers",
            {
                "p_team": team_id,
                "p_query": taste,
                "p_limit": limit,
                "p_tags": loaded.get("follows") or [],
            },
        )
        .execute()
        .data
        or []
    )
    sims = {m["post_id"]: m["similarity"] for m in matches}
    result = _hydrate(uc, [m["post_id"] for m in matches], sims, cold=False)
    # Best-effort: a failure to explain must not cost the recommendations.
    try:
        _attach_reasons(
            result,
            _recommendation_reasons(uc, [r.post for r in result.results], anchors, loaded),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("recommendation reasons failed for %s: %s", user_id, exc)
    return result


# --- BibTeX import ---------------------------------------------------------
#
# Two steps on purpose. `/import/bibtex/preflight` parses and classifies but writes
# NOTHING, so a researcher sees exactly what a 438-entry file will do to their lab
# before it does it. `/import/bibtex` then commits.
#
# Note on dates: an imported post's `posted_at` stays "when your lab shared this"
# (i.e. now). The paper's publication date goes to `papers.published_at`. Writing the
# publication date into `posted_at` would make "Posted by Ellen · 11 years ago" appear
# under a paper Ellen imported this morning, and — since BibTeX usually carries only a
# year — would pile the whole corpus onto Jan 1 and sort arbitrarily inside each year.
# Sorting by publication date is a *sort option*, not a lie in the data.


class BibEntryPreview(BaseModel):
    key: str
    title: str | None
    authors: list[str]
    venue: str | None
    year: int | None
    published_at: str | None
    doi: str | None
    url: str | None
    status: str  # "new" | "duplicate" | "no_doi" | "rejected"
    reason: str | None = None


#: Far beyond any real library (a 500-entry Zotero export is well under 1 MB), and
#: small enough that a hostile body can't exhaust the process.
MAX_BIBTEX_BYTES = 8_000_000


class PreflightRequest(BaseModel):
    team_id: str
    bibtex: str = Field(max_length=MAX_BIBTEX_BYTES)


class PreflightResponse(BaseModel):
    entries: list[BibEntryPreview]
    new: int
    duplicates: int
    no_doi: int
    rejected: int
    #: What the Import button will actually add — new + no_doi. Kept explicit because
    #: "no DOI" is a *warning*, not a refusal: those papers import, matched on URL.
    importable: int


class ImportRequest(BaseModel):
    team_id: str
    bibtex: str = Field(max_length=MAX_BIBTEX_BYTES)


class ImportResponse(BaseModel):
    imported: int
    skipped: int
    failed: int


def _require_member(token: str, team_id: str) -> str:
    """The caller's id, or 403 — enforced before we read or write anything.

    The import path reads with the service role (it has to: it needs to see papers
    posted by *other* members to dedupe against them), which bypasses RLS. Without
    this check, `team_id` is attacker-controlled and the pre-flight becomes an oracle:
    post a one-entry .bib with a DOI at someone else's lab and a "duplicate" verdict
    tells you they have that paper. Every other write in this file goes through
    `user_client`, where RLS does this job for us; here it has to be explicit.
    """
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    member = (
        user_client(token)  # as the caller, so RLS answers the question honestly
        .table("team_members")
        .select("user_id")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not member.data:
        raise HTTPException(status_code=403, detail="You are not a member of this lab.")
    return user_id


def _chunked(items: list[str], size: int = 100) -> list[list[str]]:
    """PostgREST sends `in.(...)` as a query string. A 438-entry library would produce a
    filter tens of kilobytes long — long enough to be rejected or, worse, truncated,
    which would silently classify duplicates as new."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _preview(e: bib.BibEntry, status: str, reason: str | None = None) -> BibEntryPreview:
    return BibEntryPreview(
        key=e.key,
        title=e.title,
        authors=e.authors,
        venue=e.venue,
        year=e.year,
        published_at=e.published_at.isoformat() if e.published_at else None,
        doi=e.doi,
        url=e.url,
        status=status,
        reason=reason,
    )


def _classify(entries: list[bib.BibEntry], team_id: str) -> list[BibEntryPreview]:
    """Label each entry against what's already in the lab. Read-only.

    Dedupes exactly the way `_upsert_paper` does — by url_norm AND by DOI — because a
    pre-flight that promises "3 new" while the commit merges one of them into an
    existing paper is worse than no pre-flight at all. It also dedupes *within* the
    file: a library that lists the same DOI twice must not be counted twice.
    """
    svc = service_client()

    norms = {e.identifier: _normalize_key(e.identifier) for e in entries if e.identifier}
    dois = [d for d in (_norm_doi(e.doi) for e in entries) if d]

    by_norm: dict[str, str] = {}
    by_doi: dict[str, str] = {}
    for batch in _chunked(list(set(norms.values()))):
        rows = (
            svc.table("papers").select("id, url_norm").in_("url_norm", batch).execute().data or []
        )
        by_norm |= {r["url_norm"]: r["id"] for r in rows}
    for batch in _chunked(list(set(dois))):
        rows = svc.table("papers").select("id, doi").in_("doi", batch).execute().data or []
        by_doi |= {_norm_doi(r["doi"]): r["id"] for r in rows if r.get("doi")}

    known_ids = list(set(by_norm.values()) | set(by_doi.values()))
    posted: set[str] = set()
    for batch in _chunked(known_ids):
        rows = (
            svc.table("paper_posts")
            .select("paper_id")
            .eq("team_id", team_id)
            .in_("paper_id", batch)
            .execute()
            .data
            or []
        )
        posted |= {r["paper_id"] for r in rows}

    out: list[BibEntryPreview] = []
    seen: set[str] = set()  # within-file dedupe key (doi, else normalised url)

    for e in entries:
        ident = e.identifier
        if not ident:
            out.append(_preview(e, "rejected", "No DOI or URL"))
            continue

        doi = _norm_doi(e.doi)
        key = doi or norms[ident]
        if key in seen:
            out.append(_preview(e, "duplicate", "Listed twice in this file"))
            continue
        seen.add(key)

        paper_id = by_norm.get(norms[ident]) or (by_doi.get(doi) if doi else None)
        if paper_id and paper_id in posted:
            out.append(_preview(e, "duplicate", "Already in this lab"))
        elif not e.doi:
            out.append(_preview(e, "no_doi", "No DOI — will be matched on its URL"))
        else:
            out.append(_preview(e, "new"))
    return out


@app.post("/import/bibtex/preflight", response_model=PreflightResponse)
def bibtex_preflight(
    req: PreflightRequest, token: str = Depends(require_token)
) -> PreflightResponse:
    """What *would* happen. Writes nothing."""
    _require_member(token, req.team_id)

    parsed = bib.parse_bibtex(req.bibtex)
    previews = _classify(parsed.entries, req.team_id)
    for key, reason in parsed.rejected:
        previews.append(
            BibEntryPreview(
                key=key,
                title=None,
                authors=[],
                venue=None,
                year=None,
                published_at=None,
                doi=None,
                url=None,
                status="rejected",
                reason=reason,
            )
        )

    counts = Counter(p.status for p in previews)
    return PreflightResponse(
        entries=previews,
        new=counts["new"],
        duplicates=counts["duplicate"],
        no_doi=counts["no_doi"],
        rejected=counts["rejected"],
        importable=counts["new"] + counts["no_doi"],
    )


@app.post("/import/bibtex", response_model=ImportResponse)
def bibtex_import(
    req: ImportRequest, background: BackgroundTasks, token: str = Depends(require_token)
) -> ImportResponse:
    """Commit the import. Papers already in the lab are skipped, not duplicated."""
    # Before anything is written: `_upsert_paper` runs as the service role and would
    # otherwise insert rows into the global `papers` table for a non-member, only for
    # the post itself to be refused by RLS and swallowed as a generic "failed".
    user_id = _require_member(token, req.team_id)

    parsed = bib.parse_bibtex(req.bibtex)
    svc = service_client()
    imported = skipped = failed = 0
    seen: set[str] = set()  # same within-file dedupe the pre-flight reported
    to_embed: list[tuple[str, str | None, str | None]] = []

    for e in parsed.entries:
        ident = e.identifier
        if not ident:
            failed += 1
            continue
        try:
            url = _clean_url(ident)
            url_norm = _normalize_key(url)

            key = _norm_doi(e.doi) or url_norm
            if key in seen:
                skipped += 1
                continue
            seen.add(key)

            # BibTeX metadata is already structured, so we trust it and skip the
            # network entirely — a 400-entry import must not become 400 HTTP fetches.
            # Anything thin (no abstract) is picked up by the existing backfill.
            meta = PaperMetadata(
                url=url,
                title=e.title,
                authors=e.authors,
                venue=e.venue,
                year=e.year,
                doi=e.doi,
                abstract=e.abstract,
                keywords=e.keywords,
                source="bibtex",
            )
            paper_id, needs_embedding = _upsert_paper(meta, url, url_norm)

            if e.published_at:
                svc.table("papers").update({"published_at": e.published_at.isoformat()}).eq(
                    "id", paper_id
                ).is_("published_at", "null").execute()

            _post_id, already, _source = _create_post(
                token, req.team_id, paper_id, user_id, None, source="bibtex"
            )
            if already:
                skipped += 1
                continue
            imported += 1

            if needs_embedding:
                to_embed.append((paper_id, meta.title, meta.abstract))
        except Exception as exc:  # noqa: BLE001 — one bad entry must not fail the import
            log.warning("bibtex import: %s failed: %s", e.key, exc)
            failed += 1

    # One batched call per chunk, not one Voyage request per paper: a 400-paper import
    # would otherwise fire 400 separate embedding requests.
    if to_embed and get_api_settings().voyage_api_key:
        background.add_task(_embed_batch, to_embed)

    return ImportResponse(imported=imported, skipped=skipped, failed=failed + len(parsed.rejected))


def _embed_batch(papers: list[tuple[str, str | None, str | None]]) -> None:
    """Embed an imported batch. Failures are logged; the backfill retries anything
    still missing `embedded_at`."""
    svc = service_client()
    for chunk in [papers[i : i + 64] for i in range(0, len(papers), 64)]:
        texts, ids = [], []
        for paper_id, title, abstract in chunk:
            text = embeddings.paper_text(title, abstract)
            if text:
                texts.append(text)
                ids.append(paper_id)
        if not texts:
            continue
        try:
            vectors = embeddings.embed_texts(texts)
        except Exception as exc:  # noqa: BLE001
            log.warning("bibtex import: embedding a batch of %d failed: %s", len(texts), exc)
            continue
        now = datetime.now(UTC).isoformat()
        for paper_id, vector in zip(ids, vectors, strict=True):
            try:
                svc.table("papers").update({"embedding": vector, "embedded_at": now}).eq(
                    "id", paper_id
                ).is_("embedded_at", "null").execute()
            except Exception as exc:  # noqa: BLE001
                log.warning("bibtex import: storing embedding for %s failed: %s", paper_id, exc)
