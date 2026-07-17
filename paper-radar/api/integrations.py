"""Per-lab integration endpoints (the Teams webhook, Settings → Lab management).

Access control is delegated to RLS: every read and write here runs through the
caller's ``user_client``, and the ``team_integrations`` policies are owner-only
on every verb — a non-owner sees "not configured" and writes zero rows. The
service role is never used in this module.

Secret handling: the webhook URL is a bearer capability (holding it lets you
post cards into the channel). It only ever travels client → server (the owner
pastes it once). It is NEVER returned to the browser — reads expose just the
host — and toggling on/off goes through a URL-free ``PATCH`` so the capability
stays server-side after the initial save.

The URL is also an SSRF sink (the server POSTs to it), so a save validates it
(``teams_integration.validate_webhook_url``) on top of the table's CHECK
constraint, and the send path re-validates independently.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import teams_integration
from .deps import require_token
from .supa import get_user_id, user_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/teams", tags=["integrations"])


class TeamsIntegrationOut(BaseModel):
    configured: bool
    # The webhook host only — never the full URL (that's a bearer capability).
    host: str | None = None
    enabled: bool = False
    # Whether inbound (@Atlas → Atlas) is set up — never the secret itself.
    inbound_configured: bool = False
    updated_at: str | None = None


class TeamsIntegrationSave(BaseModel):
    team_id: str
    webhook_url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True


class TeamsEnabledPatch(BaseModel):
    team_id: str
    enabled: bool


class TeamsInboundSave(BaseModel):
    team_id: str
    secret: str = Field(min_length=1, max_length=1024)


class TeamsTestRequest(BaseModel):
    team_id: str


def _require_user(token: str) -> str:
    user_id = get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user_id


def _integration_row(token: str, team_id: str) -> dict | None:
    rows = (
        user_client(token)
        .table("team_integrations")
        .select("webhook_url, enabled, updated_at, inbound_secret")
        .eq("team_id", team_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _host(url: str | None) -> str | None:
    return urlsplit(url).hostname if url else None


def _out(row: dict | None) -> TeamsIntegrationOut:
    if row is None:
        return TeamsIntegrationOut(configured=False)
    return TeamsIntegrationOut(
        configured=True,
        host=_host(row.get("webhook_url")),
        enabled=row["enabled"],
        # Presence only — the token never leaves the server.
        inbound_configured=bool(row.get("inbound_secret")),
        updated_at=row.get("updated_at"),
    )


@router.get("", response_model=TeamsIntegrationOut)
def get_integration(team_id: str, token: str = Depends(require_token)) -> TeamsIntegrationOut:
    """The lab's Teams connection (host + status only). RLS hides it from non-owners."""
    _require_user(token)
    return _out(_integration_row(token, team_id))


