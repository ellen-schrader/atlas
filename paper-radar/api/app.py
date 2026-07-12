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

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.pdf_extract import _clean_url, _normalize_key

from . import embeddings
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


class MapPoint(BaseModel):
    paper_id: str
    x: float
    y: float
    title: str | None = None
    venue: str | None = None
    year: int | None = None
    tags: list[str] = []


class MapResponse(BaseModel):
    points: list[MapPoint]
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


def _parse_vector(value: object) -> list[float]:
    """An embedding as PostgREST returns it: a '[...]' string (or already a list)."""
    if isinstance(value, str):
        return json.loads(value)
    return value  # type: ignore[return-value]


class MapCache:
    """Per-team cache of UMAP layouts, keyed by the exact set of embedded papers.

    The key is ``frozenset of (paper_id, embedded_at)`` — a new post, a removed
    post, or a re-embed all produce a different key and force a recompute.
    """

    def __init__(self) -> None:
        self._layouts: dict[str, tuple[frozenset, list[MapPoint]]] = {}

    def get(self, team_id: str, key: frozenset) -> list[MapPoint] | None:
        entry = self._layouts.get(team_id)
        if entry and entry[0] == key:
            return entry[1]
        return None

    def put(self, team_id: str, key: frozenset, points: list[MapPoint]) -> None:
        self._layouts[team_id] = (key, points)


_map_cache = MapCache()


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

    # Embed after responding so posting stays fast; skipped without a key
    # (dev without embeddings) — the backfill script covers those papers.
    if needs_embedding and get_api_settings().voyage_api_key:
        background.add_task(_embed_and_store, paper_id, meta.title, meta.abstract)

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


@app.get("/map", response_model=MapResponse)
def map_overview(team_id: str, token: str = Depends(require_token)) -> MapResponse:
    """2-D UMAP layout of the lab's embedded papers (per-lab; RLS-scoped).

    Layouts are cached per team and recomputed only when the set of embedded
    papers changes (see MapCache).
    """
    if not get_user_id(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    uc = user_client(token)
    rows = (
        uc.table("paper_posts")
        .select("paper_id, papers(id, title, venue, year, tags, embedding, embedded_at)")
        .eq("team_id", team_id)
        .execute()
        .data
        or []
    )
    total = len(rows)
    papers = [r["papers"] for r in rows if r.get("papers") and r["papers"].get("embedding")]
    if not papers:
        return MapResponse(points=[], total=total, embedded=0)
    # Sort for a deterministic layout: UMAP has a fixed seed, but the layout
    # still depends on input order.
    papers.sort(key=lambda p: p["id"])

    key = frozenset((p["id"], p["embedded_at"]) for p in papers)
    points = _map_cache.get(team_id, key)
    if points is None:
        vectors = np.array([_parse_vector(p["embedding"]) for p in papers], dtype=np.float32)
        # Imported lazily: pulls in umap/numba (and the first fit pays the JIT).
        from paper_radar.embed.index import compute_umap

        coords = compute_umap(vectors)
        points = [
            MapPoint(
                paper_id=p["id"],
                x=float(x),
                y=float(y),
                title=p.get("title"),
                venue=p.get("venue"),
                year=p.get("year"),
                tags=p.get("tags") or [],
            )
            for p, (x, y) in zip(papers, coords, strict=True)
        ]
        _map_cache.put(team_id, key, points)

    return MapResponse(points=points, total=total, embedded=len(papers))
