"""Tests for the outbound Teams integration (offline — no real webhooks)."""

from __future__ import annotations

import json
import types
import urllib.error

import pytest

pytest.importorskip("supabase")

from api import teams_integration  # noqa: E402
from paper_radar.ingest.urls import extract_urls_from_text  # noqa: E402


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
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/") is None


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


# === inbound (Teams → Atlas) =================================================

import base64  # noqa: E402
import hashlib  # noqa: E402
import hmac  # noqa: E402

_TOKEN = base64.b64encode(b"a-real-teams-security-token-32bytes!").decode()


def _sign(token: str, body: bytes) -> str:
    key = base64.b64decode(token)
    return "HMAC " + base64.b64encode(hmac.new(key, body, hashlib.sha256).digest()).decode()


def test_verify_signature_accepts_a_correct_hmac():
    body = b'{"text":"@Atlas https://arxiv.org/abs/1"}'
    assert teams_integration.verify_teams_signature(_TOKEN, body, _sign(_TOKEN, body)) is True


def test_verify_signature_rejects_tamper_missing_and_wrong_scheme():
    body = b'{"text":"x"}'
    good = _sign(_TOKEN, body)
    assert teams_integration.verify_teams_signature(_TOKEN, body + b"!", good) is False  # tampered
    assert teams_integration.verify_teams_signature(_TOKEN, body, None) is False  # no header
    assert teams_integration.verify_teams_signature(_TOKEN, body, good[5:]) is False  # no "HMAC "
    assert teams_integration.verify_teams_signature(_TOKEN, body, "HMAC not-base64") is False
    # A different key must not validate.
    other = base64.b64encode(b"some-other-key-entirely-here-32b!!").decode()
    assert teams_integration.verify_teams_signature(other, body, good) is False


def test_verify_signature_rejects_undecodable_stored_token():
    body = b"x"
    assert teams_integration.verify_teams_signature("not base64!!", body, "HMAC AAAA") is False


def test_normalize_inbound_secret():
    assert teams_integration.normalize_inbound_secret(f"  {_TOKEN}  ") == _TOKEN
    for bad in ["", "   ", "not base64!!", "a" * 2000]:
        with pytest.raises(ValueError):
            teams_integration.normalize_inbound_secret(bad)


def test_plan_no_url_never_touches_the_db(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "service_client", lambda: pytest.fail("no DB call without a link")
    )
    assert teams_integration.plan_inbound_import("t1", "just chatting, no links").status == "no_url"


def test_plan_skips_non_paper_hosts(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "service_client", lambda: pytest.fail("github is a skip-host")
    )
    plan = teams_integration.plan_inbound_import("t1", "@Atlas https://github.com/a/b")
    assert plan.status == "no_url"


def test_plan_new_when_paper_not_in_lab(monkeypatch):
    monkeypatch.setattr(teams_integration, "service_client", lambda: _FakeClient({"papers": []}))
    plan = teams_integration.plan_inbound_import("t1", "@Atlas https://arxiv.org/abs/2401.01234")
    assert plan.status == "new" and plan.url == "https://arxiv.org/abs/2401.01234"


def test_plan_new_when_paper_exists_but_not_posted_here(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "service_client",
        lambda: _FakeClient({"papers": [{"id": "p1"}], "paper_posts": []}),
    )
    assert teams_integration.plan_inbound_import("t1", "https://arxiv.org/abs/1").status == "new"


def test_plan_already_when_posted_to_this_team(monkeypatch):
    client = _FakeClient({"papers": [{"id": "p1"}], "paper_posts": [{"id": "pp1"}]})
    monkeypatch.setattr(teams_integration, "service_client", lambda: client)
    plan = teams_integration.plan_inbound_import("t1", "https://arxiv.org/abs/1")
    assert plan.status == "already"
    # The dedup lookup is scoped to this team, not global.
    assert client.eqs["paper_posts"]["team_id"] == "t1"


def test_inbound_message_text_finds_url_only_in_html_attachment():
    # Teams unfurls a pasted link into a preview card: the top-level text keeps
    # only the page title, and the URL survives only in the attachment (issue #93).
    payload = {
        "text": "<at>Atlas</at> Combination of paricalcitol with chemotherapy …",
        "attachments": [
            {
                "contentType": "text/html",
                "content": '<div><a href="https://doi.org/10.1038/s43018-1">Combination…</a></div>',
            }
        ],
    }
    text = teams_integration.inbound_message_text(payload)
    assert "https://doi.org/10.1038/s43018-1" in text
    assert extract_urls_from_text(text) == ["https://doi.org/10.1038/s43018-1"]


