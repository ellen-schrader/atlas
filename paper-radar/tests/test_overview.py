"""Offline tests for the overview compute (clustering, naming fallback, cache)."""

from __future__ import annotations

import numpy as np

from api import overview as ov
from paper_radar.config import Settings
from paper_radar.embed.index import auto_k, cluster_embeddings


def test_auto_k_scales_and_clamps():
    assert auto_k(3) == 1
    assert auto_k(100) == 4      # floor
    assert auto_k(395) == 8      # round(7.9)
    assert auto_k(1000) == 8     # clamped to the palette size


def test_cluster_embeddings_deterministic_and_partitions():
    rng = np.random.default_rng(0)
    # three separated blobs
    vecs = np.vstack([
        rng.normal(loc, 0.05, size=(20, 8)) for loc in ([5, 0, 0, 0, 0, 0, 0, 0],
                                                         [0, 5, 0, 0, 0, 0, 0, 0],
                                                         [0, 0, 5, 0, 0, 0, 0, 0])
    ]).astype(np.float32)
    a = cluster_embeddings(vecs, k=3)
    b = cluster_embeddings(vecs, k=3)
    assert (a == b).all()  # deterministic
    assert set(a.tolist()) == {0, 1, 2}
    # each true blob is a single cluster
    for start in (0, 20, 40):
        assert len(set(a[start : start + 20].tolist())) == 1


def test_name_clusters_falls_back_without_key(monkeypatch):
    no_key = Settings(_env_file=None, anthropic_api_key="")
    monkeypatch.setattr(ov, "get_llm_settings", lambda: no_key)
    names = ov.name_clusters([{"id": 0, "titles": ["A"]}, {"id": 1, "titles": ["B"]}])
    assert names[0]["label"] == "Theme 1"
    assert names[1]["label"] == "Theme 2"


def test_cached_layout_memoizes(monkeypatch):
    calls = {"n": 0}

    def fake_compute(papers):
        calls["n"] += 1
        return ({p["id"]: {"x": 0.0, "y": 0.0, "cluster": 0} for p in papers}, [])

    monkeypatch.setattr(ov, "compute_layout", fake_compute)
    ov._layout_cache._d.clear()
    papers = [{"id": "p1", "embedded_at": "t1"}, {"id": "p2", "embedded_at": "t1"}]
    ov.cached_layout("team", papers)
    ov.cached_layout("team", papers)
    assert calls["n"] == 1  # second call served from cache
    # a re-embed (new embedded_at) busts the cache
    ov.cached_layout("team", [{"id": "p1", "embedded_at": "t2"}, {"id": "p2", "embedded_at": "t1"}])
    assert calls["n"] == 2
