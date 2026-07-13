"""Offline tests for the maps endpoints — the request/response contract and the
seed-embedding wiring. RLS + membership ranking are proven by the pgTAP test
(supabase/tests/maps_test.sql); here the Supabase client and the embedding call
are stubbed so nothing external is needed."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api import embeddings, maps  # noqa: E402
from api.app import app  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": "Bearer tok"}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records the insert payload and returns a canned row, ignoring the fluent
    chain (select/eq/order/limit/delete) that PostgREST would apply."""

    def __init__(self, sink, ret):
        self.sink, self.ret = sink, ret

    def insert(self, payload):
        self.sink["insert"] = payload
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def delete(self):
        self.sink["delete"] = True
        return self

    def execute(self):
        return _Resp(self.ret)


class _Client:
    def __init__(self, sink, ret):
        self.sink, self.ret = sink, ret

    def table(self, name):
        self.sink["table"] = name
        return _Query(self.sink, self.ret)


@pytest.fixture
def stub(monkeypatch):
    """Stub auth + embeddings; return a helper to install a fake DB client whose
    execute() yields `ret`, exposing the recorded insert payload."""
    monkeypatch.setattr(maps, "get_user_id", lambda _t: "user-1")
    monkeypatch.setattr(maps.embeddings, "embed_query", lambda _s: [0.25] * 1024)
    sink: dict = {}

    def install(ret):
        monkeypatch.setattr(maps, "user_client", lambda _t: _Client(sink, ret))
        return sink

    return install


def test_create_embeds_seed_and_stamps_author(stub):
    row = {
        "id": "m1", "team_id": "t1", "created_by": "user-1", "name": "Ovarian Cancer",
        "seed": "ovarian cancer", "visibility": "lab",
        "created_at": "2026-07-13T00:00:00Z", "updated_at": "2026-07-13T00:00:00Z",
    }
    sink = stub([row])
    r = client.post(
        "/maps",
        headers=AUTH,
        json={"team_id": "t1", "name": " Ovarian Cancer ", "seed": " ovarian cancer "},
    )
    assert r.status_code == 200, r.text
    ins = sink["insert"]
    assert ins["created_by"] == "user-1"           # authored as the caller (RLS check)
    assert ins["name"] == "Ovarian Cancer"         # trimmed
    assert ins["seed"] == "ovarian cancer"
    assert ins["seed_embedding"] == [0.25] * 1024  # seed embedded server-side
    assert r.json()["id"] == "m1"


def test_create_rejects_empty_seed(stub):
    stub([])
    # "" fails pydantic's min_length=1 (422); whitespace-only passes it but is
    # caught by the endpoint's strip guard (400) — cover both.
    empty = client.post("/maps", headers=AUTH, json={"team_id": "t1", "name": "X", "seed": ""})
    blank = client.post("/maps", headers=AUTH, json={"team_id": "t1", "name": "X", "seed": " "})
    assert empty.status_code == 422
    assert blank.status_code == 400


def test_create_surfaces_embedding_outage(stub, monkeypatch):
    stub([])

    def boom(_s):
        raise embeddings.EmbeddingError("no voyage key")

    monkeypatch.setattr(maps.embeddings, "embed_query", boom)
    r = client.post("/maps", headers=AUTH, json={"team_id": "t1", "name": "X", "seed": "y"})
    assert r.status_code == 503


def test_create_rls_refusal_is_403(stub):
    stub([])  # empty insert result → not a member of that lab
    r = client.post("/maps", headers=AUTH, json={"team_id": "other", "name": "X", "seed": "y"})
    assert r.status_code == 403


class _RaisingClient:
    def __init__(self, exc):
        self.exc = exc

    def table(self, _name):
        return self

    def insert(self, _payload):
        return self

    def execute(self):
        raise self.exc


def _stub_auth(monkeypatch):
    monkeypatch.setattr(maps, "get_user_id", lambda _t: "u")
    monkeypatch.setattr(maps.embeddings, "embed_query", lambda _s: [0.1] * 1024)


def test_rls_violation_is_403(monkeypatch):
    _stub_auth(monkeypatch)
    err = Exception('new row violates row-level security policy for table "maps"')
    monkeypatch.setattr(maps, "user_client", lambda _t: _RaisingClient(err))
    r = client.post("/maps", headers=AUTH, json={"team_id": "x", "name": "n", "seed": "s"})
    assert r.status_code == 403


def test_unexpected_db_error_is_not_masked_as_403(monkeypatch):
    _stub_auth(monkeypatch)
    down = _RaisingClient(RuntimeError("connection refused"))
    monkeypatch.setattr(maps, "user_client", lambda _t: down)
    safe = TestClient(app, raise_server_exceptions=False)
    r = safe.post("/maps", headers=AUTH, json={"team_id": "x", "name": "n", "seed": "s"})
    assert r.status_code == 500  # a real failure, surfaced — not a disguised permission error


def test_delete_missing_or_foreign_is_404(stub):
    stub([])  # RLS deleted zero rows
    r = client.delete("/maps/whatever", headers=AUTH)
    assert r.status_code == 404


def test_endpoints_require_a_token():
    assert client.get("/maps?team_id=t1").status_code == 401
    assert client.post("/maps", json={"team_id": "t", "name": "n", "seed": "s"}).status_code == 401


# --- map summary generation (fallback + anti-hallucination) -----------------

import sys  # noqa: E402
import types  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from api import map_summary  # noqa: E402


def test_summary_empty_when_no_papers():
    assert map_summary.generate_summary("seed", []) == {
        "text": "", "cited_ids": [], "n_papers": 0, "ai": False
    }


def test_summary_falls_back_without_key(monkeypatch):
    monkeypatch.setattr(
        map_summary, "get_llm_settings", lambda: SimpleNamespace(anthropic_api_key=None)
    )
    papers = [{"paper_id": c, "title": f"Paper {c}"} for c in "abcd"]
    out = map_summary.generate_summary("ovarian cancer", papers)
    assert out["ai"] is False
    assert out["cited_ids"] == ["a", "b", "c"]  # the recency fallback cites the top few
    assert out["n_papers"] == 4
    assert "Paper a" in out["text"]


def test_summary_never_cites_outside_the_evidence(monkeypatch):
    """The model may return an id we never gave it; it must be dropped."""
    monkeypatch.setattr(
        map_summary,
        "get_llm_settings",
        lambda: SimpleNamespace(anthropic_api_key="k", anthropic_model="m"),
    )

    class _Messages:
        def parse(self, **_kw):
            return SimpleNamespace(
                parsed_output=SimpleNamespace(
                    summary="  Recent work.  ", cited_ids=["a", "GHOST", "b"]
                )
            )

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Client
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    papers = [{"paper_id": c, "title": f"P{c}", "abstract": "x"} for c in "abc"]
    out = map_summary.generate_summary("seed", papers)
    assert out["ai"] is True
    assert out["cited_ids"] == ["a", "b"]  # GHOST filtered out
    assert out["text"] == "Recent work."  # stripped
