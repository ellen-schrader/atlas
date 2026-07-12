"""Atlas API.

A thin FastAPI service in front of the existing ``paper_radar`` ingest logic.

  * ``POST /resolve``         — URL → metadata + dedup key (no writes).
  * ``POST /posts``           — post a paper into a lab: verify the caller's
    Supabase JWT, upsert the global ``papers`` row (service role, dedup on
    DOI/url_norm), insert the ``paper_post`` as that user so RLS enforces
    membership, and embed the paper in the background.
  * ``POST /search/semantic`` — embed a query and rank the lab's posts by
    cosine similarity (``match_papers`` RPC, caller's RLS).
  * ``GET  /map``             — 2-D UMAP layout of the lab's embedded papers.

Enrichment (summary/tags) still lands later in a worker.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.pdf_extract import _clean_url, _normalize_key

from . import embeddings, enrichment
from . import overview as overview_mod
from .config import get_api_settings
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


# --- auth dependency -------------------------------------------------------


def require_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1]


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


def _create_post(token: str, team_id: str, paper_id: str, user_id: str, note: str | None):
    """Insert the paper_post as the user (RLS enforces membership). Returns (id, already)."""
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
        "source": "web",
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


@app.get("/overview", response_model=OverviewResponse)
def overview(team_id: str, token: str = Depends(require_token)) -> OverviewResponse:
    """Insights overview for a lab: UMAP + named clusters + stats (RLS-scoped).

    The UMAP + clustering + cluster names are cached per team by the embedded
    set; engagement and stats are computed fresh so they stay live.
    """
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    uc = user_client(token)
    cols = (
        "paper_id, posted_at, "
        "papers(id, title, venue, year, keywords, tags, authors, embedding, embedded_at)"
    )
    rows = (
        uc.table("paper_posts")
        .select(cols)
        .eq("team_id", team_id)
        .execute()
        .data
        or []
    )
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