@router.put("", response_model=TeamsIntegrationOut)
def save_integration(
    req: TeamsIntegrationSave, token: str = Depends(require_token)
) -> TeamsIntegrationOut:
    """Create or replace the lab's webhook (owners only, via RLS)."""
    user_id = _require_user(token)
    try:
        webhook_url = teams_integration.validate_webhook_url(req.webhook_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = {
        "team_id": req.team_id,
        "webhook_url": webhook_url,
        "enabled": req.enabled,
        "created_by": user_id,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    try:
        # upsert returns the persisted row (representation), so inbound_secret set
        # on an earlier save is reflected rather than reported as cleared.
        saved = user_client(token).table("team_integrations").upsert(row).execute().data or []
    except Exception as exc:
        _reraise_write_error(exc, "save the Teams connection")
    return _out(saved[0] if saved else row)


@router.patch("", response_model=TeamsIntegrationOut)
def set_enabled(req: TeamsEnabledPatch, token: str = Depends(require_token)) -> TeamsIntegrationOut:
    """Pause/resume without moving the secret: flip `enabled` on the existing row.

    An UPDATE (not upsert) so it only touches a row the owner already has; a
    non-owner or a missing row updates nothing (RLS), reported as not-configured.
    """
    _require_user(token)
    try:
        updated = (
            user_client(token)
            .table("team_integrations")
            .update({"enabled": req.enabled, "updated_at": datetime.now(UTC).isoformat()})
            .eq("team_id", req.team_id)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        _reraise_write_error(exc, "update the Teams connection")
    if not updated:
        raise HTTPException(status_code=404, detail="No Teams connection is configured")
    return _out(updated[0])


@router.delete("", response_model=TeamsIntegrationOut)
def delete_integration(team_id: str, token: str = Depends(require_token)) -> TeamsIntegrationOut:
    """Disconnect Teams for the lab. A non-owner's delete matches zero rows (RLS)."""
    _require_user(token)
    user_client(token).table("team_integrations").delete().eq("team_id", team_id).execute()
    return TeamsIntegrationOut(configured=False)


@router.put("/inbound", response_model=TeamsIntegrationOut)
def save_inbound_secret(
    req: TeamsInboundSave, token: str = Depends(require_token)
) -> TeamsIntegrationOut:
    """Store the lab's inbound (Outgoing Webhook) HMAC token — owners only, via RLS.

    An UPDATE on the existing row (the outbound webhook must be connected first),
    so a non-owner or a missing row touches nothing. The token is validated as
    base64 and never returned to the browser.
    """
    _require_user(token)
    try:
        secret = teams_integration.normalize_inbound_secret(req.secret)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        updated = (
            user_client(token)
            .table("team_integrations")
            .update({"inbound_secret": secret, "updated_at": datetime.now(UTC).isoformat()})
            .eq("team_id", req.team_id)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        _reraise_write_error(exc, "save the inbound connection")
    if not updated:
        raise HTTPException(
            status_code=404, detail="Connect the outbound webhook first, then add inbound."
        )
    return _out(updated[0])


@router.delete("/inbound", response_model=TeamsIntegrationOut)
def clear_inbound_secret(
    team_id: str, token: str = Depends(require_token)
) -> TeamsIntegrationOut:
    """Turn off inbound (@Atlas) ingestion by clearing the token — owners only."""
    _require_user(token)
    updated = (
        user_client(token)
        .table("team_integrations")
        .update({"inbound_secret": None, "updated_at": datetime.now(UTC).isoformat()})
        .eq("team_id", team_id)
        .execute()
        .data
        or []
    )
    if not updated:
        raise HTTPException(status_code=404, detail="No Teams connection is configured")
    return _out(updated[0])


@router.post("/inbound/{team_id}")
async def inbound_webhook(
    team_id: str, request: Request, background: BackgroundTasks
) -> dict:
    """Receive an "@Atlas <link>" message from a Teams Outgoing Webhook and import it.

    PUBLIC — no JWT. The per-team HMAC token (from team_integrations, selected by
    the team_id in the path) is the only authenticator: we verify the signature
    over the raw body before parsing anything. We reply fast (link present? already
    in the lab?) and do the slow resolve + insert + embed in the background, so we
    stay inside Teams' ~5 s synchronous-reply window.
    """
    raw = await request.body()
    secret = await run_in_threadpool(teams_integration.inbound_secret_for_team, team_id)
    if not secret:
        # Don't distinguish "no such team" from "inbound off" — generic 404.
        raise HTTPException(status_code=404, detail="Not configured")
    if not teams_integration.verify_teams_signature(
        secret, raw, request.headers.get("Authorization")
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Malformed payload") from exc
    text = payload.get("text") or ""
    sender = (payload.get("from") or {}).get("name") or None

    # The plan is cheap DB-only work (link present? already in the lab?) — well
    # inside Teams' ~5 s reply window. Offloaded so it never blocks the event loop.
    plan = await run_in_threadpool(teams_integration.plan_inbound_import, team_id, text)

    if plan.status == "no_url":
        return teams_integration.inbound_reply(
            "I couldn't find a paper link there. Mention me with a link, e.g. "
            "`@Atlas https://arxiv.org/abs/…`"
        )
    if plan.status == "already":
        return teams_integration.inbound_reply("👍 That paper is already in the lab.")

    background.add_task(teams_integration.import_paper_background, team_id, plan.url, sender)
    return teams_integration.inbound_reply("⏳ Adding that paper to Atlas — it'll appear shortly.")


@router.post("/test")
def send_test_card(req: TeamsTestRequest, token: str = Depends(require_token)) -> dict:
    """Fire a sample card through the saved webhook so the owner sees it working.

    Reads the row as the caller, so RLS makes this owner-only; the URL is
    re-validated before the server connects to it, and never leaves the server.
    """
    _require_user(token)
    row = _integration_row(token, req.team_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No Teams connection is configured")
    if not row["enabled"]:
        raise HTTPException(status_code=400, detail="The Teams connection is disabled")
    try:
        webhook_url = teams_integration.validate_webhook_url(row["webhook_url"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    teams = (
        user_client(token).table("teams").select("name").eq("id", req.team_id).limit(1).execute()
    )
    team_name = teams.data[0]["name"] if teams.data else None

    if not teams_integration.post_to_teams(
        webhook_url, teams_integration.build_test_card(team_name)
    ):
        raise HTTPException(
            status_code=502,
            detail="Teams did not accept the card — check that the workflow still exists",
        )
    return {"ok": True}


def _reraise_write_error(exc: Exception, action: str) -> None:
    """Map an RLS denial to 403; let anything else surface as a real 500.

    A CHECK-constraint violation can't reach here — validate_webhook_url is
    strictly stronger than the DB CHECK — so a non-42501 error is a genuine
    server/infra fault and must not masquerade as a 400 input rejection.
    """
    if getattr(exc, "code", None) == "42501":
        raise HTTPException(
            status_code=403, detail="Only a lab owner can manage the Teams connection"
        ) from exc
    log.error("could not %s: %s", action, exc)
    raise HTTPException(status_code=500, detail=f"Could not {action}") from exc
