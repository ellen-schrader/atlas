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


@lab.with_refresh
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
        if not uid:
            raise LabError("Couldn't determine your user id to filter to your own figures.")
        q = q.eq("uploaded_by", uid)
    return q.execute().data or []


@lab.with_refresh
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


@lab.with_refresh
def categories(team: dict) -> list[dict]:
    """The lab's category facets (figure_categories RPC)."""
    client = lab.get_client()
    return client.rpc("figure_categories", {"p_team": team["id"]}).execute().data or []


@lab.with_refresh
def _download_raw(figure: dict) -> bytes:
    return lab.get_client().storage.from_(BUCKET).download(figure["storage_path"])


def download(figure: dict) -> bytes:
    """Raw image bytes from the private bucket (storage RLS applies)."""
    try:
        return _download_raw(figure)
    except LabError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not fetch the image for figure {figure['id']}: {exc}") from exc


def to_preview(raw: bytes, max_side: int = 768) -> tuple[bytes, str]:
    """Downscale to <= ``max_side`` on the long edge and encode as WebP.

    WebP stays small for both photos and line art, keeping the base64 payload —
    which lands in the model's context — modest. Returns (bytes, mime_type).
    """
    from PIL import Image  # lazy: importing Pillow is not free

    try:
        with Image.open(io.BytesIO(raw)) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, max_side / max(w, h))
            if scale < 1.0:
                im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))))
            out = io.BytesIO()
            im.save(out, format="WEBP", quality=80, method=6)
            return out.getvalue(), "image/webp"
    except Exception as exc:  # noqa: BLE001 — corrupt/unsupported bytes → clean error
        raise LabError(f"Could not read the image: {exc}") from exc


# A scientific figure is mostly white background + black/gray structural ink
# (axes, ticks, gridlines, text); the colours that define the lab's LOOK are the
# data series — often hairline lines or small markers, i.e. very few pixels. So a
# frequency-ranked palette returns white/black/gray and the real colours never
# surface. We instead keep only *chromatic* pixels (the data ink) and pick each
# cluster's most-saturated member, so thin coloured lines resolve to true hues.
# Thresholds are on PIL's 0–255 HSV channels.
_S_MIN = 90  # ~saturation 0.35 — excludes anti-aliased/washed edge pixels
_V_LO = 38  # ~value 0.15 — excludes near-black ink
_V_HI = 247  # ~value 0.97 — excludes near-white background
_HUE_SEP = 16  # min hue separation between returned colours (~0.06 of the wheel)
_MIN_CHROMATIC = 40  # a figure with fewer chromatic pixels is treated as monochrome


def _chromatic(raw: bytes, max_side: int = 300) -> tuple[list, list, list]:
    """The (rgb, saturation, hue) of a figure's data-ink pixels — background, ink,
    and gridlines removed. Returns three parallel lists; empty when the figure has
    essentially no colour."""
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not read the image: {exc}") from exc
    im.thumbnail((max_side, max_side))
    rgb = list(im.getdata())
    h, s, v = (list(ch.getdata()) for ch in im.convert("HSV").split())
    kr: list = []
    ks: list = []
    kh: list = []
    for i, sat in enumerate(s):
        if sat >= _S_MIN and _V_LO <= v[i] <= _V_HI:
            kr.append(rgb[i])
            ks.append(sat)
            kh.append(h[i])
    return kr, ks, kh


def _cluster(kr: list, ks: list, kh: list, n: int) -> list[str]:
    """Quantize chromatic pixels, pick each cluster's most-saturated colour, keep
    the n most-frequent with distinct hues. Empty in → empty out (monochrome)."""
    if not kr:
        return []
    from PIL import Image

    ncol = min(max(4, n * 4), 64)
    try:
        strip = Image.new("RGB", (len(kr), 1))
        strip.putdata(kr)
        quant = strip.quantize(colors=ncol, method=Image.Quantize.MEDIANCUT)
        idxs = list(quant.getdata())
    except Exception as exc:  # noqa: BLE001 — keep failures as clean LabErrors
        raise LabError(f"Could not derive a palette: {exc}") from exc

    # per cluster: [count, best_saturation, best_rgb, best_hue]
    agg: dict[int, list] = {}
    for pos, ci in enumerate(idxs):
        rec = agg.get(ci)
        if rec is None:
            agg[ci] = [1, ks[pos], kr[pos], kh[pos]]
        else:
            rec[0] += 1
            if ks[pos] > rec[1]:
                rec[1], rec[2], rec[3] = ks[pos], kr[pos], kh[pos]

    out: list[str] = []
    hues: list[int] = []
    for _count, _sat, rgb, hue in sorted(agg.values(), key=lambda r: -r[0]):
        if all(min(abs(hue - hh), 255 - abs(hue - hh)) > _HUE_SEP for hh in hues):
            out.append("#%02x%02x%02x" % rgb)
            hues.append(hue)
        if len(out) >= n:
            break
    return out


def palette(raw: bytes, n: int = 6) -> list[str]:
    """The figure's data-series colours as hex (most-used, distinct hues first).
    Empty for a genuinely monochrome figure."""
    kr, ks, kh = _chromatic(raw)
    return _cluster(kr, ks, kh, n)


def aggregate_palette(raws: list[bytes], n: int = 6) -> list[str]:
    """A palette across several figures. Pools each figure's chromatic pixels and
    clusters once; near-monochrome figures are skipped so a grayscale micrograph
    or a black-and-white plot can't wash out the lab's colours."""
    kr: list = []
    ks: list = []
    kh: list = []
    for raw in raws:
        try:
            fr, fs, fh = _chromatic(raw)
        except LabError:
            continue
        if len(fr) < _MIN_CHROMATIC:
            continue  # this figure is effectively monochrome — don't let it dilute
        kr += fr
        ks += fs
        kh += fh
    return _cluster(kr, ks, kh, n)


def mplstyle(hexes: list[str], lab_name: str) -> str:
    """A matplotlib style sheet (``.mplstyle`` text) derived from a palette.

    The palette drives the data colour cycle (the part that reads as "the lab's
    look"); axis/text ink stays neutral. When the mood board is monochrome we ship
    a CVD-safe scientific default cycle rather than an all-white one."""
    fallback = not hexes
    # Paul Tol 'bright' — a safe, colourful default when nothing could be derived.
    cycle = [h.lstrip("#") for h in hexes] or [
        "4477AA", "EE6677", "228833", "CCBB44", "66CCEE", "AA3377"
    ]
    ink = "222222"
    header = f"# Atlas mood-board style — {lab_name}"
    if fallback:
        header += "  (no distinct colours found on the mood board; using a default cycle)"
    lines = [
        header,
        "figure.facecolor: white",
        "axes.facecolor: white",
        f"axes.edgecolor: {ink}",
        f"axes.labelcolor: {ink}",
        f"text.color: {ink}",
        f"xtick.color: {ink}",
        f"ytick.color: {ink}",
        # Scientific line/marker defaults — thin lines, small markers, ticks out.
        "axes.linewidth: 0.8",
        "lines.linewidth: 1.4",
        "lines.markersize: 5",
        "patch.linewidth: 0.6",
        "xtick.direction: out",
        "ytick.direction: out",
        "axes.grid: True",
        "grid.color: DDDDDD",
        "grid.linewidth: 0.6",
        "axes.spines.top: False",
        "axes.spines.right: False",
        "axes.titlesize: 13",
        "axes.titleweight: bold",
        "font.size: 11",
        "figure.dpi: 150",
        "axes.prop_cycle: cycler('color', [" + ", ".join(f"'{c}'" for c in cycle) + "])",
    ]
    return "\n".join(lines)
