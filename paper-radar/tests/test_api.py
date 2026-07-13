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


def test_profile_requires_bearer_token():
    resp = client.post("/profile", json={"profile_md": "I study spatial biology"})
    assert resp.status_code == 401


def test_recommendations_requires_bearer_token():
    resp = client.get("/recommendations", params={"team_id": "t"})
    assert resp.status_code == 401


def test_l2norm_returns_unit_vector():
    import numpy as np

    from api.app import _l2norm

    out = _l2norm(np.array([3.0, 4.0], dtype=np.float32))
    assert abs(float(np.linalg.norm(out)) - 1.0) < 1e-6
    # a zero vector is returned unchanged (no divide-by-zero)
    zero = _l2norm(np.zeros(4, dtype=np.float32))
    assert float(np.linalg.norm(zero)) == 0.0


def test_parse_vec_handles_string_and_list():
    from api.app import _parse_vec

    assert _parse_vec("[0.1, 0.2, 0.3]") == [0.1, 0.2, 0.3]
    assert _parse_vec([0.1, 0.2]) == [0.1, 0.2]
    assert _parse_vec(None) is None


def test_recency_decay_halves_at_halflife():
    from datetime import UTC, datetime, timedelta

    from api.app import _HALFLIFE_DAYS, _recency_decay

    now = datetime(2026, 7, 1, tzinfo=UTC)
    assert _recency_decay(now, now) == 1.0  # brand new
    half = now - timedelta(days=_HALFLIFE_DAYS)
    assert abs(_recency_decay(half, now) - 0.5) < 1e-6  # one half-life → 0.5
    assert _recency_decay(None, now) == 1.0  # missing timestamp → no decay
    # a future timestamp doesn't amplify weight
    assert _recency_decay(now + timedelta(days=5), now) == 1.0


def test_parse_ts_handles_iso_and_z():
    from api.app import _parse_ts

    assert _parse_ts("2026-07-01T12:00:00+00:00") is not None
    assert _parse_ts("2026-07-01T12:00:00Z") is not None  # Z offset
    assert _parse_ts(None) is None
    assert _parse_ts("not-a-date") is None


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


# --- BibTeX import ---------------------------------------------------------


def test_bibtex_endpoints_require_a_bearer_token():
    for path in ("/import/bibtex/preflight", "/import/bibtex"):
        resp = client.post(path, json={"team_id": "x", "bibtex": "@article{a}"})
        assert resp.status_code in (401, 403), path


def test_bibtex_preflight_refuses_a_lab_you_are_not_in(monkeypatch):
    """The pre-flight reads with the service role (it must, to see papers other members
    posted), so RLS can't protect it. Without an explicit membership check, `team_id` is
    attacker-controlled and a "duplicate" verdict tells you a lab you can't see holds
    that DOI — an oracle over any lab's corpus."""
    import api.app as app_mod

    monkeypatch.setattr(app_mod, "get_user_id", lambda _t: "attacker")

    class _NoMembership:
        def table(self, _n):
            return self

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a, **_k):
            return self

        def limit(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": []})()  # not a member of anything

    monkeypatch.setattr(app_mod, "user_client", lambda _t: _NoMembership())

    for path in ("/import/bibtex/preflight", "/import/bibtex"):
        resp = client.post(
            path,
            json={"team_id": "someone-elses-lab", "bibtex": "@article{a, doi={10.1/x}}"},
            headers={"Authorization": "Bearer forged"},
        )
        assert resp.status_code == 403, f"{path} leaked: {resp.status_code}"
        assert "not a member" in resp.json()["detail"].lower()


def test_bibtex_payload_is_bounded():
    """An unbounded `bibtex` string lets one request exhaust the process."""
    resp = client.post(
        "/import/bibtex/preflight",
        json={"team_id": "x", "bibtex": "a" * (app_mod_max() + 1)},
        headers={"Authorization": "Bearer whatever"},
    )
    assert resp.status_code == 422


def app_mod_max() -> int:
    from api.app import MAX_BIBTEX_BYTES

    return MAX_BIBTEX_BYTES
