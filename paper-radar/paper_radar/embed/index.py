"""FAISS vector index + UMAP 2-D projection.

Vectors are assumed L2-normalized (see ``embed.py``), so an inner-product index
(``IndexFlatIP``) ranks by cosine similarity. The index is flat (exact) which is
plenty for a single lab's paper collection.
"""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


def build_index(embeddings: np.ndarray) -> faiss.Index:
    """Build a flat inner-product FAISS index from ``(n, dim)`` embeddings."""
    if embeddings.ndim != 2 or embeddings.shape[0] == 0:
        raise ValueError("embeddings must be a non-empty (n, dim) array")
    vecs = np.ascontiguousarray(embeddings, dtype=np.float32)
    index = faiss.IndexFlatIP(vecs.shape[1])
    index.add(vecs)
    return index


def save_index(index: faiss.Index, path: str | Path) -> None:
    """Persist a FAISS index to disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))


def load_index(path: str | Path) -> faiss.Index:
    """Load a FAISS index from disk."""
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


def compute_umap(
    embeddings: np.ndarray,
    *,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> np.ndarray:
    """Project ``(n, dim)`` embeddings to ``(n, 2)`` coordinates for plotting.

    ``n_neighbors`` is clamped for tiny collections (UMAP requires it to be < n).
    With fewer than 3 points UMAP is not meaningful, so a trivial layout is
    returned instead.
    """
    import umap  # imported lazily; pulls in numba

    n = embeddings.shape[0]
    if n == 0:
        return np.zeros((0, 2), dtype=np.float32)
    if n < 3:
        # Not enough points to embed; lay them out on a short line.
        return np.array([[float(i), 0.0] for i in range(n)], dtype=np.float32)

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=min(n_neighbors, n - 1),
        min_dist=min_dist,
        metric="cosine",
        random_state=random_state,
    )
    coords = reducer.fit_transform(np.ascontiguousarray(embeddings, dtype=np.float32))
    return np.ascontiguousarray(coords, dtype=np.float32)