def test_inbound_message_text_finds_url_in_card_json():
    # Preview-card JSON: URLs sit in plain string values (thumbnail first here,
    # to prove the planner still picks the paper link over the image).
    payload = {
        "text": "Atlas Some Paper Title",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.thumbnail",
                "content": {
                    "images": [{"url": "https://marlin-prod.literatumonline.com/cover.jpg"}],
                    "title": "Some Paper Title",
                    "url": "https://doi.org/10.1016/j.cell.2026.06.027",
                },
            }
        ],
    }
    text = teams_integration.inbound_message_text(payload)
    assert "https://doi.org/10.1016/j.cell.2026.06.027" in text


def test_inbound_message_text_preserves_non_ascii_urls():
    # json.dumps must not \uXXXX-escape card URLs: the URL regex would capture
    # the escape sequence verbatim and the mangled link would never resolve.
    payload = {
        "text": "Atlas check this out",
        "attachments": [{"content": {"url": "https://link.springer.com/article/café"}}],
    }
    text = teams_integration.inbound_message_text(payload)
    assert extract_urls_from_text(text) == ["https://link.springer.com/article/café"]


def test_inbound_message_text_tolerates_junk_shapes():
    assert teams_integration.inbound_message_text({}) == ""
    assert teams_integration.inbound_message_text({"text": None, "attachments": "nope"}) == ""
    assert (
        teams_integration.inbound_message_text(
            {"text": "hi", "attachments": [None, {"content": 7}, {}]}
        )
        == "hi"
    )


def test_plan_matches_existing_paper_by_doi(monkeypatch):
    # A doi.org mention of a paper originally added via its publisher URL must
    # be answered "already in the lab", not "adding" (url_norm alone can't see
    # they're the same paper; the DOI can). Casefolded: mention is uppercase.
    paper = {"id": "p1", "title": "TLS harbour T cells", "authors": ["Jane Smith", "Bob Lee"]}

    class _Query:
        def __init__(self, table):
            self.table = table
            self.filters = {}

        def select(self, *a, **k):
            return self

        def eq(self, col, val):
            self.filters[col] = val
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            if self.table == "papers":
                hit = self.filters.get("doi") == "10.1038/s41586-026-10808-w"
                return types.SimpleNamespace(data=[paper] if hit else [])
            return types.SimpleNamespace(data=[{"id": "pp1"}])

    class _Client:
        def table(self, name):
            return _Query(name)

    monkeypatch.setattr(teams_integration, "service_client", lambda: _Client())
    plan = teams_integration.plan_inbound_import(
        "t1", "@Atlas https://doi.org/10.1038/S41586-026-10808-W"
    )
    assert plan.status == "already"
    assert plan.paper_id == "p1"
    assert plan.title == "TLS harbour T cells" and plan.authors == ["Jane Smith", "Bob Lee"]


def test_doi_from_url_resolver_hosts_only():
    # The path of a resolver URL IS the DOI — folded, decoded, slash-trimmed.
    f = teams_integration._doi_from_url
    assert f("https://doi.org/10.1038/S41586-026-10808-W") == "10.1038/s41586-026-10808-w"
    assert f("https://www.doi.org/10.1038/x/") == "10.1038/x"
    assert f("https://dx.doi.org/10.1002/(SICI)1097-0258") == "10.1002/(sici)1097-0258"
    assert f("https://doi.org/10.1002/anie%2F2020") == "10.1002/anie/2020"
    # Publisher paths are deliberately out of scope: a regex can't tell where
    # the DOI ends or whose DOI it found, and a wrong dedup answer is worse
    # than a hedged "adding" reply.
    assert f("https://link.springer.com/article/10.1007/s00248-1/tables/1") is None
    assert f("https://www.nature.com/articles/s41586-026-10808-w") is None


def test_already_reply_names_the_paper_and_links_it(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "get_api_settings",
        lambda: types.SimpleNamespace(atlas_web_url="https://atlas.example.com/"),
    )
    plan = teams_integration.InboundPlan(
        "already", url="u", paper_id="p1", title="A Paper", authors=["Jane Smith", "Bob Lee"]
    )
    text = teams_integration.already_reply_text(plan)
    assert "Jane Smith et al." in text
    assert "A Paper" in text
    assert "[Open in Atlas](https://atlas.example.com/?paper=p1)" in text


def test_already_reply_degrades_without_metadata_or_web_url(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "get_api_settings", lambda: types.SimpleNamespace(atlas_web_url="")
    )
    text = teams_integration.already_reply_text(teams_integration.InboundPlan("already", url="u"))
    assert text == "👍 That paper is already in the lab."


