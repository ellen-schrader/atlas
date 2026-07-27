"""Cold-tier persistence for map layouts (the `map_layouts` table).

The 2-D t-SNE coordinates + KMeans assignment are deterministic for a given
embedded-paper set, so they are stored once per `(team_id, signature)` — the
same signature that keys the cluster names in `trends` — and simply superseded
when the set changes. Serving reads from here (via the in-process hot cache);
only the layout job (api/layout_job.py) writes.

Both directions degrade to "not persisted" if the `map_layouts` migration
hasn't been applied on the target DB, mirroring overview._load_names.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from .supa import service_client

log = logging.getLogger(__name__)

# Rows for superseded signatures are cheap (~30 KB each) but pointless to keep
# forever; anything this old is either superseded or so rarely viewed that one
# recompute on the next view is fine.
_GC_DAYS = 60


def load_layout(team_id: str, signature: str) -> dict[str, dict] | None:
    """The stored layout for this signature as ``{paper_id: {x, y, cluster}}``,
    or None when it hasn't been computed (or the table doesn't exist yet)."""
    try:
        rows = (
            service_client()
            .table("map_layouts")
            .select("coords")
            .eq("team_id", team_id)
            .eq("signature", signature)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        log.warning("map_layouts read failed (layout not persisted): %s", exc)
        return None
    if not rows:
        return None
    coords = rows[0]["coords"] or {}
    return {
        pid: {"x": float(x), "y": float(y), "cluster": int(c)}
        for pid, (x, y, c) in coords.items()
    }


def delete_layout(team_id: str, signature: str) -> None:
    """Drop one stored layout (used when a row fails the serving-side sanity
    check) so the recompute's upsert starts from a clean slate."""
    try:
        service_client().table("map_layouts").delete().eq("team_id", team_id).eq(
            "signature", signature
        ).execute()
    except Exception as exc:
        log.warning("map_layouts delete failed: %s", exc)


def store_layout(team_id: str, signature: str, point_by_id: dict[str, dict]) -> bool:
    """Upsert this signature's layout and GC the team's ancient rows.

    Returns False when the upsert failed (e.g. the migration isn't applied) so
    the layout job can exit non-zero — the failure then shows up in its exit
    code and log instead of masquerading as a successful run that stored
    nothing. A failed GC is only logged; the layout itself landed.
    """
    coords = {
        pid: [p["x"], p["y"], p["cluster"]] for pid, p in point_by_id.items()
    }
    try:
        svc = service_client()
        svc.table("map_layouts").upsert(
            {"team_id": team_id, "signature": signature, "coords": coords},
            on_conflict="team_id,signature",
        ).execute()
    except Exception as exc:
        log.warning("map_layouts write failed (layout not persisted): %s", exc)
        return False
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=_GC_DAYS)).isoformat()
        svc.table("map_layouts").delete().eq("team_id", team_id).lt(
            "created_at", cutoff
        ).execute()
    except Exception as exc:
        log.warning("map_layouts GC failed (stale rows kept): %s", exc)
    return True
