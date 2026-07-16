"""Per-lab integration endpoints (the Teams webhook, Settings → Lab management).

Access control is delegated to RLS: every read and write here runs through the
caller's ``user_client``, and the ``team_integrations`` policies are owner-only
on every verb — a non-owner sees "not configured" and writes zero rows. The
service role is never used in this module.

The webhook URL is an SSRF sink (the server POSTs to it), so a save validates
it (``teams_integration.validate_webhook_url``) on top of the table's CHECK
constraint, and the send path re-validates independently.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import teams_integration
from .deps import require_token
from .supa import get_user_id, user_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/teams", tags=["integrations"])


class TeamsIntegrationOut(BaseModel):
    configured: bool
    webhook_url: str | None = None
    enabled: bool = False
    updated_at: str | None = None


class TeamsIntegrationSave(BaseModel):
    team_id: str
    webhook_url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True


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
        .select("webhook_url, enabled, updated_at")
        .eq("team_id", team_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


@router.get("", response_model=TeamsIntegrationOut)
def get_integration(team_id: str, token: str = Depends(require_token)) -> TeamsIntegrationOut:
    """The lab's Teams connection. RLS-scoped: a non-owner sees 'not configured'."""
    _require_user(token)
    row = _integration_row(token, team_id)
    if row is None:
        return TeamsIntegrationOut(configured=False)
    return TeamsIntegrationOut(
        configured=True,
        webhook_url=row["webhook_url"],
        enabled=row["enabled"],
        updated_at=row["updated_at"],
    )


@router.put("", response_model=TeamsIntegrationOut)
def save_integration(
    req: TeamsIntegrationSave, token: str = Depends(require_token)
) -> TeamsIntegrationOut:
    """Create or update the lab's Teams connection (owners only, via RLS)."""
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
        user_client(token).table("team_integrations").upsert(row).execute()
    except Exception as exc:
        # RLS denial (not an owner) surfaces as 42501.
        if getattr(exc, "code", None) == "42501":
            raise HTTPException(
                status_code=403, detail="Only a lab owner can manage the Teams connection"
            ) from exc
        log.warning("saving Teams integration for team %s failed: %s", req.team_id, exc)
        raise HTTPException(
            status_code=400, detail="Could not save the Teams connection"
        ) from exc
    return TeamsIntegrationOut(
        configured=True, webhook_url=webhook_url, enabled=req.enabled, updated_at=row["updated_at"]
    )


@router.delete("", response_model=TeamsIntegrationOut)
def delete_integration(team_id: str, token: str = Depends(require_token)) -> TeamsIntegrationOut:
    """Disconnect Teams for the lab. A non-owner's delete matches zero rows (RLS)."""
    _require_user(token)
    user_client(token).table("team_integrations").delete().eq("team_id", team_id).execute()
    return TeamsIntegrationOut(configured=False)


@router.post("/test")
def send_test_card(req: TeamsTestRequest, token: str = Depends(require_token)) -> dict:
    """Fire a sample card through the saved webhook so the owner sees it working.

    Reads the row as the caller, so RLS makes this owner-only; the URL is
    re-validated before the server connects to it.
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
