"""Endpoint tests for /integrations/teams (offline — no Supabase, no webhooks)."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api import integrations as integ  # noqa: E402
from api.app import app  # noqa: E402

client = TestClient(app)

AUTH = {"Authorization": "Bearer test-token"}
GOOD_URL = "https://prod-1.westeurope.logic.azure.com/workflows/abc?sig=x"


class _FakeQuery:
    def __init__(self, data, eqs: dict):
        self._data = data
        self._eqs = eqs

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._eqs[col] = val
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _FakeClient:
    def __init__(self, tables: dict):
        self._tables = tables
        self.eqs: dict = {}

    def table(self, name):
        assert name in self._tables, f"unexpected query on table {name!r}"
        self.eqs[name] = {}
        return _FakeQuery(self._tables[name], self.eqs[name])


def test_all_endpoints_require_bearer_token():
    assert client.get("/integrations/teams", params={"team_id": "t"}).status_code == 401
    assert (
        client.put(
            "/integrations/teams", json={"team_id": "t", "webhook_url": GOOD_URL}
        ).status_code
        == 401
    )
    assert (
        client.patch(
            "/integrations/teams", json={"team_id": "t", "enabled": False}
        ).status_code
        == 401
    )
    assert client.delete("/integrations/teams", params={"team_id": "t"}).status_code == 401
    assert client.post("/integrations/teams/test", json={"team_id": "t"}).status_code == 401


def test_get_reports_not_configured_when_rls_hides_the_row(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    client_obj = _FakeClient({"team_integrations": []})
    monkeypatch.setattr(integ, "user_client", lambda t: client_obj)
    resp = client.get("/integrations/teams", headers=AUTH, params={"team_id": "abc"})
    assert resp.status_code == 200
    assert resp.json() == {
        "configured": False,
        "host": None,
        "enabled": False,
        "updated_at": None,
    }
    # The read must be scoped to the requested team.
    assert client_obj.eqs["team_integrations"] == {"team_id": "abc"}


def test_get_never_returns_the_full_webhook_url(monkeypatch):
    # The URL is a bearer secret — the client gets only the host.
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    monkeypatch.setattr(
        integ,
        "user_client",
        lambda t: _FakeClient(
            {
                "team_integrations": [
                    {"webhook_url": GOOD_URL, "enabled": True, "updated_at": "2026-07-16T00:00:00Z"}
                ]
            }
        ),
    )
    resp = client.get("/integrations/teams", headers=AUTH, params={"team_id": "t"})
    assert resp.status_code == 200
    body = resp.json()
    assert "webhook_url" not in body
    assert GOOD_URL not in resp.text
    assert body == {
        "configured": True,
        "host": "prod-1.westeurope.logic.azure.com",
        "enabled": True,
        "updated_at": "2026-07-16T00:00:00Z",
    }


def test_save_rejects_disallowed_url_before_any_write(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    monkeypatch.setattr(
        integ, "user_client", lambda t: pytest.fail("must not touch the DB on an invalid URL")
    )
    resp = client.put(
        "/integrations/teams",
        headers=AUTH,
        json={"team_id": "t", "webhook_url": "https://evil.example/workflows/x"},
    )
    assert resp.status_code == 400
    assert "Power Automate" in resp.json()["detail"]


def test_save_persists_the_normalized_url(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    saved: dict = {}

    class _Upserting:
        def upsert(self, row):
            saved.update(row)
            return self

        def execute(self):
            return types.SimpleNamespace(data=[saved])

    class _Client:
        def table(self, name):
            assert name == "team_integrations"
            return _Upserting()

    monkeypatch.setattr(integ, "user_client", lambda t: _Client())
    resp = client.put(
        "/integrations/teams",
        headers=AUTH,
        json={"team_id": "t", "webhook_url": "https://PROD-1.LOGIC.AZURE.COM/workflows/x"},
    )
    assert resp.status_code == 200
    # The normalized (lowercased) URL is stored, but only the host comes back.
    assert saved["webhook_url"] == "https://prod-1.logic.azure.com/workflows/x"
    assert saved["enabled"] is True
    assert saved["created_by"] == "u1"
    body = resp.json()
    assert "webhook_url" not in body
    assert body["host"] == "prod-1.logic.azure.com"


def test_save_maps_rls_denial_to_403(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")

    class _Denied(Exception):
        code = "42501"

    class _Denying:
        def upsert(self, row):
            raise _Denied("permission denied")

    class _Client:
        def table(self, name):
            return _Denying()

    monkeypatch.setattr(integ, "user_client", lambda t: _Client())
    resp = client.put(
        "/integrations/teams", headers=AUTH, json={"team_id": "t", "webhook_url": GOOD_URL}
    )
    assert resp.status_code == 403


def test_save_maps_unexpected_db_error_to_500_not_400(monkeypatch):
    # A non-RLS failure is a real server fault, not an input rejection — it must
    # not masquerade as a 400 (which would tell the owner their URL was bad).
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")

    class _Boom:
        def upsert(self, row):
            raise RuntimeError("connection reset")

    class _Client:
        def table(self, name):
            return _Boom()

    monkeypatch.setattr(integ, "user_client", lambda t: _Client())
    resp = client.put(
        "/integrations/teams", headers=AUTH, json={"team_id": "t", "webhook_url": GOOD_URL}
    )
    assert resp.status_code == 500


def test_patch_toggles_enabled_without_sending_a_url(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    captured: dict = {}

    class _Updating:
        def update(self, values):
            captured["values"] = values
            return self

        def eq(self, col, val):
            captured[col] = val
            return self

        def execute(self):
            return types.SimpleNamespace(
                data=[{"webhook_url": GOOD_URL, "enabled": False, "updated_at": None}]
            )

    class _Client:
        def table(self, name):
            assert name == "team_integrations"
            return _Updating()

    monkeypatch.setattr(integ, "user_client", lambda t: _Client())
    resp = client.patch(
        "/integrations/teams", headers=AUTH, json={"team_id": "t", "enabled": False}
    )
    assert resp.status_code == 200
    assert captured["values"]["enabled"] is False
    assert captured["team_id"] == "t"
    assert resp.json()["enabled"] is False
    assert resp.json()["host"] == "prod-1.westeurope.logic.azure.com"


def test_patch_404_when_no_row_updated(monkeypatch):
    # A non-owner (or missing row) updates nothing under RLS → not configured.
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")

    class _Updating:
        def update(self, values):
            return self

        def eq(self, col, val):
            return self

        def execute(self):
            return types.SimpleNamespace(data=[])

    class _Client:
        def table(self, name):
            return _Updating()

    monkeypatch.setattr(integ, "user_client", lambda t: _Client())
    resp = client.patch("/integrations/teams", headers=AUTH, json={"team_id": "t", "enabled": True})
    assert resp.status_code == 404


def test_test_endpoint_404_when_unconfigured_or_not_owner(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    monkeypatch.setattr(integ, "user_client", lambda t: _FakeClient({"team_integrations": []}))
    resp = client.post("/integrations/teams/test", headers=AUTH, json={"team_id": "t"})
    assert resp.status_code == 404


def test_test_endpoint_sends_card_and_reports_failure(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    monkeypatch.setattr(
        integ,
        "user_client",
        lambda t: _FakeClient(
            {
                "team_integrations": [
                    {"webhook_url": GOOD_URL, "enabled": True, "updated_at": None}
                ],
                "teams": [{"name": "Spatial Bio Lab"}],
            }
        ),
    )
    sent = {}

    def fake_post(url, card):
        sent["url"] = url
        sent["card"] = card
        return True

    monkeypatch.setattr(integ.teams_integration, "post_to_teams", fake_post)
    resp = client.post("/integrations/teams/test", headers=AUTH, json={"team_id": "t"})
    assert resp.status_code == 200
    assert sent["url"] == GOOD_URL
    assert "Spatial Bio Lab" in sent["card"]["body"][1]["text"]

    monkeypatch.setattr(integ.teams_integration, "post_to_teams", lambda *a: False)
    resp = client.post("/integrations/teams/test", headers=AUTH, json={"team_id": "t"})
    assert resp.status_code == 502


def test_test_endpoint_refuses_disabled_connection(monkeypatch):
    monkeypatch.setattr(integ, "get_user_id", lambda t: "u1")
    monkeypatch.setattr(
        integ,
        "user_client",
        lambda t: _FakeClient(
            {
                "team_integrations": [
                    {"webhook_url": GOOD_URL, "enabled": False, "updated_at": None}
                ]
            }
        ),
    )
    resp = client.post("/integrations/teams/test", headers=AUTH, json={"team_id": "t"})
    assert resp.status_code == 400
