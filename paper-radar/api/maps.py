"""Topic-map endpoints (maps v2 — Milestone 0/1: create & list).

A map is a *subject the lab tracks*, whose membership is a live semantic query.
The seed phrase is embedded here because the Voyage key is server-side only; RLS
(see ``supabase/migrations/…_maps.sql``) scopes every read/write to the caller's
labs and enforces that only a map's creator edits or deletes it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import embeddings
from .deps import require_token
from .supa import get_user_id, user_client

log = logging.getLogger(__name__)

router = APIRouter(prefix="/maps", tags=["maps"])

# Columns returned to the client — deliberately excludes seed_embedding (a 1024-dim
# vector), config, and ai_summary, which the list/detail views don't need.
_COLUMNS = "id, team_id, created_by, name, seed, visibility, created_at, updated_at"


class MapCreate(BaseModel):
    team_id: str
    name: str = Field(min_length=1, max_length=120)
    seed: str = Field(min_length=1, max_length=400)
    visibility: str = "lab"


class MapOut(BaseModel):
    id: str
    team_id: str
    created_by: str
    name: str
    seed: str
    visibility: str
    created_at: str
    updated_at: str


def _out(row: dict) -> MapOut:
    return MapOut(**{k: row[k] for k in MapOut.model_fields})


def _require_user(token: str) -> str:
    uid = get_user_id(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return uid


@router.post("", response_model=MapOut)
def create_map(req: MapCreate, token: str = Depends(require_token)) -> MapOut:
    """Create a topic map in one of the caller's labs. RLS refuses a lab the caller
    isn't a member of; the seed phrase is embedded for live membership."""
    user_id = _require_user(token)
    name, seed = req.name.strip(), req.seed.strip()
    if not name or not seed:
        raise HTTPException(status_code=400, detail="name and seed must not be empty")
    if req.visibility not in ("lab", "private"):
        raise HTTPException(status_code=400, detail="visibility must be 'lab' or 'private'")

    try:
        seed_embedding = embeddings.embed_query(seed)
    except embeddings.EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=f"Embeddings unavailable: {exc}") from exc

    try:
        rows = (
            user_client(token)
            .table("maps")
            .insert(
                {
                    "team_id": req.team_id,
                    "created_by": user_id,
                    "name": name,
                    "seed": seed,
                    "seed_embedding": seed_embedding,
                    "visibility": req.visibility,
                }
            )
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001 — inspect, don't blanket-403
        # Only an RLS `with check` refusal means "not a member" (403). Anything
        # else (Supabase down, bad payload) is a real failure and must not be
        # disguised as a permission error.
        detail = f"{getattr(exc, 'code', '')} {getattr(exc, 'message', '')} {exc}".lower()
        if "row-level security" in detail or "42501" in detail or "permission denied" in detail:
            raise HTTPException(
                status_code=403, detail="You can only create maps in labs you belong to."
            ) from exc
        raise
    if not rows:
        raise HTTPException(
            status_code=403, detail="You can only create maps in labs you belong to."
        )
    return _out(rows[0])


class MapPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    seed: str | None = Field(default=None, max_length=400)
    visibility: str | None = None
    min_similarity: float | None = None
    pin: str | None = None  # paper_id to add to pinned (forces it into the map)
    unpin: str | None = None
    exclude: str | None = None  # paper_id to add to excluded (drops it from the map)
    uninclude: str | None = None


@router.patch("/{map_id}", response_model=MapOut)
def update_map(map_id: str, req: MapPatch, token: str = Depends(require_token)) -> MapOut:
    """Edit a map — rename, re-seed, change visibility, tune the match threshold, or
    pin/exclude a paper. Creator-only (enforced by RLS: a non-creator's update hits
    zero rows). Config is read-modify-written, which is safe because a map has a
    single editor (its creator), so there is no concurrent writer to race."""
    _require_user(token)
    uc = user_client(token)
    rows = uc.table("maps").select("config").eq("id", map_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")

    updates: dict = {}
    if req.name is not None:
        if not req.name.strip():
            raise HTTPException(status_code=400, detail="name must not be empty")
        updates["name"] = req.name.strip()
    if req.visibility is not None:
        if req.visibility not in ("lab", "private"):
            raise HTTPException(status_code=400, detail="visibility must be 'lab' or 'private'")
        updates["visibility"] = req.visibility
    if req.seed is not None:
        seed = req.seed.strip()
        if not seed:
            raise HTTPException(status_code=400, detail="seed must not be empty")
        try:
            updates["seed_embedding"] = embeddings.embed_query(seed)
        except embeddings.EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=f"Embeddings unavailable: {exc}") from exc
        updates["seed"] = seed

    config = dict(rows[0].get("config") or {})
    pinned = set(config.get("pinned") or [])
    excluded = set(config.get("excluded") or [])
    if req.min_similarity is not None:
        config["min_similarity"] = max(-1.0, min(1.0, req.min_similarity))
    if req.pin:
        pinned.add(req.pin)
        excluded.discard(req.pin)  # pinning a paper un-excludes it
    if req.unpin:
        pinned.discard(req.unpin)
    if req.exclude:
        excluded.add(req.exclude)
        pinned.discard(req.exclude)  # excluding a paper un-pins it
    if req.uninclude:
        excluded.discard(req.uninclude)
    config["pinned"] = sorted(pinned)
    config["excluded"] = sorted(excluded)
    updates["config"] = config
    updates["updated_at"] = datetime.now(UTC).isoformat()

    updated = uc.table("maps").update(updates).eq("id", map_id).execute().data or []
    if not updated:
        raise HTTPException(status_code=403, detail="Only the map's creator can edit it.")
    return _out(updated[0])


@router.get("", response_model=list[MapOut])
def list_maps(team_id: str, token: str = Depends(require_token)) -> list[MapOut]:
    """The caller's visible maps in a lab (RLS hides other members' private maps)."""
    _require_user(token)
    rows = (
        user_client(token)
        .table("maps")
        .select(_COLUMNS)
        .eq("team_id", team_id)
        .order("updated_at", desc=True)
        .execute()
        .data
        or []
    )
    return [_out(r) for r in rows]


@router.get("/{map_id}", response_model=MapOut)
def get_map(map_id: str, token: str = Depends(require_token)) -> MapOut:
    _require_user(token)
    rows = (
        user_client(token).table("maps").select(_COLUMNS).eq("id", map_id).limit(1).execute().data
        or []
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No such map, or it isn't visible to you.")
    return _out(rows[0])


@router.delete("/{map_id}")
def delete_map(map_id: str, token: str = Depends(require_token)) -> dict:
    """Delete a map. RLS allows only the map's creator, so a non-owner deletes zero
    rows and gets a 404 rather than silently succeeding."""
    _require_user(token)
    deleted = (
        user_client(token).table("maps").delete().eq("id", map_id).execute().data or []
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="No such map, or it isn't yours to delete.")
    return {"deleted": True}
