"""Mood-board data layer for the Atlas MCP server.

Reads the lab's ``figures`` as the signed-in user (RLS scopes to their lab),
downloads image bytes from the private ``figures`` Storage bucket, and derives
palettes. See docs/MOODBOARD_MCP_PLAN.md.
"""

from __future__ import annotations

import io

from . import lab
from .lab import LabError

BUCKET = "figures"

# Explicit columns + the uploader profile and linked paper (for provenance).
FIGURE_COLUMNS = (
    "id, team_id, uploaded_by, storage_path, title, caption, category, paper_id, tags, "
    "width, height, mime_type, origin, source_url, license, attribution, created_at, "
    "uploader:profiles!figures_uploaded_by_fkey(display_name), papers(id, title, doi)"
)


def list_figures(
    team: dict,
    *,
    category: str | None = None,
    tag: str | None = None,
    origin: str | None = None,
    mine_only: bool = False,
    limit: int = 20,
) -> list[dict]:
    """The lab's figures, newest first, with optional filters."""
    client = lab.get_client()
    q = (
        client.table("figures")
        .select(FIGURE_COLUMNS)
        .eq("team_id", team["id"])
        .order("created_at", desc=True)
        .limit(limit)
    )
    if category:
        q = q.eq("category", category)
    if origin:
        q = q.eq("origin", origin)
    if tag:
        q = q.contains("tags", [tag])
    if mine_only:
        uid = lab.current_user_id()
        if uid:
            q = q.eq("uploaded_by", uid)
    return q.execute().data or []


def get_figure(team: dict, figure_id: str) -> dict:
    """One figure in the lab, hydrated with uploader + linked paper."""
    client = lab.get_client()
    rows = (
        client.table("figures")
        .select(FIGURE_COLUMNS)
        .eq("team_id", team["id"])
        .eq("id", figure_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise LabError(f"No figure {figure_id} in {team['name']}.")
    return rows[0]


def categories(team: dict) -> list[dict]:
    """The lab's category facets (figure_categories RPC)."""
    client = lab.get_client()
    return client.rpc("figure_categories", {"p_team": team["id"]}).execute().data or []


def download(figure: dict) -> bytes:
    """Raw image bytes from the private bucket (storage RLS applies)."""
    client = lab.get_client()
    try:
        return client.storage.from_(BUCKET).download(figure["storage_path"])
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not fetch the image for figure {figure['id']}: {exc}") from exc


def downscale_png(raw: bytes, max_side: int = 900) -> tuple[bytes, int, int]:
    """Downscale to <= ``max_side`` on the long edge; return (png_bytes, w, h)."""
    from PIL import Image  # lazy: importing Pillow is not free

    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))))
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue(), im.width, im.height


def palette(raw: bytes, n: int = 6) -> list[str]:
    """Dominant colours as hex, most-common first (deterministic)."""
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as im:
        im = im.convert("RGB")
        im.thumbnail((200, 200))  # palette is stable at low res and much faster
        quant = im.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
        pal = quant.getpalette() or []
        by_count = sorted(quant.getcolors() or [], reverse=True)  # [(count, index), ...]
        hexes = []
        for _, idx in by_count[:n]:
            r, g, b = pal[idx * 3 : idx * 3 + 3]
            hexes.append(f"#{r:02x}{g:02x}{b:02x}")
        return hexes