def test_new_reply_is_hedged_and_links_the_papers_feed(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "get_api_settings",
        lambda: types.SimpleNamespace(atlas_web_url="https://atlas.example.com"),
    )
    text = teams_integration.new_reply_text()
    # Must stay true whether the background dedup finds the paper or not.
    assert "isn't in the lab yet" in text
    assert "[Atlas](https://atlas.example.com/papers)" in text
    # The reply promises nothing about readability: that could only be a guess
    # made before the fetch, and it would be wrong in both directions.
    assert "recognize" not in text


def test_plan_skips_thumbnail_assets_and_picks_the_paper_link(monkeypatch):
    monkeypatch.setattr(teams_integration, "service_client", lambda: _FakeClient({"papers": []}))
    plan = teams_integration.plan_inbound_import(
        "t1",
        "https://marlin-prod.literatumonline.com/cover.jpg then "
        "https://doi.org/10.1016/j.cell.2026.06.027",
    )
    assert plan.status == "new" and plan.url == "https://doi.org/10.1016/j.cell.2026.06.027"


def test_import_background_closes_the_queue_row_once_the_link_resolves(monkeypatch):
    # A link queued months ago and re-driven after a resolver fix must not stay
    # in the queue; the same close runs whether it was queued a minute ago or not.
    import api.app as app_mod

    monkeypatch.setattr(teams_integration, "fetch_metadata", lambda url, **kw: _fake_meta())
    monkeypatch.setattr(app_mod, "_upsert_paper", lambda *a: ("p1", False))
    cap = _InsertCapture()
    monkeypatch.setattr(teams_integration, "service_client", lambda: cap)

    out = teams_integration.import_paper_background("t1", "https://arxiv.org/abs/1", "Ellen")

    assert out == "p1"  # the retry script uses this to tell recovered from still-failing
    assert cap.updated is not None and cap.updated["resolved_paper_id"] == "p1"
    assert cap.updated["resolved_at"]


def test_plan_asset_only_message_is_no_url(monkeypatch):
    monkeypatch.setattr(
        teams_integration, "service_client", lambda: pytest.fail("an image is not a paper")
    )
    plan = teams_integration.plan_inbound_import(
        "t1", "@Atlas https://statics.teams.cdn.office.net/thumb.png"
    )
    assert plan.status == "no_url"


def test_plan_retries_once_when_the_pooled_connection_is_stale(monkeypatch):
    # After a Fly suspend/resume the cached client's first request can hit a
    # socket the server closed during the idle window; one retry must recover.
    import httpx

    calls = {"n": 0}

    class _FlakyQuery:
        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            return types.SimpleNamespace(data=[])

    class _FlakyClient:
        def table(self, name):
            return _FlakyQuery()

    monkeypatch.setattr(teams_integration, "service_client", lambda: _FlakyClient())
    plan = teams_integration.plan_inbound_import("t1", "@Atlas https://arxiv.org/abs/2401.01234")
    assert plan.status == "new" and calls["n"] == 2


def test_inbound_secret_for_team(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "service_client",
        lambda: _FakeClient({"team_integrations": [{"inbound_secret": _TOKEN}]}),
    )
    assert teams_integration.inbound_secret_for_team("t1") == _TOKEN
    monkeypatch.setattr(teams_integration, "service_client", _client_without_row)
    assert teams_integration.inbound_secret_for_team("t1") is None


# --- import_paper_background (the actual resolve → insert) ---


class _InsertCapture:
    """A fake service client that records the paper_posts insert and reports the
    existing-post check as empty (a fresh paper)."""

    def __init__(self):
        self.inserted = None
        self.updated = None
        self.last_table = None

    def table(self, name):
        # The success path also closes any queue row for the link; the fake has to
        # allow that, or close_unresolved's own except would swallow the assert.
        assert name in ("paper_posts", "inbound_unresolved")
        self.last_table = name
        return self

    def update(self, row):
        self.updated = row
        return self

    def is_(self, *a, **k):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def execute(self):
        return types.SimpleNamespace(data=[] if self.inserted is None else [{"id": "pp1"}])


