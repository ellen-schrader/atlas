"""FAISS vector index.

Vectors are assumed L2-normalized (see ``embed.py``), so an inner-product index
(``IndexFlatIP``) ranks by cosine similarity. The index is flat (exact) which is
plenty for a single lab's paper collection.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import faiss


def _require_faiss():
    """Import faiss lazily: only the local-index CLI path needs it, so the API
    image (and dev test runs) work without the ``legacy`` extra installed."""
    try:
        import faiss
    except ImportError as exc:
        raise ImportError(
            "faiss is not installed; the local index pipeline needs the legacy "
            "extra: uv sync --extra dev --extra legacy"
        ) from exc
    return faiss


def build_index(embeddings: np.ndarray) -> faiss.Index:
    """Build a flat inner-product FAISS index from ``(n, dim)`` embeddings."""
    if embeddings.ndim != 2 or embeddings.shape[0] == 0:
        raise ValueError("embeddings must be a non-empty (n, dim) array")
    faiss = _require_faiss()
    vecs = np.ascontiguousarray(embeddings, dtype=np.float32)
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)
    return index


def save_index(index: faiss.Index, path: str | Path) -> None:
    """Persist a FAISS index to disk."""
    faiss = _require_faiss()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))


def load_index(path: str | Path) -> faiss.Index:
    """Load a FAISS index from disk."""
    faiss = _require_faiss()
    return faiss.read_index(str(Path(path)))


def search(
    index: faiss.Index,
    query: np.ndarray,
    k: int = 10,
) -> list[tuple[int, float]]:
    """Return the top-``k`` ``(row_id, score)`` for a single query vector.

    ``query`` may be shape ``(dim,)`` or ``(1, dim)``. Scores are cosine
    similarities in ``[-1, 1]``.
    """
    q = np.ascontiguousarray(query, dtype=np.float32).reshape(1, -1)
    k = min(k, index.ntotal)
    if k == 0:
        return []
    scores, ids = index.search(q, k)
    return [(int(i), float(s)) for i, s in zip(ids[0], scores[0], strict=True) if i != -1]
