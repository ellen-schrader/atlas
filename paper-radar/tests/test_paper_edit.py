"""Correcting a paper's metadata: PATCH /papers/{id} and POST /papers/{id}/resolve.

Offline. The database half — the concurrency token, the history row, the column
allow-list — lives in apply_paper_edit and is stubbed here; these tests pin what
the API decides before it gets there.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import api.app as app_mod  # noqa: E402
from api.app import app  # noqa: E402
from paper_radar.ingest.metadata import PaperMetadata  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": "Bearer good"}
EDITED = "2026-10-02T09:30:00.123456+00:00"


def _row(**kw) -> dict:
    base = {
        "id": "p1",
        "url": "https://jamanetwork.com/journals/jama/fullarticle/2847987",
        "doi": None,
        "title": "Old title",
        "authors": ["A. Author"],
        "venue": "JAMA",
        "year": 2024,
        "abstract": None,
        "keywords": [],
        "code_url": None,
        "data_url": None,
        "metadata_source": "citation_meta",
        "published_at": "2024-01-01",
        "edited_by": None,
        "edited_at": None,
        "edited_fields": [],
    }
    return {**base, **kw}


@pytest.fixture
def paper(monkeypatch):
    """A paper the caller may edit; records what would be written."""
    state = {"row": _row(), "writes": [], "tasks": []}
    monkeypatch.setattr(app_mod, "_require_paper_editor", lambda _t, _p: "user-1")
    monkeypatch.setattr(app_mod, "_load_paper", lambda _p: state["row"])

    def _apply(paper_id, user_id, kind, expected, patch, held):
        state["writes"].append(
            {"kind": kind, "expected": expected, "patch": patch, "held": held, "by": user_id}
        )

    monkeypatch.setattr(app_mod, "_apply_edit", _apply)
    monkeypatch.setattr(
        app_mod, "_embed_and_store", lambda *a: state["tasks"].append(("embed", *a))
    )
    monkeypatch.setattr(
        app_mod, "_enrich_and_store", lambda *a: state["tasks"].append(("enrich", *a))
    )
    monkeypatch.setattr(
        app_mod, "_resolve_limiter", app_mod._PerUserRateLimiter(max_events=30, window_seconds=60.0)
    )
    return state


def _patch(body: dict):
    return client.patch("/papers/p1", json={"expected_edited_at": None, **body}, headers=AUTH)


# --- fix by hand -------------------------------------------------------------


def test_edit_writes_only_changed_fields_and_holds_only_those(paper):
    resp = _patch({"title": "  The real title ", "venue": "JAMA"})  # venue unchanged
    assert resp.status_code == 200, resp.text
    (w,) = paper["writes"]
    assert w["kind"] == "edit"
    assert w["patch"]["title"] == "The real title"
    assert "venue" not in w["patch"]
    # Re-saving an untouched field must not opt it out of future backfill.
    assert w["held"] == ["title"]
    assert w["patch"]["metadata_source"] == "manual"


def test_holds_accumulate_across_edits(paper):
    paper["row"] = _row(edited_at=EDITED, edited_fields=["venue"])
    resp = client.patch(
        "/papers/p1", json={"expected_edited_at": EDITED, "title": "New"}, headers=AUTH
    )
    assert resp.status_code == 200, resp.text
    assert paper["writes"][0]["held"] == ["title", "venue"]


def test_title_edit_reembeds_and_retags(paper):
    _patch({"title": "New"})
    w = paper["writes"][0]
    assert w["patch"]["embedded_at"] is None and w["patch"]["enriched_at"] is None
    assert {t[0] for t in paper["tasks"]} >= {"enrich"}


def test_link_edit_does_not_retag_the_paper_for_every_lab(paper):
    # papers.tags is shown in every lab holding the paper; fixing a code link must
    # not buy an LLM re-tag of it.
    _patch({"code_url": "https://github.com/lab/tool"})
    w = paper["writes"][0]
    assert "embedded_at" not in w["patch"] and "enriched_at" not in w["patch"]
    assert paper["tasks"] == []


def test_year_moves_a_year_only_published_at(paper):
    _patch({"year": 2023})
    assert paper["writes"][0]["patch"]["published_at"] == "2023-01-01"


def test_year_leaves_a_real_publication_date_alone(paper):
    paper["row"] = _row(published_at="2024-03-17")
    _patch({"year": 2023})
    assert "published_at" not in paper["writes"][0]["patch"]


def test_unchanged_form_writes_nothing(paper):
    resp = _patch({"title": "Old title", "authors": ["A. Author"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unchanged"
    assert paper["writes"] == []


def test_blank_title_is_refused(paper):
    resp = _patch({"title": "   "})
    assert resp.status_code == 400
    assert paper["writes"] == []


def test_doi_and_url_are_not_editable(paper):
    _patch({"title": "New", "doi": "10.1/other", "url": "https://elsewhere"})
    patch = paper["writes"][0]["patch"]
    assert "doi" not in patch and "url" not in patch


def test_script_links_are_refused(paper):
    resp = _patch({"code_url": "javascript:alert(1)"})
    assert resp.status_code == 400
    assert paper["writes"] == []


def test_stale_token_is_a_409_before_anything_is_written(paper):
    paper["row"] = _row(edited_at=EDITED, edited_fields=["title"])
    # The form was rendered before that edit happened.
    resp = _patch({"title": "Mine"})
    assert resp.status_code == 409
    assert paper["writes"] == []


def test_edit_requires_permission(monkeypatch):
    monkeypatch.setattr(app_mod, "get_user_id", lambda _t: "member")

    class _Denied:
        def rpc(self, name, args):
            assert name == "can_edit_paper"
            return self

        def execute(self):
            return type("R", (), {"data": False})()

    monkeypatch.setattr(app_mod, "user_client", lambda _t: _Denied())
    monkeypatch.setattr(app_mod, "_load_paper", lambda _p: pytest.fail("read before authz"))
    resp = _patch({"title": "Mine"})
    assert resp.status_code == 403


def test_edit_requires_a_token():
    resp = client.patch("/papers/p1", json={"expected_edited_at": None, "title": "x"})
    assert resp.status_code in (401, 403)


def test_rpc_serialization_failure_becomes_409(monkeypatch):
    class _Conflict(Exception):
        code = "40001"

    class _Svc:
        def rpc(self, *_a):
            return self

        def execute(self):
            raise _Conflict("stale")

    monkeypatch.setattr(app_mod, "service_client", lambda: _Svc())
    with pytest.raises(HTTPException) as err:
        app_mod._apply_edit("p1", "u", "edit", None, {"title": "x"}, ["title"])
    assert err.value.status_code == 409


# --- re-resolve --------------------------------------------------------------


def _resolver(monkeypatch, *, owner=None, **meta):
    base = {
        "url": "https://jamanetwork.com/journals/jama/fullarticle/2847987",
        "title": "Resolved title",
        "authors": ["A. Author", "B. Author"],
        "venue": "JAMA",
        "year": 2026,
        "doi": "10.1001/jama.2026.4634",
        "abstract": "An abstract.",
        "source": "crossref",
    }
    monkeypatch.setattr(app_mod, "fetch_metadata", lambda _u: PaperMetadata(**{**base, **meta}))
    monkeypatch.setattr(app_mod, "_doi_owner", lambda _s, _d, _id: owner)
    monkeypatch.setattr(app_mod, "service_client", lambda: None)


def _reresolve(**body):
    return client.post(
        "/papers/p1/resolve", json={"expected_edited_at": None, **body}, headers=AUTH
    )


def test_reresolve_writes_what_the_publisher_says(paper, monkeypatch):
    _resolver(monkeypatch)
    resp = _reresolve()
    assert resp.status_code == 200, resp.text
    (w,) = paper["writes"]
    assert w["kind"] == "resolve"
    assert w["patch"]["title"] == "Resolved title"
    assert w["patch"]["doi"] == "10.1001/jama.2026.4634"
    assert w["held"] == []


def test_reresolve_refuses_to_discard_hand_edits_unasked(paper, monkeypatch):
    paper["row"] = _row(edited_at=EDITED, edited_fields=["title"])

    def _no_fetch(_u):
        raise AssertionError("must not fetch before the override is confirmed")

    monkeypatch.setattr(app_mod, "fetch_metadata", _no_fetch)
    resp = client.post("/papers/p1/resolve", json={"expected_edited_at": EDITED}, headers=AUTH)
    assert resp.status_code == 409
    assert "title" in resp.json()["detail"]
    assert paper["writes"] == []


def test_reresolve_with_override_clears_the_holds(paper, monkeypatch):
    paper["row"] = _row(edited_at=EDITED, edited_fields=["title"])
    _resolver(monkeypatch)
    resp = client.post(
        "/papers/p1/resolve",
        json={"expected_edited_at": EDITED, "discard_edits": True},
        headers=AUTH,
    )
    assert resp.status_code == 200, resp.text
    w = paper["writes"][0]
    assert w["patch"]["title"] == "Resolved title"
    assert w["held"] == []


def test_reresolve_keeps_the_doi_off_a_collision(paper, monkeypatch):
    _resolver(monkeypatch, owner="p2")
    resp = _reresolve()
    assert resp.json()["duplicate_of"] == "p2"
    patch = paper["writes"][0]["patch"]
    assert "doi" not in patch and patch["title"] == "Resolved title"


def test_reresolve_with_nothing_found_writes_nothing(paper, monkeypatch):
    _resolver(monkeypatch, title=None)
    resp = _reresolve()
    assert resp.json()["status"] == "unresolved"
    assert paper["writes"] == []


def test_reresolve_is_rate_limited(paper, monkeypatch):
    _resolver(monkeypatch)
    monkeypatch.setattr(
        app_mod, "_resolve_limiter", app_mod._PerUserRateLimiter(max_events=1, window_seconds=60.0)
    )
    assert _reresolve().status_code == 200
    assert _reresolve().status_code == 429


def test_reresolve_refuses_internal_urls(paper, monkeypatch):
    paper["row"] = _row(url="http://169.254.169.254/latest/meta-data")
    monkeypatch.setattr(app_mod, "fetch_metadata", lambda _u: pytest.fail("fetched"))
    assert _reresolve().status_code == 400


def test_reresolve_reports_a_collision_even_when_nothing_else_changes(paper, monkeypatch):
    # Everything matches the publisher except the rendition DOI, and another row
    # already holds the real one.
    paper["row"] = _row(
        title="Resolved title",
        authors=["A. Author", "B. Author"],
        year=2026,
        published_at="2026-01-01",
        abstract="An abstract.",
        doi="10.1001/jama.2026.4634v1",
        metadata_source="crossref",
    )
    _resolver(monkeypatch, owner="p2")
    resp = _reresolve()
    assert resp.json()["duplicate_of"] == "p2"
    assert paper["writes"] == []


def test_repairing_an_untitled_row_leaves_hand_corrected_fields_alone(monkeypatch):
    written = {}

    class _Svc:
        def table(self, _n):
            return self

        def update(self, patch):
            written.update(patch)
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            return None

    monkeypatch.setattr(app_mod, "service_client", lambda: _Svc())
    row = {"id": "p1", "title": None, "edited_fields": ["venue", "year"]}
    meta = PaperMetadata(
        url="https://x.org", title="T", venue="Wrong", year=1999, source="crossref"
    )
    assert app_mod._repair_untitled(row, meta)
    assert written["title"] == "T"
    assert "venue" not in written and "year" not in written
