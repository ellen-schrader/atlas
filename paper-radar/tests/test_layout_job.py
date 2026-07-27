"""Offline tests for the ephemeral layout job (api/layout_job.py)."""

from __future__ import annotations

import sys

from api import layout_job as lj
from api import overview as ov


def test_embedded_papers_filters_and_sorts():
    rows = [
        {"papers": {"id": "b", "embedding": "[1]", "embedded_at": "t"}},
        {"papers": {"id": "c", "embedding": None, "embedded_at": None}},  # not embedded
        {"papers": None},                                                  # dangling join
        {"papers": {"id": "a", "embedding": "[2]", "embedded_at": "t"}},
    ]
    papers = lj._embedded_papers(rows)
    assert [p["id"] for p in papers] == ["a", "b"]


def test_compute_and_store_empty_set_stores_nothing(monkeypatch):
    stored = []
    monkeypatch.setattr(lj, "store_layout", lambda *a: stored.append(a))
    assert lj.compute_and_store("team", []) == "empty"
    assert stored == []


def _papers():
    return [
        {"id": "p1", "embedded_at": "t1", "title": "A", "embedding": "[0.1, 0.2]"},
        {"id": "p2", "embedded_at": "t1", "title": "B", "embedding": "[0.9, 0.8]"},
    ]


def test_compute_and_store_skips_persisted_and_forces(monkeypatch):
    computed = {"n": 0}
    points = {p["id"]: {"x": 0.0, "y": 0.0, "cluster": 0} for p in _papers()}

    def fake_compute(team_id, papers):
        computed["n"] += 1
        return points, []

    stored: list[tuple] = []
    monkeypatch.setattr(ov, "compute_layout", fake_compute)
    monkeypatch.setattr(lj, "store_layout", lambda *a: stored.append(a))

    # miss → computes and stores under the papers' signature
    monkeypatch.setattr(lj, "load_layout", lambda *a: None)
    assert lj.compute_and_store("team", _papers()) == "stored"
    assert computed["n"] == 1
    assert stored == [("team", ov._signature(_papers()), points)]

    # already persisted → no recompute…
    monkeypatch.setattr(lj, "load_layout", lambda *a: points)
    assert lj.compute_and_store("team", _papers()) == "skipped"
    assert computed["n"] == 1
    # …unless forced
    assert lj.compute_and_store("team", _papers(), force=True) == "stored"
    assert computed["n"] == 2


def test_spawn_launches_this_module(monkeypatch):
    launched = {}

    class _P:
        def __init__(self, argv):
            launched["argv"] = argv

    monkeypatch.setattr(lj.subprocess, "Popen", _P)
    lj.spawn("lab", "team-1")
    assert launched["argv"] == [sys.executable, "-m", "api.layout_job", "lab", "team-1"]


def test_main_lab_mode_wires_fetch_to_compute(monkeypatch):
    calls = {}
    monkeypatch.setattr(lj, "service_client", lambda: "svc")
    monkeypatch.setattr(lj, "_fetch_lab_papers", lambda svc, tid: [{"id": "p1"}])
    monkeypatch.setattr(
        lj,
        "compute_and_store",
        lambda tid, papers, force=False: calls.update(tid=tid, papers=papers, force=force)
        or "stored",
    )
    lj.main(["lab", "team-1"])
    assert calls == {"tid": "team-1", "papers": [{"id": "p1"}], "force": False}
