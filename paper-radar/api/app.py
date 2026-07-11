"""Atlas API.

A thin FastAPI service in front of the existing ``paper_radar`` ingest logic.

  * ``POST /resolve`` — URL → metadata + dedup key (no writes).
  * ``POST /posts``   — post a paper into a lab: verify the caller's Supabase
    JWT, upsert the global ``papers`` row (service role, dedup on DOI/url_norm),
    and insert the ``paper_post`` as that user so RLS enforces membership.

Enrichment (summary/tags) and embedding run later in a worker.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from paper_radar.ingest.metadata import PaperMetadata, fetch_metadata
from paper_radar.ingest.pdf_extract import _clean_url, _normalize_key

from .supa import get_user_id, service_client, user_client

app = FastAPI(title="Atlas API", version="0.1.0")

# The Vite dev server calls this cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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


# --- auth dependency -------------------------------------------------------


def require_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1]


# --- helpers ---------------------------------------------------------------


def _resolved(meta: PaperMetadata, url: str, url_norm: str) -> ResolvedPaper:
    fields = {k: v for k, v in asdict(meta).items() if k != "url"}
    return ResolvedPaper(url=meta.url, url_norm=url_norm, **fields)


def _upsert_paper(meta: PaperMetadata, url: str, url_norm: str) -> str:
    """Find the canonical paper (by url_norm, then DOI) or insert it. Service role."""
    svc = service_client()

    found = svc.table("papers").select("id").eq("url_norm", url_norm).limit(1).execute()
    if found.data:
        return found.data[0]["id"]
    if meta.doi:
        by_doi = svc.table("papers").select("id").eq("doi", meta.doi).limit(1).execute()
        if by_doi.data:
            return by_doi.data[0]["id"]

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
        return inserted.data[0]["id"]
    except Exception:
        # Lost a race on the url_norm unique constraint — re-read the winner.
        again = svc.table("papers").select("id").eq("url_norm", url_norm).limit(1).execute()
        if again.data:
            return again.data[0]["id"]
        raise


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
def create_post(req: PostRequest, token: str = Depends(require_token)) -> PostResponse:
    """Post a paper into a lab (JWT-verified; RLS enforces lab membership)."""
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    url = _clean_url(req.url)
    url_norm = _normalize_key(url)
    meta = fetch_metadata(url)
    paper_id = _upsert_paper(meta, url, url_norm)
    post_id, already = _create_post(token, req.team_id, paper_id, user_id, req.note)

    return PostResponse(
        post_id=post_id,
        paper_id=paper_id,
        already_posted=already,
        paper=_resolved(meta, url, url_norm),
    )
