"""Tests for the outbound Teams integration (offline — no real webhooks)."""

from __future__ import annotations

import json
import types
import urllib.error

import pytest

pytest.importorskip("supabase")

from api import teams_integration  # noqa: E402


def _settings(value: str):
    return lambda: types.SimpleNamespace(teams_webhook_urls=value)


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _FakeClient:
    def __init__(self, data):
        self._data = data

    def table(self, name):
        return _FakeQuery(self._data)


def _no_service_client():
    raise AssertionError("service_client must not be called")


# --- webhook_url_for_team ----------------------------------------------------


def test_webhook_url_unconfigured_is_none_without_db_call(monkeypatch):
    monkeypatch.setattr(teams_integration, "get_api_settings", _settings(""))
    monkeypatch.setattr(teams_integration, "service_client", _no_service_client)
    assert teams_integration.webhook_url_for_team("t1") is None


def test_webhook_url_invalid_json_is_none(monkeypatch):
    monkeypatch.setattr(teams_integration, "get_api_settings", _settings("{not json"))
    monkeypatch.setattr(teams_integration, "service_client", _no_service_client)
    assert teams_integration.webhook_url_for_team("t1") is None


def test_webhook_url_non_object_json_is_none(monkeypatch):
    monkeypatch.setattr(teams_integration, "get_api_settings", _settings('["url"]'))
    monkeypatch.setattr(teams_integration, "service_client", _no_service_client)
    assert teams_integration.webhook_url_for_team("t1") is None


def test_webhook_url_by_team_id_skips_db(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "get_api_settings", _settings('{"t1": "https://hook.example/x"}')
    )
    monkeypatch.setattr(teams_integration, "service_client", _no_service_client)
    assert teams_integration.webhook_url_for_team("t1") == "https://hook.example/x"


def test_webhook_url_falls_back_to_slug(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "get_api_settings", _settings('{"my-lab": "https://hook.example/y"}')
    )
    monkeypatch.setattr(
        teams_integration, "service_client", lambda: _FakeClient([{"slug": "my-lab"}])
    )
    assert teams_integration.webhook_url_for_team("some-uuid") == "https://hook.example/y"


def test_webhook_url_unmapped_team_is_none(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "get_api_settings", _settings('{"other-lab": "https://hook.example/z"}')
    )
    monkeypatch.setattr(
        teams_integration, "service_client", lambda: _FakeClient([{"slug": "my-lab"}])
    )
    assert teams_integration.webhook_url_for_team("some-uuid") is None


# --- build_paper_card ---------------------------------------------------------


def test_card_has_linked_title_byline_note_and_footer():
    card = teams_integration.build_paper_card(
        url="https://arxiv.org/abs/2401.01234",
        title="Attention Is All You Need",
        authors=["A. One", "B. Two", "C. Three", "D. Four"],
        venue="NeurIPS",
        year=2017,
        note="classic, worth a re-read",
        posted_by="Ellen",
    )
    assert card["type"] == "AdaptiveCard"
    texts = [b["text"] for b in card["body"]]
    assert texts[0] == "[Attention Is All You Need](https://arxiv.org/abs/2401.01234)"
    # 4 authors → first 3 + et al.; venue and year joined into the byline
    assert texts[1] == "A. One, B. Two, C. Three et al. · NeurIPS 2017"
    assert "classic, worth a re-read" in texts
    assert texts[-1] == "Posted by Ellen via Atlas"


def test_card_minimal_falls_back_to_url_and_generic_footer():
    card = teams_integration.build_paper_card(url="https://example.org/paper")
    texts = [b["text"] for b in card["body"]]
    assert texts[0] == "[https://example.org/paper](https://example.org/paper)"
    assert texts[-1] == "Posted via Atlas"
    assert len(texts) == 2  # no byline, no note


def test_card_escapes_brackets_in_title():
    card = teams_integration.build_paper_card(
        url="https://example.org/p", title="[RETRACTED] A study"
    )
    assert card["body"][0]["text"] == "[\\[RETRACTED\\] A study](https://example.org/p)"


# --- post_to_teams -----------------------------------------------------------


def test_post_to_teams_sends_adaptive_card_attachment(monkeypatch):
    captured = {}

    class _Resp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["content_type"] = req.get_header("Content-type")
        return _Resp()

    monkeypatch.setattr(teams_integration.urllib.request, "urlopen", fake_urlopen)
    card = {"type": "AdaptiveCard", "body": []}
    assert teams_integration.post_to_teams("https://hook.example/x", card) is True
    assert captured["url"] == "https://hook.example/x"
    assert captured["content_type"] == "application/json"
    (attachment,) = captured["body"]["attachments"]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert attachment["content"] == card


def test_post_to_teams_swallows_network_errors(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(teams_integration.urllib.request, "urlopen", fake_urlopen)
    assert teams_integration.post_to_teams("https://hook.example/x", {}) is False


def test_post_to_teams_treats_error_status_as_failure(monkeypatch):
    class _Resp:
        status = 400

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        teams_integration.urllib.request, "urlopen", lambda req, timeout=None: _Resp()
    )
    assert teams_integration.post_to_teams("https://hook.example/x", {}) is False


# --- notify_paper_posted -----------------------------------------------------


def test_notify_is_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(teams_integration, "get_api_settings", _settings(""))
    monkeypatch.setattr(teams_integration, "service_client", _no_service_client)
    monkeypatch.setattr(
        teams_integration,
        "post_to_teams",
        lambda *a, **k: pytest.fail("must not post without config"),
    )
    teams_integration.notify_paper_posted("t1", url="https://example.org/p")


def test_notify_posts_card_with_display_name(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "get_api_settings", _settings('{"t1": "https://hook.example/x"}')
    )
    monkeypatch.setattr(
        teams_integration, "service_client", lambda: _FakeClient([{"display_name": "Ellen"}])
    )
    sent = {}

    def fake_post(webhook_url, card):
        sent["webhook_url"] = webhook_url
        sent["card"] = card
        return True

    monkeypatch.setattr(teams_integration, "post_to_teams", fake_post)
    teams_integration.notify_paper_posted(
        "t1", url="https://example.org/p", title="A Paper", posted_by_id="u1"
    )
    assert sent["webhook_url"] == "https://hook.example/x"
    assert sent["card"]["body"][-1]["text"] == "Posted by Ellen via Atlas"


def test_notify_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(teams_integration, "get_api_settings", boom)
    teams_integration.notify_paper_posted("t1", url="https://example.org/p")
