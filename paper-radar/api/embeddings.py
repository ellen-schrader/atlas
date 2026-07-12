"""Paper embeddings via the Voyage AI HTTP API.

Anthropic has no embeddings endpoint; Voyage is its recommended provider
(docs/EMBEDDINGS_PLAN.md §1.1). ``voyage-4`` returns 1024-dim, L2-normalized
vectors, matching the schema's ``vector(1024)`` columns and cosine HNSW index.

stdlib-only (urllib), like ``ingest/metadata.py`` — the interface below is the
swap point if a scientific model (SPECTER2/SciNCL) wins the later benchmark.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from .config import ApiSettings, get_api_settings

log = logging.getLogger(__name__)

# Batches are deliberately small: the free tier caps tokens-per-minute, and one
# large batch of abstracts can exceed it in a single request. Small batches +
# 429 backoff keep us under the limit.
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
BATCH_SIZE = 16           # texts per request
_RETRIES = 6              # attempts per batch on 429/5xx
_TIMEOUT = 60             # seconds per request
_RATE_LIMIT_WAIT = 30     # fallback seconds to wait on a 429 with no Retry-After
_RETRYABLE = {429, 500, 502, 503, 529}


class EmbeddingError(RuntimeError):
    """The embedding API could not produce vectors."""


def paper_text(title: str | None, abstract: str | None) -> str:
    """The text we embed for a paper: title + abstract (falling back to title)."""
    parts = [p for p in (title, abstract) if p and p.strip()]
    return "\n\n".join(p.strip() for p in parts)


def embed_texts(
    texts: list[str],
    *,
    input_type: str = "document",
    settings: ApiSettings | None = None,
) -> list[list[float]]:
    """Embed ``texts`` into unit-norm float vectors, preserving order.

    ``input_type`` is "document" for corpus text and "query" for search
    queries — Voyage prepends a retrieval-tuned prompt per side.
    """
    settings = settings or get_api_settings()
    if settings.embedding_provider != "voyage":
        raise EmbeddingError(f"unknown embedding provider: {settings.embedding_provider!r}")
    if not settings.voyage_api_key:
        raise EmbeddingError("VOYAGE_API_KEY is not set")
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        vectors.extend(_embed_batch(texts[start : start + BATCH_SIZE], input_type, settings))
    return vectors


def embed_query(text: str, *, settings: ApiSettings | None = None) -> list[float]:
    """Embed a single search query."""
    return embed_texts([text], input_type="query", settings=settings)[0]


def _embed_batch(batch: list[str], input_type: str, settings: ApiSettings) -> list[list[float]]:
    payload = json.dumps(
        {"input": batch, "model": settings.embedding_model, "input_type": input_type}
    ).encode("utf-8")
    request = urllib.request.Request(
        VOYAGE_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.voyage_api_key}",
        },
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                body = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in _RETRYABLE and attempt < _RETRIES - 1:
                if exc.code == 429:
                    # Honor Retry-After when present; the free tier's per-minute
                    # limit needs a real cooldown, not a 1-2s backoff.
                    retry_after = (exc.headers or {}).get("Retry-After")
                    time.sleep(int(retry_after) if retry_after and retry_after.isdigit()
                               else _RATE_LIMIT_WAIT)
                else:
                    time.sleep(2**attempt)
                continue
            raise EmbeddingError(f"Voyage API returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < _RETRIES - 1:
                time.sleep(2**attempt)
                continue
            raise EmbeddingError(f"Voyage API request failed: {exc}") from exc
    else:  # pragma: no cover — the loop always breaks or raises
        raise EmbeddingError(f"Voyage API request failed: {last_error}")

    rows = sorted(body.get("data", []), key=lambda row: row["index"])
    vectors = [row["embedding"] for row in rows]
    if len(vectors) != len(batch):
        raise EmbeddingError(f"expected {len(batch)} embeddings, got {len(vectors)}")
    for vector in vectors:
        if len(vector) != settings.embedding_dim:
            raise EmbeddingError(
                f"model returned {len(vector)}-dim vectors; schema expects "
                f"{settings.embedding_dim} (vector(N) columns must match)"
            )
    return vectors
