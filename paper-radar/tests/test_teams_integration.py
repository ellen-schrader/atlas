"""Tests for the outbound Teams integration (offline — no real webhooks)."""

from __future__ import annotations

import json
import types
import urllib.error

import pytest

pytest.importorskip("supabase")

from api import teams_integration  # noqa: E402


class _FakeQuery:
    """Records .eq() filters so tests can assert the query is team-scoped."""

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
    """Canned rows per table; querying any table not in the map is an error.

    Records the last .eq() filters per table in `.eqs` for scoping assertions.
    """

    def __init__(self, tables: dict):
        self._tables = tables
        self.eqs: dict = {}

    def table(self, name):
        assert name in self._tables, f"unexpected query on table {name!r}"
        self.eqs[name] = {}
        return _FakeQuery(self._tables[name], self.eqs[name])


def _client_without_row():
    return _FakeClient({"team_integrations": []})


# --- validate_webhook_url (SSRF / allowlist) ----------------------------------

GOOD_URL = "https://prod-27.westeurope.logic.azure.com:443/workflows/abc/triggers/manual?sig=x"


def test_validate_accepts_power_automate_urls():
    assert teams_integration.validate_webhook_url(GOOD_URL) == GOOD_URL
    assert (
        teams_integration.validate_webhook_url(
            "https://x.westeurope.environment.api.powerplatform.com/powerautomate/x"
        )
        == "https://x.westeurope.environment.api.powerplatform.com/powerautomate/x"
    )


def test_validate_lowercases_the_host():
    out = teams_integration.validate_webhook_url("https://PROD-27.LOGIC.AZURE.COM/workflows/x")
    assert out == "https://prod-27.logic.azure.com/workflows/x"


@pytest.mark.parametrize(
    "url",
    [
        "http://prod-27.logic.azure.com/workflows/x",  # not https
        "https://evil.example/workflows/x",  # host not allowlisted
        "https://logic.azure.com.evil.example/x",  # allowlisted suffix in the middle
        "https://evillogic.azure.com/x",  # missing the dot boundary
        "https://logic.azure.com/x",  # bare apex, no subdomain
        "https://prod.logic.azure.com./x",  # trailing-dot host
        "https://user@prod.logic.azure.com/x",  # embedded credentials
        "https://user:pw@prod.logic.azure.com/x",  # embedded credentials
        "https://evil.com\\@prod.logic.azure.com/x",  # backslash parser-confusion
        "https://prod.logic.azure.com:8443/x",  # non-default port
        "https://prod.logic.azure.com",  # no path (DB CHECK requires one)
        "https://prod.logic.azure.com/",  # bare-slash path only
        "https://127.0.0.1/workflows/x",  # IP literal (also not allowlisted)
        "https://[::1]/workflows/x",  # IPv6 loopback literal
        "https://localhost/workflows/x",  # internal name (url_guard)
        "https://prod.logic.azure.cоm/x",  # Cyrillic 'о' homoglyph — not the real TLD
        "file:///etc/passwd",  # scheme (url_guard)
        "",  # empty (url_guard)
        "https://" + "a" * 2100 + ".logic.azure.com/x",  # over-long (url_guard)
    ],
)
def test_validate_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        teams_integration.validate_webhook_url(url)


def test_redirects_are_never_followed():
    handler = teams_integration._NoRedirect()
    assert (
        handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/") is None
    )


# --- webhook_url_for_team ----------------------------------------------------


def test_webhook_url_unconfigured_is_none(monkeypatch):
    monkeypatch.setattr(teams_integration, "service_client", _client_without_row)
    assert teams_integration.webhook_url_for_team("t1") is None


