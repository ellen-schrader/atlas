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


class _FakeTrends:
    """Tiny in-memory stand-in for the Supabase client's `trends` table."""

    def __init__(self):
        self.rows: list[dict] = []
        self._op = None
        self._filters: dict = {}
        self._not_null: str | None = None
        self._pending: list[dict] = []

    def table(self, _name):
        self._op = None
        self._filters = {}
        self._not_null = None
        self._pending = []
        return self

    def select(self, _cols):
        self._op = "select"
        return self

    def delete(self):
        self._op = "delete"
        return self

    def insert(self, rows):
        self._op = "insert"
        self._pending = rows
        return self

    def eq(self, k, v):
        self._filters[k] = v
        return self

    @property
    def not_(self):
        return self

    def is_(self, col, _val):  # only used as .not_.is_(col, "null") → col is not null
        self._not_null = col
        return self

    def execute(self):
        if self._op == "insert":
            self.rows.extend(self._pending)
            return type("R", (), {"data": self._pending})
        if self._op == "delete":
            self.rows = [r for r in self.rows if not self._match(r)]
            return type("R", (), {"data": []})
        return type("R", (), {"data": [r for r in self.rows if self._match(r)]})

    def _match(self, row):
        if not all(row.get(k) == v for k, v in self._filters.items()):
            return False
        return self._not_null is None or row.get(self._not_null) is not None


def test_names_persist_and_reload(monkeypatch):
    fake = _FakeTrends()
    monkeypatch.setattr(ov, "service_client", lambda: fake)
    names = {0: {"label": "A", "description": "da"}, 1: {"label": "B", "description": "db"}}
    ids = {0: ["p1"], 1: ["p2"]}

    assert ov._load_names("team", "sig") is None  # nothing persisted yet
    ov._store_names("team", "sig", names, ids)
    assert ov._load_names("team", "sig") == names  # round-trips → no Claude call next time
    assert ov._load_names("team", "other-sig") is None  # a changed clustering misses


def test_signature_stable_regardless_of_input_order():
    a = [{"id": "p1", "embedded_at": "t1"}, {"id": "p2", "embedded_at": "t2"}]
    b = list(reversed(a))
    assert ov._signature(a) == ov._signature(b)
    # a re-embed (different embedded_at) changes the signature
    c = [{"id": "p1", "embedded_at": "t9"}, {"id": "p2", "embedded_at": "t2"}]
    assert ov._signature(a) != ov._signature(c)


def test_cached_layout_memoizes(monkeypatch):
    calls = {"n": 0}

    def fake_compute(team_id, papers):
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
