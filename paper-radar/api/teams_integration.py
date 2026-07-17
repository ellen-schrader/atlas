"""Mirror lab posts into a Microsoft Teams channel (docs/teams-integration-plan.md).

Outbound direction (M1): when a paper is posted to a lab from the web app,
build an Adaptive Card and POST it to the lab's Power Automate "Workflows"
webhook URL ("When a Teams webhook request is received" trigger — the
sanctioned replacement for the retired O365 incoming webhooks).

Configured per lab in the team_integrations table (Settings → Lab management,
owner-only). Unconfigured or disabled labs are a silent no-op, and nothing in
the notify path ever raises: posting to Teams must never break, slow, or roll
back an in-app post, so every entry point catches and logs.

Security: the webhook URL is attacker-influencable data that the SERVER posts
to — an SSRF sink. It is validated on save (the API endpoint), on write (a DB
CHECK constraint), and again on send (`validate_webhook_url` below), and the
POST itself never follows redirects, so a webhook that 302s at internal infra
fails instead of being fetched.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from paper_radar.ingest import url_guard

from .config import get_api_settings
from .supa import service_client

log = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds; the card is fire-and-forget, never worth waiting longer
_MAX_AUTHORS = 3

# Only Microsoft Power Automate endpoints. The suffixes are dot-prefixed so
# "evillogic.azure.com" can't match, and the base domains are Microsoft-owned,
# which also neutralizes DNS games — an attacker can't point *.logic.azure.com
# at internal infra.
_ALLOWED_WEBHOOK_SUFFIXES = (".logic.azure.com", ".api.powerplatform.com")


def validate_webhook_url(url: str) -> str:
    """The normalized webhook URL, or raise ValueError with a user-facing reason.

    Layered checks (matches the team_integrations DB CHECK, plus what a regex
    can't see): url_guard's SSRF screen (scheme, length, internal names and IP
    literals), then https-only, no embedded credentials, default port only, and
    the Power Automate host allowlist. DNS resolution is deliberately skipped —
    the allowlisted domains are Microsoft's, so resolving them adds flakiness,
    not safety.
    """
    try:
        url_guard.validate_public_url(url, resolve=False)
    except url_guard.BlockedUrl as exc:
        raise ValueError(str(exc)) from exc
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise ValueError("The webhook URL must use https.")
    if parts.username is not None or parts.password is not None:
        raise ValueError("The webhook URL must not contain credentials.")
    try:
        port_ok = parts.port in (None, 443)
    except ValueError:  # non-numeric port
        port_ok = False
    if not port_ok:
        raise ValueError("The webhook URL must use the default https port.")
    # No rstrip('.'): a trailing-dot host is deliberately rejected here (it
    # would also fail the DB CHECK) instead of being silently normalized.
    host = parts.hostname or ""
    if not host.endswith(_ALLOWED_WEBHOOK_SUFFIXES):
        raise ValueError(
            "That doesn't look like a Power Automate webhook URL "
            "(expected a *.logic.azure.com or *.api.powerplatform.com address)."
        )
    # Keep this validator strictly stronger than the team_integrations DB CHECK
    # so a value it accepts can never be rejected by the constraint (which would
    # surface as an opaque write error): the host must start alphanumeric and
    # there must be a path. Power Automate URLs always satisfy both.
    if not host[0].isalnum():
        raise ValueError("That webhook host isn't valid.")
    if not parts.path or parts.path == "/":
        raise ValueError("That webhook URL is missing its path — copy the whole URL from Teams.")
    # Normalize: lowercase the host so the stored value satisfies the DB CHECK
    # (no userinfo is present — rejected above — so lowercasing netloc is safe).
    return urlunsplit(parts._replace(netloc=parts.netloc.lower()))


def webhook_url_for_team(team_id: str) -> str | None:
    """The lab's Workflows webhook URL, or None if not configured or disabled.

    Single source of truth: the owner-managed team_integrations row. A disabled
    row is OFF, and deleting it (Settings → Disconnect) stops posting — there is
    deliberately no env-map fallback that could keep a "disconnected" lab live.
    """
    found = (
        service_client()
        .table("team_integrations")
        .select("webhook_url, enabled")
        .eq("team_id", team_id)
        .limit(1)
        .execute()
    )
    if not found.data:
        return None
    row = found.data[0]
    return row["webhook_url"] if row["enabled"] else None


# TextBlock text renders a CommonMark subset (emphasis, links, lists), so any
# user- or metadata-controlled string must be escaped or it becomes a markdown
# injection vector (a note or display name of "[x](https://evil)" would render
# as a live link). Backslash first so escapes aren't themselves re-escaped.
_MD_CHARS = "\\`*_~[]()"


def _md_escape(text: str) -> str:
    for c in _MD_CHARS:
        text = text.replace(c, f"\\{c}")
    return text


# Abstracts can be a page long. The card shows a short teaser and, when the full
# text is longer, a "Show more" toggle that reveals it in place — no truncation.
_ABSTRACT_PREVIEW_CHARS = 240


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    # Cut on a word boundary so the ellipsis doesn't land mid-word.
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "…"


def _abstract_blocks(abstract: str) -> list[dict]:
    """Body elements for the abstract.

    Short abstracts render whole. A longer one shows a truncated preview plus a
    "Show more" affordance that swaps the preview for the full text in place and
    offers "Show less" to re-collapse — no cut-off, no popup. The affordance is a
    link (accent-coloured text in a container whose selectAction toggles the
    visibility), not a button, so it doesn't add button chrome to the card.
    Element ids are card-local, so the fixed names don't collide (each posted
    card is its own message).
    """
    full = abstract.strip()
    common = {"type": "TextBlock", "wrap": True, "spacing": "Medium"}
    if len(full) <= _ABSTRACT_PREVIEW_CHARS:
        return [{**common, "text": _md_escape(full)}]

    preview = _md_escape(_truncate(full, _ABSTRACT_PREVIEW_CHARS))

    def _link(is_more: bool) -> dict:
        # "Show more" is shown first and expands; "Show less" starts hidden and
        # collapses. `expand` is the state a tap moves to, so both set the same
        # four ids to consistent visibilities. selectAction on the container
        # renders as a plain click target (no button), and the accent colour
        # makes the text read as a link.
        expand = is_more
        return {
            "type": "Container",
            "id": "abstract-more" if is_more else "abstract-less",
            "isVisible": is_more,
            "spacing": "Small",
            "selectAction": {
                "type": "Action.ToggleVisibility",
                "targetElements": [
                    {"elementId": "abstract-preview", "isVisible": not expand},
                    {"elementId": "abstract-full", "isVisible": expand},
                    {"elementId": "abstract-more", "isVisible": not expand},
                    {"elementId": "abstract-less", "isVisible": expand},
                ],
            },
            "items": [
                {
                    "type": "TextBlock",
                    "text": "Show more" if is_more else "Show less",
                    "color": "Accent",
                    "wrap": True,
                }
            ],
        }

    return [
        {**common, "id": "abstract-preview", "text": preview},
        {**common, "id": "abstract-full", "text": _md_escape(full), "isVisible": False},
        _link(is_more=True),
        _link(is_more=False),
    ]


def _click_safe(url: str | None) -> str | None:
    """A URL safe to place behind a click action — http(s) only.

    The paper URL is user-supplied, and Action.OpenUrl opens whatever scheme it
    carries. Teams sanitizes button URLs, but we don't rely on the client: a
    ``javascript:``/``file:``/``data:`` URL is dropped here so it can never
    become a clickable button in the channel.
    """
    if not url:
        return None
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return None
    return url if scheme in ("http", "https") else None


def _authors_line(authors: list[str] | None) -> str | None:
    if not authors:
        return None
    shown = ", ".join(authors[:_MAX_AUTHORS])
    return f"{shown} et al." if len(authors) > _MAX_AUTHORS else shown


def build_paper_card(
    *,
    url: str,
    title: str | None = None,
    authors: list[str] | None = None,
    venue: str | None = None,
    year: int | None = None,
    abstract: str | None = None,
    note: str | None = None,
    posted_by: str | None = None,
    atlas_url: str | None = None,
) -> dict:
    """An Adaptive Card announcing one paper post.

    Layout: title as a header, then authors, then venue/year, an abstract
    preview, an optional note, and a footer. The paper URL and (when provided)
    the Atlas deep link are rendered as buttons rather than inline links, so
    both are one tap away and neither depends on markdown escaping.
    """
    # Header — the title as its own bold line (not a link; the buttons carry the
    # links). Falls back to the URL only when there's no title.
    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": _md_escape(title or url),
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        }
    ]

    authors_line = _authors_line(authors)
    if authors_line:
        body.append(
            {
                "type": "TextBlock",
                "text": _md_escape(authors_line),
                "wrap": True,
                "spacing": "None",
            }
        )

    venue_year = " · ".join(str(p) for p in (venue, year) if p)
    if venue_year:
        body.append(
            {
                "type": "TextBlock",
                "text": _md_escape(venue_year),
                "isSubtle": True,
                "wrap": True,
                "spacing": "None",
            }
        )

    if abstract and abstract.strip():
        body.extend(_abstract_blocks(abstract))

    if note:
        body.append(
            {
                "type": "TextBlock",
                "text": f"“{_md_escape(note)}”",
                "wrap": True,
                "isSubtle": True,
                "spacing": "Medium",
            }
        )

    footer = f"Posted by {_md_escape(posted_by)} via Atlas" if posted_by else "Posted via Atlas"
    body.append(
        {
            "type": "TextBlock",
            "text": footer,
            "isSubtle": True,
            "size": "Small",
            "wrap": True,
            "spacing": "Medium",
        }
    )

    # Action.OpenUrl values are plain JSON strings the client opens directly (not
    # markdown, so no escaping needed) — but only http(s) may become a clickable
    # button, so a dangerous scheme in the user-supplied paper URL is never armed.
    actions: list[dict] = []
    paper_link = _click_safe(url)
    if paper_link:
        actions.append({"type": "Action.OpenUrl", "title": "View paper", "url": paper_link})
    atlas_link = _click_safe(atlas_url)
    if atlas_link:
        actions.append({"type": "Action.OpenUrl", "title": "Open in Atlas", "url": atlas_link})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


def build_test_card(team_name: str | None) -> dict:
    """The card the Settings "Send test card" button fires."""
    where = f" for {_md_escape(team_name)}" if team_name else ""
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": [
            {
                "type": "TextBlock",
                "text": "Atlas is connected ✅",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    f"Papers posted{where} will appear in this channel. "
                    "This is a test card sent from Settings."
                ),
                "isSubtle": True,
                "wrap": True,
            },
        ],
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect from a webhook.

    The URL was validated against the Power Automate allowlist, but a redirect
    is a fresh, unvalidated target — following it would let a (mis)configured
    endpoint bounce the server's POST anywhere, including internal addresses.
    A webhook has no business redirecting; treat 3xx as failure.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib turns this into an HTTPError -> logged as failure


_webhook_opener = urllib.request.build_opener(_NoRedirect)


def post_to_teams(webhook_url: str, card: dict) -> bool:
    """POST one Adaptive Card to a Workflows webhook. Logs and returns False on failure.

    The URL must already be validated (validate_webhook_url) — callers in this
    module do so at send time, not just at save time.
    """
    payload = {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # urlopen raises (HTTPError) for any non-2xx status — including the
        # redirects _NoRedirect refuses — so success needs no status check.
        with _webhook_opener.open(req, timeout=_TIMEOUT):  # noqa: S310 (validated above)
            pass
    except Exception as exc:
        log.warning("posting card to Teams failed: %s", exc)
        return False
    return True


def _display_name(user_id: str | None) -> str | None:
    if not user_id:
        return None
    try:
        found = (
            service_client()
            .table("profiles")
            .select("display_name")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        return found.data[0]["display_name"] if found.data else None
    except Exception as exc:
        log.warning("looking up poster display name failed: %s", exc)
        return None


def _atlas_paper_url(paper_id: str | None) -> str | None:
    """Deep link to the paper in the Atlas web app, or None if unconfigured.

    The web app opens a paper via the global `?paper=<id>` modal on any route,
    so the canonical link is `<web>/?paper=<id>`.
    """
    if not paper_id:
        return None
    base = get_api_settings().atlas_web_url.strip()
    if not base:
        return None
    return f"{base.rstrip('/')}/?paper={paper_id}"


def notify_paper_posted(
    team_id: str,
    *,
    url: str,
    paper_id: str | None = None,
    title: str | None = None,
    authors: list[str] | None = None,
    venue: str | None = None,
    year: int | None = None,
    abstract: str | None = None,
    note: str | None = None,
    posted_by_id: str | None = None,
) -> None:
    """Background task: mirror one new post to the lab's Teams channel, if mapped."""
    try:
        webhook_url = webhook_url_for_team(team_id)
        if not webhook_url:
            return
        try:
            # Re-validate at send time: the stored value may predate (or have
            # dodged) save-time checks, and this is the last line before the
            # server actually connects to it.
            webhook_url = validate_webhook_url(webhook_url)
        except ValueError as exc:
            log.warning("refusing configured Teams webhook for team %s: %s", team_id, exc)
            return
        card = build_paper_card(
            url=url,
            title=title,
            authors=authors,
            venue=venue,
            year=year,
            abstract=abstract,
            note=note,
            posted_by=_display_name(posted_by_id),
            atlas_url=_atlas_paper_url(paper_id),
        )
        post_to_teams(webhook_url, card)
    except Exception as exc:
        log.warning("Teams notification for team %s failed: %s", team_id, exc)
