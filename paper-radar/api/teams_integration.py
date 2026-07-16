"""Mirror lab posts into a Microsoft Teams channel (docs/teams-integration-plan.md).

Outbound direction (M1): when a paper is posted to a lab from the web app,
build an Adaptive Card and POST it to the lab's Power Automate "Workflows"
webhook URL ("When a Teams webhook request is received" trigger — the
sanctioned replacement for the retired O365 incoming webhooks).

Configured per lab in the team_integrations table (Settings → Lab management,
owner-only), with the operator-level TEAMS_WEBHOOK_URLS env map (team uuid →
URL) as a fallback. Unconfigured labs are a silent no-op, and nothing in the
notify path ever raises: posting to Teams must never break, slow, or roll
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
    # Normalize: lowercase the host so the stored value satisfies the DB CHECK
    # (no userinfo is present — rejected above — so lowercasing netloc is safe).
    return urlunsplit(parts._replace(netloc=parts.netloc.lower()))


def webhook_url_for_team(team_id: str) -> str | None:
    """The lab's Workflows webhook URL, or None if not configured/disabled.

    The team_integrations row (owner-managed in Settings) wins; an explicitly
    disabled row is OFF even if the env fallback maps the team. The env map
    (TEAMS_WEBHOOK_URLS, keyed by team uuid) covers labs configured before the
    table existed.
    """
    found = (
        service_client()
        .table("team_integrations")
        .select("webhook_url, enabled")
        .eq("team_id", team_id)
        .limit(1)
        .execute()
    )
    if found.data:
        row = found.data[0]
        return row["webhook_url"] if row["enabled"] else None

    raw = get_api_settings().teams_webhook_urls
    if not raw:
        return None
    try:
        urls = json.loads(raw)
    except ValueError:
        log.warning("TEAMS_WEBHOOK_URLS is not valid JSON; Teams posting disabled")
        return None
    if not isinstance(urls, dict):
        log.warning("TEAMS_WEBHOOK_URLS must be a JSON object; Teams posting disabled")
        return None
    return urls.get(team_id) or None


# TextBlock text renders a CommonMark subset (emphasis, links, lists), so any
# user- or metadata-controlled string must be escaped or it becomes a markdown
# injection vector (a note or display name of "[x](https://evil)" would render
# as a live link). Backslash first so escapes aren't themselves re-escaped.
_MD_CHARS = "\\`*_~[]()"


def _md_escape(text: str) -> str:
    for c in _MD_CHARS:
        text = text.replace(c, f"\\{c}")
    return text


def _link_target(url: str) -> str:
    """Percent-encode parens so a URL (e.g. a (SICI)-style DOI) can't end the link."""
    return url.replace("(", "%28").replace(")", "%29")


def build_paper_card(
    *,
    url: str,
    title: str | None = None,
    authors: list[str] | None = None,
    venue: str | None = None,
    year: int | None = None,
    note: str | None = None,
    posted_by: str | None = None,
) -> dict:
    """An Adaptive Card announcing one paper post."""
    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"[{_md_escape(title or url)}]({_link_target(url)})",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        }
    ]

    byline: list[str] = []
    if authors:
        shown = ", ".join(authors[:_MAX_AUTHORS])
        byline.append(f"{shown} et al." if len(authors) > _MAX_AUTHORS else shown)
    venue_year = " ".join(str(p) for p in (venue, year) if p)
    if venue_year:
        byline.append(venue_year)
    if byline:
        body.append(
            {
                "type": "TextBlock",
                "text": _md_escape(" · ".join(byline)),
                "isSubtle": True,
                "wrap": True,
            }
        )

    if note:
        body.append({"type": "TextBlock", "text": _md_escape(note), "wrap": True})

    footer = f"Posted by {_md_escape(posted_by)} via Atlas" if posted_by else "Posted via Atlas"
    body.append(
        {"type": "TextBlock", "text": footer, "isSubtle": True, "size": "Small", "wrap": True}
    )

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }


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


def notify_paper_posted(
    team_id: str,
    *,
    url: str,
    title: str | None = None,
    authors: list[str] | None = None,
    venue: str | None = None,
    year: int | None = None,
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
            note=note,
            posted_by=_display_name(posted_by_id),
        )
        post_to_teams(webhook_url, card)
    except Exception as exc:
        log.warning("Teams notification for team %s failed: %s", team_id, exc)
