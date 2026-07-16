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
from paper_radar.ingest.urls import _clean_url, _normalize_key

from . import embeddings, enrichment, maps, teams_integration
from . import map_summary as map_summary_mod
from . import overview as overview_mod
from .config import get_api_settings
from .deps import require_token
from .supa import get_user_id, service_client, user_client

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
    "code_url, data_url, enriched_at"
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
    """Clean + SSRF-check a URL we're about to fetch, as a 400 on rejection.

    `resolve=False` keeps this to the syntactic checks (scheme, literal internal IP,
    internal name) for a fast, clean 400 — the DNS-resolution check runs again inside
    `fetch_metadata` (which every fetch path shares), so a public name pointing at an
    internal address is still caught there without resolving the host twice here.
    """
    try:
        return _clean_url(url_guard.validate_public_url(raw, resolve=False))
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
    try:
        service_client().table("papers").update(patch).eq("id", row["id"]).execute()
    except Exception as exc:  # a unique-DOI clash shouldn't fail the post
        log.warning("repairing untitled paper %s failed: %s", row["id"], exc)
        return False
    return True


def _norm_doi(doi: str | None) -> str | None:
    """DOIs are case-insensitive (ISO 26324), so store and compare them folded.

    AACR registers "10.1158/2159-8290.CD-25-1745" while PubMed reports it
    lowercased; matching case-sensitively let the same paper in twice — once via
    the publisher link, once via PubMed. Strip the resolver prefix too, so
    "https://doi.org/10.x/y" and "10.x/y" are the same key.
    """
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix) :]
    return d.strip("/") or None


def _upsert_paper(meta: PaperMetadata, url: str, url_norm: str) -> tuple[str, bool]:
    """Find the canonical paper (by url_norm, then DOI) or insert it. Service role.

    Returns ``(paper_id, needs_embedding)`` — an existing row may still lack an
    embedding (posted before embeddings landed, or a previous embed failed).
    """
    svc = service_client()

    found = (
        svc.table("papers")
        .select("id, title, embedded_at")
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
            .select("id, title, embedded_at")
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
        url = _clean_url(req.url)
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
            title=meta.title,
            authors=meta.authors,
            venue=meta.venue,
            year=meta.year,
            note=req.note,
            posted_by_id=user_id,
        )

    return PostResponse(
        post_id=post_id,
        paper_id=paper_id,
        already_posted=already,
        paper=_resolved(meta, url, url_norm),
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
    read_status: str | None = None  # 'to_read'|'reading'|'read'|None, for the caller
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
_W_BOOKMARK = 1.5  # to_read — an explicit, deliberate save
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


def _engagement_weights(uc, user_id: str, team_id: str) -> dict[str, float]:
    """Per-paper positive-interest weight for the user in this lab, blending signal
    strength (save > reaction > comment > read) with recency decay."""
    now = datetime.now(UTC)
    weights: dict[str, float] = {}

    def add(paper_id: str, w: float) -> None:
        weights[paper_id] = weights.get(paper_id, 0.0) + w

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
    for s in (
        uc.table("paper_status")
        .select("paper_id, status, updated_at")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    ):
        base = _W_BOOKMARK if s.get("status") == "to_read" else _W_READ
        add(s["paper_id"], base * _recency_decay(_parse_ts(s.get("updated_at")), now))
    return weights


def _taste_vector(uc, user_id: str, weights: dict[str, float]) -> list[float] | None:
    """Per-user taste vector: a confidence-weighted blend of the profile embedding
    and a recency-/strength-weighted engagement centroid over ``weights``
    (the caller's `_engagement_weights`, computed once per request).

    The engagement side's weight grows with how many papers the user has actually
    engaged with, so a single incidental interaction can't hijack the feed while
    the profile carries a sparse user. Missing either side falls back to the other;
    missing both returns None (cold start → recency fallback)."""
    prof = (
        uc.table("profiles").select("profile_vec").eq("id", user_id).limit(1).execute().data or []
    )
    profile_vec = _parse_vec(prof[0]["profile_vec"]) if prof else None
    profile_np = (
        _l2norm(np.asarray(profile_vec, dtype=np.float32)) if profile_vec is not None else None
    )

    centroid_np = None
    n_engaged = 0
    if weights:
        rows = (
            uc.table("papers").select("id, embedding").in_("id", list(weights)).execute().data or []
        )
        acc: np.ndarray | None = None
        wsum = 0.0
        for r in rows:
            w = weights.get(r["id"], 0.0)
            if w <= 0 or not r.get("embedding"):
                continue
            v = _l2norm(np.asarray(_parse_vec(r["embedding"]), dtype=np.float32))
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
    """The user's saved (to_read) papers, ranked by taste similarity."""
    saved = (
        uc.table("paper_status")
        .select("paper_id")
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("status", "to_read")
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


def _recency_fallback(uc, team_id: str, seen: set[str], limit: int) -> RecommendationsResponse:
    """Cold start (no profile, no engagement): recent unseen posts, newest first.

    ``seen`` is the engaged-paper set the discover feed excludes (the SQL RPC does
    this server-side; here it comes from the request's `_engagement_weights` keys —
    every engagement row gets a nonzero weight, so the keys are exactly the seen set)."""
    rows = (
        uc.table("paper_posts")
        .select("id, paper_id, posted_at")
        .eq("team_id", team_id)
        .order("posted_at", desc=True)
        .limit(limit * 4)
        .execute()
        .data
        or []
    )
    order = [r["id"] for r in rows if r["paper_id"] not in seen][:limit]
    return _hydrate(uc, order, {}, cold=True)


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
    weights = _engagement_weights(uc, user_id, team_id)
    taste = _taste_vector(uc, user_id, weights)

    if scope == "reading_list":
        return _reading_list_ranked(uc, user_id, team_id, taste, limit)

    if taste is None:
        return _recency_fallback(uc, team_id, set(weights), limit)

    matches = (
        uc.rpc("recommend_papers", {"p_team": team_id, "p_query": taste, "p_limit": limit})
        .execute()
        .data
        or []
    )
    sims = {m["post_id"]: m["similarity"] for m in matches}
    return _hydrate(uc, [m["post_id"] for m in matches], sims, cold=False)


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
