"""Atlas API.

A thin FastAPI service in front of the existing ``paper_radar`` ingest logic.
This first slice resolves a pasted URL into paper metadata + the canonical dedup
key, reusing ``ingest/metadata.py`` and ``ingest/pdf_extract.py`` verbatim.
Persisting into Supabase (upsert paper + create paper_post) is the next slice.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from paper_radar.ingest.metadata import fetch_metadata
from paper_radar.ingest.pdf_extract import _clean_url, _normalize_key

app = FastAPI(title="Atlas API", version="0.1.0")

# The Vite dev server calls this cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/resolve", response_model=ResolvedPaper)
def resolve(req: ResolveRequest) -> ResolvedPaper:
    """Resolve a pasted URL to metadata + its normalized dedup key."""
    url = _clean_url(req.url)
    meta = fetch_metadata(url, network=req.network)
    fields = {k: v for k, v in asdict(meta).items() if k != "url"}
    return ResolvedPaper(url=meta.url, url_norm=_normalize_key(url), **fields)
