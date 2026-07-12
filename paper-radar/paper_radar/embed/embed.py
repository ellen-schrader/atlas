"""Local text embeddings via sentence-transformers.

The model (default ``BAAI/bge-small-en-v1.5``) is loaded lazily and cached so we
pay the load cost only once per process. Embeddings are L2-normalized, which lets
us use inner-product FAISS search as cosine similarity (see ``index.py``).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..config import get_settings
from ..models import Paper


@lru_cache(maxsize=2)
def get_model(model_name: str | None = None):
    """Load (and cache) a SentenceTransformer model.

    Imported lazily so that merely importing this module -- or running the
    Streamlit shell -- does not pull in torch.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is not installed; the local embedding "
            "pipeline needs the legacy extra: uv sync --extra dev --extra legacy"
        ) from exc

    name = model_name or get_settings().embedding_model
    return SentenceTransformer(name)


def paper_text(paper: Paper) -> str:
    """The text we embed for a paper: title + summary (falling back to title)."""
    parts = [p for p in (paper.title, paper.summary) if p]
    return "\n\n".join(parts) if parts else (paper.url or "")


def embed_texts(
    texts: list[str],
    *,
    model_name: str | None = None,
    is_query: bool = False,
) -> np.ndarray:
    """Embed a list of texts into an ``(n, dim)`` float32, L2-normalized array.

    Set ``is_query=True`` for search queries so the bge query prefix is applied.
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = get_model(model_name)
    if is_query:
        prefix = get_settings().query_prefix
        texts = [prefix + t for t in texts]
    vecs = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return np.ascontiguousarray(vecs, dtype=np.float32)


def embed_text(text: str, *, model_name: str | None = None, is_query: bool = False) -> np.ndarray:
    """Embed a single string; returns a 1-D ``(dim,)`` array."""
    return embed_texts([text], model_name=model_name, is_query=is_query)[0]


def embed_papers(papers: list[Paper], *, model_name: str | None = None) -> np.ndarray:
    """Embed a list of papers (title + summary) into an ``(n, dim)`` array."""
    return embed_texts([paper_text(p) for p in papers], model_name=model_name)