def test_webhook_url_returns_enabled_row_scoped_to_team(monkeypatch):
    client = _FakeClient(
        {"team_integrations": [{"webhook_url": "https://db.example/hook", "enabled": True}]}
    )
    monkeypatch.setattr(teams_integration, "service_client", lambda: client)
    assert teams_integration.webhook_url_for_team("t1") == "https://db.example/hook"
    # The lookup must be filtered to the requested team — else it's a
    # cross-tenant leak (any lab's webhook for any team_id).
    assert client.eqs["team_integrations"] == {"team_id": "t1"}


def test_webhook_url_disabled_row_is_none(monkeypatch):
    # An owner who paused the connection must stay off.
    monkeypatch.setattr(
        teams_integration,
        "service_client",
        lambda: _FakeClient(
            {"team_integrations": [{"webhook_url": "https://db.example/hook", "enabled": False}]}
        ),
    )
    assert teams_integration.webhook_url_for_team("t1") is None


# --- build_paper_card ---------------------------------------------------------


def _button_urls(card):
    return {a["title"]: a["url"] for a in card.get("actions", [])}


def test_card_layout_header_authors_venue_abstract_note_footer():
    card = teams_integration.build_paper_card(
        url="https://arxiv.org/abs/2401.01234",
        title="Attention Is All You Need",
        authors=["A. One", "B. Two", "C. Three", "D. Four"],
        venue="NeurIPS",
        year=2017,
        abstract="We propose the Transformer.",
        note="classic, worth a re-read",
        posted_by="Ellen",
        atlas_url="https://atlas.example.com/?paper=p1",
    )
    assert card["type"] == "AdaptiveCard"
    texts = [b["text"] for b in card["body"]]
    # Title is a bold header (not a markdown link — links are buttons now).
    assert texts[0] == "Attention Is All You Need"
    assert card["body"][0]["size"] == "Large" and card["body"][0]["weight"] == "Bolder"
    # 4 authors → first 3 + et al., on their own line; venue · year separate.
    assert texts[1] == "A. One, B. Two, C. Three et al."
    assert texts[2] == "NeurIPS · 2017"
    assert "We propose the Transformer." in texts
    assert "“classic, worth a re-read”" in texts
    assert texts[-1] == "Posted by Ellen via Atlas"
    # Both links are buttons.
    assert _button_urls(card) == {
        "View paper": "https://arxiv.org/abs/2401.01234",
        "Open in Atlas": "https://atlas.example.com/?paper=p1",
    }


def test_card_without_atlas_url_has_only_the_paper_button():
    card = teams_integration.build_paper_card(url="https://example.org/paper", title="T")
    assert _button_urls(card) == {"View paper": "https://example.org/paper"}


def test_card_minimal_falls_back_to_url_header_and_generic_footer():
    card = teams_integration.build_paper_card(url="https://example.org/paper")
    texts = [b["text"] for b in card["body"]]
    assert texts[0] == "https://example.org/paper"  # header falls back to URL
    assert texts[-1] == "Posted via Atlas"
    assert len(texts) == 2  # header + footer only


def _by_id(card):
    return {b["id"]: b for b in card["body"] if "id" in b}


def test_card_short_abstract_shown_whole_without_toggle():
    card = teams_integration.build_paper_card(
        url="https://example.org/p", title="T", abstract="A brief abstract."
    )
    assert "A brief abstract." in [b.get("text") for b in card["body"]]
    # No preview/toggle machinery for a short abstract.
    assert _by_id(card) == {}


