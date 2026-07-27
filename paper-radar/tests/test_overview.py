"""Offline tests for the overview compute (clustering, naming fallback, cache)."""

from __future__ import annotations

import subprocess
import sys

import numpy as np

from api import overview as ov
from paper_radar.config import Settings
from paper_radar.embed.index import auto_k, cluster_embeddings, compute_layout_2d


def test_auto_k_scales_and_clamps():
    assert auto_k(3) == 1
    assert auto_k(100) == 4      # floor
    assert auto_k(395) == 8      # round(7.9)
    assert auto_k(1000) == 8     # clamped to the palette size


def test_compute_layout_2d_shape_determinism_and_edges():
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(40, 16)).astype(np.float32)
    a = compute_layout_2d(vecs)
    b = compute_layout_2d(vecs)
    assert a.shape == (40, 2)
    assert a.dtype == np.float32
    assert (a == b).all()  # deterministic (fixed seed)
    # tiny collections skip the projection entirely
    assert compute_layout_2d(vecs[:0]).shape == (0, 2)
    assert (compute_layout_2d(vecs[:2]) == [[0.0, 0.0], [1.0, 0.0]]).all()
    # smallest projected size (perplexity must stay < n)
    assert compute_layout_2d(vecs[:3]).shape == (3, 2)
    # all-identical embeddings must not reach t-SNE (PCA init would divide by
    # zero std and segfault Barnes-Hut); expect the trivial line layout
    same = compute_layout_2d(np.ones((5, 16), dtype=np.float32))
    assert same.shape == (5, 2)
    assert np.isfinite(same).all()


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


_PAPERS = [{"id": "p1", "embedded_at": "t1"}, {"id": "p2", "embedded_at": "t1"}]
_POINTS = {"p1": {"x": 0.0, "y": 1.0, "cluster": 0}, "p2": {"x": 2.0, "y": 3.0, "cluster": 0}}


def _fresh_serving_state(monkeypatch, *, stored=None, names=None):
    """Reset cache/job state and stub the DB tiers + job spawn; returns the
    list of (mode, target, force) spawns."""
    spawns: list[tuple] = []
    ov._layout_cache._d.clear()
    ov._layout_jobs.clear()
    monkeypatch.setattr(ov, "load_layout", lambda t, s: stored)
    monkeypatch.setattr(ov, "_load_names", lambda t, s: names)

    def fake_ensure(mode, target, *, force=False):
        spawns.append((mode, target, force))

    monkeypatch.setattr(ov, "ensure_layout_job", fake_ensure)
    return spawns


def test_cached_layout_miss_spawns_job_and_reports_computing(monkeypatch):
    spawns = _fresh_serving_state(monkeypatch, stored=None)
    assert ov.cached_layout("team", _PAPERS, job=("lab", "team")) is None
    assert spawns == [("lab", "team", False)]


def test_cached_layout_serves_stored_layout_and_memoizes(monkeypatch):
    spawns = _fresh_serving_state(
        monkeypatch, stored=_POINTS, names={0: {"label": "A", "description": "d"}}
    )
    result = ov.cached_layout("team", _PAPERS, job=("lab", "team"))
    assert result is not None
    point_by_id, clusters = result
    assert point_by_id == _POINTS
    assert clusters == [{"id": 0, "label": "A", "description": "d", "size": 2}]
    assert spawns == []  # nothing to compute

    # second call is the hot tier: no DB reads at all
    monkeypatch.setattr(ov, "load_layout", lambda t, s: (_ for _ in ()).throw(AssertionError))
    assert ov.cached_layout("team", _PAPERS, job=("lab", "team")) == result


def test_cached_layout_falls_back_to_generic_names(monkeypatch):
    _fresh_serving_state(monkeypatch, stored=_POINTS, names=None)
    _points, clusters = ov.cached_layout("team", _PAPERS, job=("lab", "team"))
    assert clusters == [{"id": 0, "label": "Theme 1", "description": "", "size": 2}]


def test_cached_layout_mismatched_stored_layout_forces_recompute(monkeypatch):
    # stored row covers different paper ids than the request's set → corruption
    bad = {"zz": {"x": 0.0, "y": 0.0, "cluster": 0}}
    spawns = _fresh_serving_state(monkeypatch, stored=bad)
    assert ov.cached_layout("team", _PAPERS, job=("map", "m1")) is None
    assert spawns == [("map", "m1", True)]


def test_ensure_layout_job_dedupes_running(monkeypatch):
    ov._layout_jobs.clear()
    spawned = []

    class _Proc:
        def __init__(self, rc):
            self._rc = rc

        def poll(self):
            return self._rc

    import api.layout_job as lj

    monkeypatch.setattr(
        lj, "spawn", lambda mode, tid, force=False: spawned.append((mode, tid)) or _Proc(None)
    )
    ov.ensure_layout_job("lab", "team")
    ov.ensure_layout_job("lab", "team")  # still running → deduped
    assert spawned == [("lab", "team")]
    ov._layout_jobs[("lab", "team")] = _Proc(0)  # finished → respawn allowed
    ov.ensure_layout_job("lab", "team")
    assert spawned == [("lab", "team"), ("lab", "team")]


def test_serving_modules_never_import_sklearn():
    """The whole point of issue #103: importing the serving stack must not pull
    scikit-learn (its ~300 MB resident set is why the VM needed 1 GB). Run in a
    child interpreter so other tests' imports can't contaminate the check."""
    code = (
        "import sys; import api.app, api.overview, api.layout_job, api.layout_store; "
        "bad = [m for m in sys.modules if m.split('.')[0] in ('sklearn', 'scipy')]; "
        "assert not bad, f'serving imports pulled in {bad}'"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=120)
