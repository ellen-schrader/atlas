"""Mood-board data layer for the Atlas MCP server.

Reads the lab's ``figures`` as the signed-in user (RLS scopes to their lab),
downloads image bytes from the private ``figures`` Storage bucket, and derives
palettes. See docs/MOODBOARD_MCP_PLAN.md.
"""

from __future__ import annotations

import io
import uuid

from . import lab
from .lab import LabError
from .spec import DEFAULT_PALETTE, spec_seed

BUCKET = "figures"

# Explicit columns + the uploader profile and linked paper (for provenance).
# Deliberately WITHOUT `spec`: no list/tool consumer reads it, and it would drag
# a full JSON document per row into every board listing (and model context).
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


@lab.with_refresh
def add_style_card(
    team: dict,
    *,
    spec: dict,
    title: str,
    category: str = "",
    tags: list[str] | None = None,
    source_url: str | None = None,
    attribution: str | None = None,
    paper_id: str | None = None,
) -> dict:
    """Create a style card: render the (validated) spec with synthetic data,
    store the render in the figures bucket, insert the row (origin='style_card').

    The render is seeded from the spec's content (spec_seed) — the same seed
    preview_plot_spec uses — so the board shows exactly the image the user
    approved, and the stored row (which carries the spec) can always reproduce
    it. Mirrors the web upload's orphan handling: if the row insert fails, the
    just-uploaded object is best-effort removed.
    """
    from . import render as figrender

    uid = lab.current_user_id()
    if not uid:
        raise LabError("Couldn't determine your user id to attribute the style card to.")
    figure_id = str(uuid.uuid4())
    try:
        png, width, height = figrender.render(spec, spec_seed(spec))
    except Exception as exc:  # noqa: BLE001 — surface renderer failures cleanly
        raise LabError(f"Could not render the spec: {exc}") from exc

    path = f"{team['id']}/{figure_id}.png"
    client = lab.get_client()
    try:
        client.storage.from_(BUCKET).upload(path, png, {"content-type": "image/png"})
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not store the rendered preview: {exc}") from exc

    row = {
        "id": figure_id,
        "team_id": team["id"],
        "uploaded_by": uid,
        "storage_path": path,
        "title": title,
        "caption": "",
        "category": category,
        "tags": tags or [],
        "width": width,
        "height": height,
        "mime_type": "image/png",
        "file_size": len(png),
        "origin": "style_card",
        "spec": spec,
        "source_url": source_url,
        "attribution": attribution,
        "paper_id": paper_id,
    }
    try:
        rows = client.table("figures").insert(row).execute().data or []
    except Exception as exc:  # noqa: BLE001
        try:
            client.storage.from_(BUCKET).remove([path])
        except Exception:  # noqa: BLE001 — cleanup is best-effort
            pass
        raise LabError(f"Could not save the style card: {exc}") from exc
    return rows[0] if rows else row


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


# --- colour-vision-deficiency (CVD) safety -------------------------------------
# A CVD-safe qualitative default (Paul Tol 'bright') to recommend when a palette
# collides. Distinguishable under all three dichromacies by construction. Single
# source of truth is spec.DEFAULT_PALETTE, which style cards also fall back to.
SAFE_CYCLE = list(DEFAULT_PALETTE)

# Machado et al. (2009) dichromacy simulation matrices, severity 1.0, applied in
# LINEAR RGB. Rows are the R/G/B outputs; columns the R/G/B inputs.
_CVD_MATRICES = {
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}
# CIE76 ΔE below which two colours read as "the same" — the JND for flat swatches
# sits around 2.3, but plotted lines/markers need more headroom to tell apart.
_CVD_MIN_DE = 11.0


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> int:
    c = 0.0 if c < 0 else (1.0 if c > 1 else c)
    s = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return round(255 * s)


def _simulate_cvd(rgb: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    """How ``rgb`` (0–255) appears under a given dichromacy."""
    r, g, b = (_srgb_to_linear(x) for x in rgb)
    m = _CVD_MATRICES[kind]
    return (
        _linear_to_srgb(m[0][0] * r + m[0][1] * g + m[0][2] * b),
        _linear_to_srgb(m[1][0] * r + m[1][1] * g + m[1][2] * b),
        _linear_to_srgb(m[2][0] * r + m[2][1] * g + m[2][2] * b),
    )


def _rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """CIELAB (D65) for a 0–255 sRGB triple — for perceptual ΔE distances."""
    r, g, b = (_srgb_to_linear(x) for x in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def normalize_hexes(raw) -> list[str]:
    """Parse a hex palette from a list or a comma/space-separated string; keep only
    well-formed 6-digit colours, normalised to ``#rrggbb`` lower-case, de-duped."""
    import re

    if isinstance(raw, str):
        tokens = re.split(r"[,\s]+", raw.strip())
    else:
        tokens = list(raw or [])
    out: list[str] = []
    for t in tokens:
        t = str(t).strip().lstrip("#").lower()
        if re.fullmatch(r"[0-9a-f]{6}", t) and f"#{t}" not in out:
            out.append(f"#{t}")
    return out


def cvd_report(hexes: list[str], min_de: float = _CVD_MIN_DE) -> dict:
    """For each dichromacy, the colour pairs that collide (ΔE < ``min_de``) once the
    palette is seen through that deficiency. ``{kind: {"safe": bool, "pairs": [...]}}``."""
    report: dict[str, dict] = {}
    for kind in _CVD_MATRICES:
        seen = [(_rgb_to_lab(_simulate_cvd(_hex_to_rgb(h), kind)), h) for h in hexes]
        pairs = []
        for i in range(len(seen)):
            for j in range(i + 1, len(seen)):
                de = _delta_e(seen[i][0], seen[j][0])
                if de < min_de:
                    pairs.append((seen[i][1], seen[j][1], round(de, 1)))
        report[kind] = {"safe": not pairs, "pairs": pairs}
    return report


def mplstyle(hexes: list[str], lab_name: str) -> str:
    """A matplotlib style sheet (``.mplstyle`` text) derived from a palette.

    The palette drives the data colour cycle (the part that reads as "the lab's
    look"); axis/text ink stays neutral. When the mood board is monochrome we ship
    a CVD-safe scientific default cycle rather than an all-white one."""
    fallback = not hexes
    cycle = [h.lstrip("#") for h in (hexes or SAFE_CYCLE)]
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