def _fake_meta(**kw):
    base = dict(
        url="https://arxiv.org/abs/1",
        title="A Paper",
        doi=None,
        abstract="x",
        authors=[],
        venue=None,
        year=None,
        keywords=[],
        source="arxiv",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_import_background_inserts_teams_post_with_sender_label(monkeypatch):
    import api.app as app_mod

    monkeypatch.setattr(teams_integration, "fetch_metadata", lambda url, **kw: _fake_meta())
    monkeypatch.setattr(app_mod, "_upsert_paper", lambda meta, url, url_norm: ("p1", False))
    cap = _InsertCapture()
    monkeypatch.setattr(teams_integration, "service_client", lambda: cap)

    teams_integration.import_paper_background("t1", "https://arxiv.org/abs/1", "Ellen Schrader")

    assert cap.inserted == {
        "paper_id": "p1",
        "team_id": "t1",
        "posted_by": None,
        "posted_by_label": "Ellen Schrader",
        "source": "teams",
    }


def test_import_background_truncates_a_long_sender_label(monkeypatch):
    import api.app as app_mod

    monkeypatch.setattr(teams_integration, "fetch_metadata", lambda url, **kw: _fake_meta())
    monkeypatch.setattr(app_mod, "_upsert_paper", lambda *a: ("p1", False))
    cap = _InsertCapture()
    monkeypatch.setattr(teams_integration, "service_client", lambda: cap)

    teams_integration.import_paper_background("t1", "https://arxiv.org/abs/1", "z" * 500)
    assert len(cap.inserted["posted_by_label"]) == teams_integration._INBOUND_LABEL_MAX


class _QueueCapture:
    """Fake service client that records inbound_unresolved writes and fails the
    test if anything tries to insert a paper or a post."""

    def __init__(self, existing=None):
        self.existing = existing or []
        self.inserted = None
        self.updated = None
        self._table = None

    def table(self, name):
        if name != "inbound_unresolved":
            pytest.fail(f"must not write {name} for an unresolved link")
        self._table = name
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def update(self, row):
        self.updated = row
        return self

    def execute(self):
        if self.inserted is not None or self.updated is not None:
            return types.SimpleNamespace(data=[])
        return types.SimpleNamespace(data=self.existing)


def test_import_background_queues_an_unresolved_link_instead_of_dropping_it(monkeypatch):
    # The whole point: a link the resolver can't read used to vanish, leaving only
    # a log line that Fly keeps for about a week.
    monkeypatch.setattr(
        teams_integration,
        "fetch_metadata",
        lambda url, **kw: _fake_meta(title=None, doi=None, source="unknown"),
    )
    cap = _QueueCapture()
    monkeypatch.setattr(teams_integration, "service_client", lambda: cap)

    out = teams_integration.import_paper_background("t1", "https://paywalled.example/x", "Ellen")

    assert out is None
    assert cap.inserted["team_id"] == "t1"
    assert cap.inserted["url"] == "https://paywalled.example/x"
    assert cap.inserted["sender_label"] == "Ellen"
    # No id in the URL -> a publisher shape we don't know, not a derivation bug.
    assert cap.inserted["reason"] == "no_identifier"


def test_queue_reason_separates_an_unknown_publisher_from_a_bad_identifier(monkeypatch):
    # The distinction is what says whether to write code or just retry later.
    monkeypatch.setattr(
        teams_integration,
        "fetch_metadata",
        lambda url, **kw: _fake_meta(title=None, doi=None, source="crossref"),
    )
    cap = _QueueCapture()
    monkeypatch.setattr(teams_integration, "service_client", lambda: cap)
    teams_integration.import_paper_background("t1", "https://doi.org/10.1/nope", "Ellen")
    assert cap.inserted["reason"] == "identifier_unresolved"


def test_repeat_mention_bumps_attempts_rather_than_duplicating(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "fetch_metadata",
        lambda url, **kw: _fake_meta(title=None, doi=None, source="unknown"),
    )
    cap = _QueueCapture(existing=[{"id": 7, "attempts": 2}])
    monkeypatch.setattr(teams_integration, "service_client", lambda: cap)

    teams_integration.import_paper_background("t1", "https://paywalled.example/x", "Ellen")

    assert cap.inserted is None  # unique(team_id, url_norm) means one row per link
    assert cap.updated["attempts"] == 3


def test_recording_failure_never_breaks_the_import(monkeypatch):
    # Failing to record a failure must not escalate a dropped paper into a 500.
    monkeypatch.setattr(
        teams_integration,
        "fetch_metadata",
        lambda url, **kw: _fake_meta(title=None, doi=None, source="unknown"),
    )
    monkeypatch.setattr(
        teams_integration,
        "service_client",
        lambda: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    assert teams_integration.import_paper_background("t1", "https://x.example/y", "Ellen") is None


def test_import_background_never_raises(monkeypatch):
    monkeypatch.setattr(
        teams_integration,
        "fetch_metadata",
        lambda url, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # A resolve failure is logged, not raised (it runs as a fire-and-forget task).
    teams_integration.import_paper_background("t1", "https://arxiv.org/abs/1", "Ellen")
