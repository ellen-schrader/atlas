"""Mirror lab posts into a Microsoft Teams channel (docs/teams-integration-plan.md).

Outbound direction (M1): when a paper is posted to a lab from the web app,
build an Adaptive Card and POST it to the lab's Power Automate "Workflows"
webhook URL ("When a Teams webhook request is received" trigger — the
sanctioned replacement for the retired O365 incoming webhooks).

Configured via TEAMS_WEBHOOK_URLS, a JSON map of team uuid → webhook URL.
Unconfigured labs are a silent no-op, and nothing in this module ever raises:
posting to Teams must never break, slow, or roll back an in-app post, so
every entry point catches and logs.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from .config import get_api_settings
from .supa import service_client

log = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds; the card is fire-and-forget, never worth waiting longer
_MAX_AUTHORS = 3


def webhook_url_for_team(team_id: str) -> str | None:
    """The team's Workflows webhook URL, or None if not configured.

    TEAMS_WEBHOOK_URLS is keyed by team uuid — not slug, because slugs double
    as the lab invite code and regenerate_team_code rewrites them, which would
    silently kill a slug-keyed mapping.
    """
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


def post_to_teams(webhook_url: str, card: dict) -> bool:
    """POST one Adaptive Card to a Workflows webhook. Logs and returns False on failure."""
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
        # urlopen raises (HTTPError) for any non-2xx status, so success needs
        # no status check.
        with urllib.request.urlopen(req, timeout=_TIMEOUT):  # noqa: S310 (operator-configured URL)
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