def test_card_long_abstract_collapses_with_show_more_link():
    long_abstract = " ".join(f"word{i}" for i in range(400))  # well over the preview limit
    card = teams_integration.build_paper_card(
        url="https://example.org/p", title="T", abstract=long_abstract
    )
    blocks = _by_id(card)
    # Preview visible + truncated; full hidden + complete.
    preview, full = blocks["abstract-preview"], blocks["abstract-full"]
    assert preview.get("isVisible", True) is True and preview["text"].endswith("…")
    assert len(preview["text"]) <= teams_integration._ABSTRACT_PREVIEW_CHARS + 1
    assert full["isVisible"] is False
    assert full["text"] == teams_integration._md_escape(long_abstract)  # nothing cut off

    # The toggle is a link, not a button: a Container with a selectAction, and
    # accent-coloured text — so it never shows up among the card's action buttons.
    more, less = blocks["abstract-more"], blocks["abstract-less"]
    assert more["type"] == "Container" and "actions" not in more
    assert more.get("isVisible", True) is True
    assert more["items"][0]["text"] == "Show more ▾" and more["items"][0]["color"] == "Accent"
    assert less["isVisible"] is False and less["items"][0]["text"] == "Show less ▴"
    button_titles = [a["title"] for a in card.get("actions", [])]
    assert "Show more" not in button_titles and "Show less" not in button_titles

    # "Show more" expands: reveal full + less, hide preview + more.
    targets = {t["elementId"]: t["isVisible"] for t in more["selectAction"]["targetElements"]}
    assert targets == {
        "abstract-preview": False,
        "abstract-full": True,
        "abstract-more": False,
        "abstract-less": True,
    }
    # "Show less" is the exact inverse.
    inv = {t["elementId"]: t["isVisible"] for t in less["selectAction"]["targetElements"]}
    assert inv == {k: (not v) for k, v in targets.items()}


def test_card_escapes_markdown_in_title():
    card = teams_integration.build_paper_card(
        url="https://example.org/p", title="[RETRACTED] Model_v2 *study*"
    )
    assert card["body"][0]["text"] == "\\[RETRACTED\\] Model\\_v2 \\*study\\*"


def test_card_url_button_is_not_escaped_or_encoded():
    # Action.OpenUrl carries a plain URL, not markdown — parens stay intact.
    card = teams_integration.build_paper_card(
        url="https://doi.org/10.1002/(SICI)1097-0142", title="Old Wiley DOI"
    )
    assert _button_urls(card)["View paper"] == "https://doi.org/10.1002/(SICI)1097-0142"


def test_card_escapes_markdown_in_abstract_note_and_footer():
    # Any user/metadata text in a TextBlock must render literally, never as a link.
    card = teams_integration.build_paper_card(
        url="https://example.org/p",
        abstract="see [here](https://evil.example)",
        note="[click me](https://evil.example)",
        posted_by="[x](https://evil.example)",
    )
    texts = [b["text"] for b in card["body"]]
    assert "see \\[here\\]\\(https://evil.example\\)" in texts
    assert "“\\[click me\\]\\(https://evil.example\\)”" in texts
    assert texts[-1] == "Posted by \\[x\\]\\(https://evil.example\\) via Atlas"


def test_card_escapes_markdown_in_authors_line():
    card = teams_integration.build_paper_card(
        url="https://example.org/p",
        title="T",
        authors=["[phish](https://evil.example)"],
    )
    assert card["body"][1]["text"] == "\\[phish\\]\\(https://evil.example\\)"


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "ms-cxh://x",  # OS deep-link scheme
    ],
)
def test_card_never_arms_a_dangerous_scheme_as_a_button(bad_url):
    # A non-http(s) paper URL must not become a clickable Action.OpenUrl.
    card = teams_integration.build_paper_card(url=bad_url, title="T")
    assert "actions" not in card  # no clickable button at all
    # The header still shows (escaped), so the card degrades gracefully.
    assert card["body"][0]["text"] == "T"


def test_card_drops_a_dangerous_atlas_url_but_keeps_the_paper_button():
    card = teams_integration.build_paper_card(
        url="https://example.org/p", title="T", atlas_url="javascript:alert(1)"
    )
    assert _button_urls(card) == {"View paper": "https://example.org/p"}


# --- _atlas_paper_url --------------------------------------------------------


def test_atlas_url_none_without_config(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "get_api_settings", lambda: types.SimpleNamespace(atlas_web_url="")
    )
    assert teams_integration._atlas_paper_url("p1") is None


