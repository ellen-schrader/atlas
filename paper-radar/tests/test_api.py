"""Smoke tests for the FastAPI service (offline — no network lookups)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api.app import app  # noqa: E402

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_resolve_recognizes_scheme_and_computes_dedup_key():
    resp = client.post(
        "/resolve",
        json={"url": "https://arxiv.org/abs/2401.01234", "network": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "arxiv"
    assert data["url"] == "https://arxiv.org/abs/2401.01234"
    # url_norm drops scheme + www and is the dedup key (schemeless //host/path).
    assert data["url_norm"] == "//arxiv.org/abs/2401.01234"


def test_posts_requires_bearer_token():
    # No Authorization header → 401 before any Supabase call.
    resp = client.post("/posts", json={"url": "https://arxiv.org/abs/2401.01234", "team_id": "x"})
    assert resp.status_code == 401


def test_semantic_search_requires_bearer_token():
    resp = client.post("/search/semantic", json={"query": "x", "team_id": "t"})
    assert resp.status_code == 401


def test_overview_requires_bearer_token():
    resp = client.get("/overview", params={"team_id": "t"})
    assert resp.status_code == 401


def test_similarity_requires_bearer_token():
    resp = client.post("/similarity", json={"query": "x", "team_id": "t"})
    assert resp.status_code == 401


def test_compute_stats_aggregates_posts():
    from api.app import _compute_stats

    rows = [
        {"posted_at": "2026-03-09T12:00:00Z", "papers": {"venue": "Nature", "year": 2025,
                                                          "authors": ["A. One", "B. Last"]}},
        {"posted_at": "2026-03-20T12:00:00Z", "papers": {"venue": "Nature", "year": 2026,
                                                          "authors": ["C. Only"]}},
        {"posted_at": "2026-04-01T12:00:00Z", "papers": {"venue": "bioRxiv", "year": 2026,
                                                          "authors": []}},
    ]
    stats = _compute_stats(rows)
    assert stats.over_time == [{"month": "2026-03", "count": 2}, {"month": "2026-04", "count": 1}]
    assert stats.by_venue[0] == {"venue": "Nature", "count": 2}
    assert {"year": 2026, "count": 2} in stats.by_year
    # last author is the lab proxy; the empty-author row contributes nothing
    labs = {d["lab"]: d["count"] for d in stats.by_lab}
    assert labs == {"B. Last": 1, "C. Only": 1}


def test_resolve_dedup_key_strips_tracking_params():
    resp = client.post(
        "/resolve",
        json={
            "url": "https://www.nature.com/articles/s41586-024-01234-5?utm_source=x&fbclid=y",
            "network": False,
        },
    )
    assert resp.status_code == 200
    norm = resp.json()["url_norm"]
    assert norm == "//nature.com/articles/s41586-024-01234-5"
