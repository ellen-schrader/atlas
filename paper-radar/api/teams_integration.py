"""Mirror lab posts into a Microsoft Teams channel (docs/teams-integration-plan.md).

Outbound direction (M1): when a paper is posted to a lab from the web app,
build an Adaptive Card and POST it to the lab's Power Automate "Workflows"
webhook URL ("When a Teams webhook request is received" trigger — the
sanctioned replacement for the retired O365 incoming webhooks).

Configured via TEAMS_WEBHOOK_URLS, a JSON map of team id (or slug) → webhook
URL. Unconfigured labs are a silent no-op, and nothing in this module ever
raises: posting to Teams must never break, slow, or roll back an in-app post,
so every entry point catches and logs.
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

    TEAMS_WEBHOOK_URLS keys may be team uuids or the human-friendly slug; the
    slug lookup costs one service-role query and only runs on a uuid miss.
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
    if urls.get(team_id):
        return urls[team_id]
    found = (
        service_client().table("teams").select("slug").eq("id", team_id).limit(1).execute()
    )
    slug = found.data[0]["slug"] if found.data else None
    return urls.get(slug) or None


def _md_link_text(text: str) -> str:
    """Escape brackets so a title can't terminate its own markdown link."""
    return text.replace("[", "\\[").replace("]", "\\]")


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
            "text": f"[{_md_link_text(title or url)}]({url})",
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
            {"type": "TextBlock", "text": " · ".join(byline), "isSubtle": True, "wrap": True}
        )

    if note:
        body.append({"type": "TextBlock", "text": note, "wrap": True})

    footer = f"Posted by {posted_by} via Atlas" if posted_by else "Posted via Atlas"
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
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310 (operator-configured URL)
            status = resp.status
    except Exception as exc:
        log.warning("posting card to Teams failed: %s", exc)
        return False
    if status >= 300:
        log.warning("posting card to Teams failed: HTTP %s", status)
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
