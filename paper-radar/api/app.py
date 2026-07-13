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
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from paper_radar.ingest import bibtex as bib
from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.pdf_extract import _clean_url, _normalize_key

from . import embeddings, enrichment, maps
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


class PostRequest(BaseModel):
    url: str
    team_id: str
    note: str | None = None


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
    by_venue: list[dict]   # [{venue, count}] top venues
    by_year: list[dict]    # [{year, count}]
    by_lab: list[dict]     # [{lab, count}] top last-authors (proxy for source lab)
    by_tag: list[dict]     # [{tag, count}] top LLM tags


class OverviewResponse(BaseModel):
    points: list[OverviewPoint]
    clusters: list[Cluster]
    stats: OverviewStats
    total: int     # posts in the lab
    embedded: int  # posts whose paper has an embedding (points returned)


# The token dependency lives in `deps.py` (imported above) so routers can share it
# without importing this module; `require_token` is re-exported here for the many
# endpoints below that depend on it.

# --- helpers ---------------------------------------------------------------


def _resolved(meta: PaperMetadata, url: str, url_norm: str) -> ResolvedPaper:
    fields = {k: v for k, v in asdict(meta).items() if k != "url"}
    return ResolvedPaper(url=meta.url, url_norm=url_norm, **fields)


def _upsert_paper(meta: PaperMetadata, url: str, url_norm: str) -> tuple[str, bool]:
    """Find the canonical paper (by url_norm, then DOI) or insert it. Service role.

    Returns ``(paper_id, needs_embedding)`` — an existing row may still lack an
    embedding (posted before embeddings landed, or a previous embed failed).
    """
    svc = service_client()

    found = (
        svc.table("papers").select("id, embedded_at").eq("url_norm", url_norm).limit(1).execute()
    )
    if found.data:
        return found.data[0]["id"], found.data[0]["embedded_at"] is None
    if meta.doi:
        by_doi = (
            svc.table("papers").select("id, embedded_at").eq("doi", meta.doi).limit(1).execute()
        )
        if by_doi.data:
            return by_doi.data[0]["id"], by_doi.data[0]["embedded_at"] is None

    row = {
        "url": url,
        "url_norm": url_norm,
        "doi": meta.doi,
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
    """Insert the paper_post as the user (RLS enforces membership). Returns (id, already).

    `source` records how the paper got here ("web" | "bibtex" | "teams_pdf"), so a
    400-paper import can be told apart from 400 people posting.
    """
    uc = user_client(token)

    existing = (
        uc.table("paper_posts")
        .select("id")
        .eq("paper_id", paper_id)
        .eq("team_id", team_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"], True

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
    return inserted.data[0]["id"], False


# --- routes ----------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/resolve", response_model=ResolvedPaper)
def resolve(req: ResolveRequest) -> ResolvedPaper:
    """Resolve a pasted URL to metadata + its normalized dedup key."""
    url = _clean_url(req.url)
    meta = fetch_metadata(url, network=req.network)
    return _resolved(meta, url, _normalize_key(url))


@app.post("/posts", response_model=PostResponse)
def create_post(
    req: PostRequest, background: BackgroundTasks, token: str = Depends(require_token)
) -> PostResponse:
    """Post a paper into a lab (JWT-verified; RLS enforces lab membership)."""
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    url = _clean_url(req.url)
    url_norm = _normalize_key(url)
    meta = fetch_metadata(url)
    paper_id, needs_embedding = _upsert_paper(meta, url, url_norm)
    post_id, already = _create_post(token, req.team_id, paper_id, user_id, req.note)

    # Embed + tag after responding so posting stays fast; each no-ops without
    # its key, and the backfill scripts cover anything skipped.
    if needs_embedding and get_api_settings().voyage_api_key:
        background.add_task(_embed_and_store, paper_id, meta.title, meta.abstract)
    if needs_embedding:
        background.add_task(_enrich_and_store, paper_id, meta.title, meta.abstract)

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
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query must not be empty")

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
    if not get_user_id(token):
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

    try:
        query_vector = embeddings.embed_query(query)
    except embeddings.EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=f"Embeddings unavailable: {exc}") from exc

    rows = (
        service_client()
        .rpc("match_papers", {"p_team": req.team_id, "p_query": query_vector, "p_limit": 100000})
        .execute()
        .data
        or []
    )
    return SimilarityResponse(similarities={r["paper_id"]: r["similarity"] for r in rows})


def _last_author_lab(authors: list) -> str | None:
    """Last author as a rough proxy for 'the lab that produced the paper' (§4.1a)."""
    return authors[-1] if authors else None


def _engagement_counts(uc, team_id: str, paper_ids: list[str]) -> dict[str, tuple[int, int]]:
    """(reactions, comments) per paper for the team, RLS-scoped. {} if no ids."""
    if not paper_ids:
        return {}
    counts: dict[str, list[int]] = {pid: [0, 0] for pid in paper_ids}
    # Filter to the loaded papers (not the whole team) — fewer rows, and avoids
    # a truncated count if a busy lab hits PostgREST's max-rows.
    rx = (
        uc.table("reactions").select("paper_id").eq("team_id", team_id)
        .in_("paper_id", paper_ids).execute().data
        or []
    )
    cm = (
        uc.table("comments").select("paper_id").eq("team_id", team_id)
        .in_("paper_id", paper_ids).execute().data
        or []
    )
    for r in rx:
        if r["paper_id"] in counts:
            counts[r["paper_id"]][0] += 1
    for c in cm:
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
    rows = (
        uc.table("paper_posts").select(_OVERVIEW_COLS).eq("team_id", team_id).execute().data or []
    )
    return _build_overview(uc, team_id, rows)


class MapOverviewResponse(OverviewResponse):
    map_id: str
    name: str
    seed: str
    visibility: str
    new_this_week: int  # members posted in the last 7 days


@app.get("/maps/{map_id}/overview", response_model=MapOverviewResponse)
def map_overview(map_id: str, token: str = Depends(require_token)) -> MapOverviewResponse:
    """The scoped map: a t-SNE + sub-themes over just the map's member papers.

    Membership comes from the `map_members` RPC (seed similarity + pins − excludes);
    RLS on `maps` means a caller who can't see the map gets a 404.
    """
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    uc = user_client(token)

    rows = (
        uc.table("maps").select("id, team_id, name, seed, visibility").eq("id", map_id).limit(1)
        .execute().data or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")
    m = rows[0]

    members = uc.rpc("map_members", {"p_map": map_id, "p_limit": 500}).execute().data or []
    member_ids = [x["paper_id"] for x in members]
    if not member_ids:
        base = OverviewResponse(
            points=[], clusters=[], stats=_compute_stats([]), total=0, embedded=0
        )
        return MapOverviewResponse(
            **base.model_dump(), map_id=map_id, name=m["name"], seed=m["seed"],
            visibility=m["visibility"], new_this_week=0,
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
        visibility=m["visibility"], new_this_week=new_this_week,
    )


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
        uc.table("reactions").select("paper_id, emoji, created_at")
        .eq("team_id", team_id).eq("user_id", user_id).execute().data or []
    ):
        base = _W_SKEPTIC if r.get("emoji") == "🤔" else _W_REACTION
        add(r["paper_id"], base * _recency_decay(_parse_ts(r.get("created_at")), now))
    for c in (
        uc.table("comments").select("paper_id, created_at")
        .eq("team_id", team_id).eq("author_id", user_id).execute().data or []
    ):
        add(c["paper_id"], _W_COMMENT * _recency_decay(_parse_ts(c.get("created_at")), now))
    for s in (
        uc.table("paper_status").select("paper_id, status, updated_at")
        .eq("team_id", team_id).eq("user_id", user_id).execute().data or []
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
        user_client(token)      # as the caller, so RLS answers the question honestly
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
    dois = [e.doi for e in entries if e.doi]

    by_norm: dict[str, str] = {}
    by_doi: dict[str, str] = {}
    for batch in _chunked(list(set(norms.values()))):
        rows = (
            svc.table("papers").select("id, url_norm").in_("url_norm", batch).execute().data
            or []
        )
        by_norm |= {r["url_norm"]: r["id"] for r in rows}
    for batch in _chunked(list(set(dois))):
        rows = svc.table("papers").select("id, doi").in_("doi", batch).execute().data or []
        by_doi |= {r["doi"]: r["id"] for r in rows if r.get("doi")}

    known_ids = list(set(by_norm.values()) | set(by_doi.values()))
    posted: set[str] = set()
    for batch in _chunked(known_ids):
        rows = (
            svc.table("paper_posts").select("paper_id")
            .eq("team_id", team_id).in_("paper_id", batch).execute().data or []
        )
        posted |= {r["paper_id"] for r in rows}

    out: list[BibEntryPreview] = []
    seen: set[str] = set()   # within-file dedupe key (doi, else normalised url)

    for e in entries:
        ident = e.identifier
        if not ident:
            out.append(_preview(e, "rejected", "No DOI or URL"))
            continue

        key = e.doi or norms[ident]
        if key in seen:
            out.append(_preview(e, "duplicate", "Listed twice in this file"))
            continue
        seen.add(key)

        paper_id = by_norm.get(norms[ident]) or (by_doi.get(e.doi) if e.doi else None)
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
                key=key, title=None, authors=[], venue=None, year=None, published_at=None,
                doi=None, url=None, status="rejected", reason=reason,
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

            key = e.doi or url_norm
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
                svc.table("papers").update(
                    {"published_at": e.published_at.isoformat()}
                ).eq("id", paper_id).is_("published_at", "null").execute()

            _post_id, already = _create_post(
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
