"""Projects endpoints (docs/PROJECTS_PLAN.md, PR 1).

Reading projects and their closeness, adding and dismissing papers, sharing,
following tags and labs, and deleting a project all go straight to Supabase from
the web app, where RLS checks the feature switch and who can see what. This
router holds only what needs the server: the description's embedding, because
the Voyage key is server-side.

Every endpoint answers 404 unless the projects feature is on for the caller in
that lab, so the feature isn't advertised while it is dark.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import embeddings
from .deps import require_feature, require_token
from .supa import user_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])

FEATURE = "projects"
_NOT_FOUND = "Not Found"  # FastAPI's own wording for an unknown route
# What the client gets back: never the 1024-dim embedding.
_COLUMNS = (
    "id, team_id, owner_id, name, description, visibility, suggest_level, created_at, updated_at"
)

Visibility = Literal["private", "lab", "people"]
SuggestLevel = Literal["fewer", "balanced", "more"]


class ProjectOut(BaseModel):
    id: str
    team_id: str
    owner_id: str | None  # None once the owner has deleted their account
    name: str
    description: str
    visibility: Visibility
    suggest_level: SuggestLevel
    created_at: str
    updated_at: str


class ProjectCreate(BaseModel):
    team_id: UUID
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    visibility: Visibility = "private"


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    visibility: Visibility | None = None
    suggest_level: SuggestLevel | None = None


def _embed(user_id: str, description: str) -> list[float] | None:
    """The description's embedding, or None when there is none or Voyage is
    unavailable: a project works without it once it holds three papers, so a
    failed embedding never fails the save."""
    if not description:
        return None
    # Bound the paid call so a caller can't loop saves to drain the Voyage quota.
    from .app import _query_limiter  # lazy: app imports this module

    _query_limiter.check(user_id)
    try:
        return embeddings.embed_query(description)
    except embeddings.EmbeddingError as exc:
        log.warning("project description not embedded: %s %s", exc, exc.detail)
        return None


@router.post("", response_model=ProjectOut)
def create_project(req: ProjectCreate, token: str = Depends(require_token)) -> ProjectOut:
    """Create a project in one of the caller's labs, owned by them."""
    team_id = str(req.team_id)
    user_id = require_feature(token, team_id, FEATURE)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the project a name.")
    description = " ".join(req.description.split())
    rows = (
        user_client(token)
        .table("projects")
        .insert(
            {
                "team_id": team_id,
                "owner_id": user_id,
                "name": name,
                "description": description,
                "description_embedding": _embed(user_id, description),
                "visibility": req.visibility,
            }
        )
        .execute()
        .data
    )
    rows = (
        user_client(token).table("projects").select(_COLUMNS).eq("id", rows[0]["id"]).execute().data
    )
    return ProjectOut(**rows[0])


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID, req: ProjectPatch, token: str = Depends(require_token)
) -> ProjectOut:
    """Rename, re-describe, share or tune a project. Only its owner can; RLS
    turns anyone else's update into no rows."""
    uc = user_client(token)
    found = (
        uc.table("projects")
        .select("team_id, owner_id, description")
        .eq("id", str(project_id))
        .execute()
        .data
    )
    if not found:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    user_id = require_feature(token, found[0]["team_id"], FEATURE)
    if found[0]["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="Only the project's owner can change it.")

    updates: dict = {"updated_at": datetime.now(UTC).isoformat()}
    if req.name is not None:
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="Give the project a name.")
        updates["name"] = req.name.strip()
    if req.description is not None:
        description = " ".join(req.description.split())
        # Only a changed description costs an embedding. If Voyage is down the
        # old vector goes too rather than stand for words it wasn't made from;
        # the papers take over once there are three.
        if description != found[0]["description"]:
            updates["description"] = description
            updates["description_embedding"] = _embed(user_id, description)
    if req.visibility is not None:
        updates["visibility"] = req.visibility
    if req.suggest_level is not None:
        updates["suggest_level"] = req.suggest_level

    if not uc.table("projects").update(updates).eq("id", str(project_id)).execute().data:
        raise HTTPException(status_code=403, detail="Only the project's owner can change it.")
    rows = uc.table("projects").select(_COLUMNS).eq("id", str(project_id)).execute().data
    return ProjectOut(**rows[0])