def test_atlas_url_none_without_paper_id(monkeypatch):
    # paper_id missing → no settings lookup even needed.
    monkeypatch.setattr(
        teams_integration,
        "get_api_settings",
        lambda: pytest.fail("must not read settings without a paper_id"),
    )
    assert teams_integration._atlas_paper_url(None) is None


def test_atlas_url_builds_deep_link_and_strips_trailing_slash(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "get_api_settings",
        lambda: types.SimpleNamespace(atlas_web_url="https://atlas.example.com/"),
    )
    assert teams_integration._atlas_paper_url("p1") == "https://atlas.example.com/?paper=p1"


# --- post_to_teams -----------------------------------------------------------


class _FakeOpener:
    """Stands in for _webhook_opener; records the request or raises."""

    def __init__(self, raises: Exception | None = None):
        self.captured: dict = {}
        self._raises = raises

    def open(self, req, timeout=None):
        if self._raises is not None:
            raise self._raises
        self.captured["url"] = req.full_url
        self.captured["body"] = json.loads(req.data.decode("utf-8"))
        self.captured["content_type"] = req.get_header("Content-type")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()


def test_post_to_teams_sends_adaptive_card_attachment(monkeypatch):
    opener = _FakeOpener()
    monkeypatch.setattr(teams_integration, "_webhook_opener", opener)
    card = {"type": "AdaptiveCard", "body": []}
    assert teams_integration.post_to_teams("https://hook.example/x", card) is True
    assert opener.captured["url"] == "https://hook.example/x"
    assert opener.captured["content_type"] == "application/json"
    (attachment,) = opener.captured["body"]["attachments"]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert attachment["content"] == card


def test_post_to_teams_swallows_network_errors(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "_webhook_opener", _FakeOpener(raises=urllib.error.URLError("boom"))
    )
    assert teams_integration.post_to_teams("https://hook.example/x", {}) is False


def test_post_to_teams_treats_http_error_as_failure(monkeypatch):
    # The opener raises HTTPError for non-2xx (and for refused redirects); it
    # must be swallowed, not propagated.
    err = urllib.error.HTTPError("https://hook.example/x", 400, "Bad Request", None, None)
    monkeypatch.setattr(teams_integration, "_webhook_opener", _FakeOpener(raises=err))
    assert teams_integration.post_to_teams("https://hook.example/x", {}) is False


# --- notify_paper_posted -----------------------------------------------------


def test_notify_is_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(teams_integration, "service_client", _client_without_row)
    monkeypatch.setattr(
        teams_integration,
        "post_to_teams",
        lambda *a, **k: pytest.fail("must not post without config"),
    )
    teams_integration.notify_paper_posted("t1", url="https://example.org/p")


def test_notify_posts_card_with_display_name(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "service_client",
        lambda: _FakeClient(
            {
                "team_integrations": [{"webhook_url": GOOD_URL, "enabled": True}],
                "profiles": [{"display_name": "Ellen"}],
            }
        ),
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
    assert sent["webhook_url"] == GOOD_URL
    assert sent["card"]["body"][-1]["text"] == "Posted by Ellen via Atlas"


def test_notify_refuses_invalid_stored_webhook(monkeypatch):
    # Send-time validation: a stored URL that isn't a Power Automate endpoint
    # (however it got there) must never be connected to.
    monkeypatch.setattr(
        teams_integration,
        "service_client",
        lambda: _FakeClient(
            {"team_integrations": [{"webhook_url": "https://internal.example/x", "enabled": True}]}
        ),
    )
    monkeypatch.setattr(
        teams_integration,
        "post_to_teams",
        lambda *a, **k: pytest.fail("must not post to a non-allowlisted URL"),
    )
    teams_integration.notify_paper_posted("t1", url="https://example.org/p")


def test_notify_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(teams_integration, "service_client", boom)
    teams_integration.notify_paper_posted("t1", url="https://example.org/p")
