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


def test_map_requires_bearer_token():
    resp = client.get("/map", params={"team_id": "t"})
    assert resp.status_code == 401


def test_map_cache_keys_on_embedded_set():
    from api.app import MapCache

    cache = MapCache()
    key = frozenset({("p1", "2026-07-01T00:00:00Z")})
    cache.put("team-a", key, ["layout"])

    assert cache.get("team-a", key) == ["layout"]
    # A re-embedded paper (new embedded_at) or another team must miss.
    assert cache.get("team-a", frozenset({("p1", "2026-07-02T00:00:00Z")})) is None
    assert cache.get("team-b", key) is None


def test_parse_vector_handles_postgrest_string_form():
    from api.app import _parse_vector

    assert _parse_vector("[0.1,0.2]") == [0.1, 0.2]
    assert _parse_vector([0.1, 0.2]) == [0.1, 0.2]


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
