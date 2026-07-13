"""Style-card spec (v1) — validation and normalisation.

A style card stores a figure's *style* as data — chart form, palette, line
styles, axes, legend, typography — plus gestalt-level ``data_hints``. The board
image is a synthetic render of the spec (``atlas_mcp/render.py``); the admired
original is never persisted. See docs/STYLE_CARDS_PLAN.md.

Validation is hand-rolled and closed-vocabulary: every field maps onto a
matplotlib rcParam or draw call, so a valid spec cannot carry code, file paths,
real data values, or free drawing. Unknown keys are rejected — the schema grows
by version, not by loosening. Error messages name the allowed values so the
calling model can self-correct.

This module is deliberately import-light (stdlib only), so spec validation is
testable without supabase/mcp/matplotlib installed.
"""

from __future__ import annotations

import hashlib
import json
import re

SPEC_VERSION = 1

CHART_TYPES = ("line", "scatter", "bar", "histogram", "heatmap", "box")
SCALES = ("linear", "log")
GRIDS = ("none", "x", "y", "both")
SPINES = ("open", "box")
DASHES = ("solid", "dashed", "dotted", "dashdot")
MARKERS = ("none", "circle", "square", "triangle", "diamond", "plus", "x")
# How a line connects its points. "step" is what makes a Kaplan-Meier curve or an
# empirical CDF read as itself — a smooth line through the same points doesn't.
DRAWSTYLES = ("linear", "step")
LEGEND_MODES = ("direct", "box", "none")
LEGEND_LOCS = (
    "best",
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "center left",
    "center right",
    "lower center",
    "upper center",
    "center",
)
TRENDS = ("rising", "falling", "saturating", "peaked", "flat", "mixed")
NOISES = ("none", "low", "medium", "high")
WEIGHTS = ("normal", "bold")

MAX_SERIES = 8
MAX_POINTS = 500
MAX_NOTES = 500
# The render is DPI-scaled (render.DPI), so aspect is a pixel budget, not just a
# shape: 12x12in at 300dpi is a 12.9 MP figure — ~50 MB of Agg buffer, a PNG the
# figures bucket (10 MB limit) would reject, and every byte of it thrown away by
# consumers that show it at ~300-768px. Bound the area, not only the sides.
MAX_AREA_SQIN = 40.0

# Paul Tol 'bright' — a CVD-safe default when a spec names no palette. Matches
# moodboard.SAFE_CYCLE; duplicated so this module stays dependency-free.
DEFAULT_PALETTE = ("#4477aa", "#ee6677", "#228833", "#ccbb44", "#66ccee", "#aa3377")

_HEX = re.compile(r"[0-9a-f]{6}")

# How many synthetic points feel natural per chart form, absent a hint.
_DEFAULT_POINTS = {
    "line": 40,
    "scatter": 120,
    "bar": 5,
    "histogram": 200,
    "heatmap": 400,
    "box": 80,
}

# The defaults, in ONE place. validate_spec fills them on the write path and
# hydrate() fills them on the read path — a second copy in the renderer would
# drift the moment either side gains a field.
SERIES_DEFAULTS = {"line_width": 1.8, "dash": "solid", "marker": "none", "drawstyle": "linear"}
SECTION_DEFAULTS = {
    "chart": {"aspect": [5.0, 3.4]},
    "axes": {"x_scale": "linear", "y_scale": "linear", "grid": "y", "spines": "open"},
    "legend": {"mode": "direct"},
    "typography": {"base_size": 11.0, "title_weight": "bold"},
    "data_hints": {"n_series": 2, "trend": "rising", "noise": "low"},
}

_TOP_KEYS = (
    "spec_version",
    "chart",
    "axes",
    "palette",
    "series",
    "legend",
    "typography",
    "data_hints",
    "notes",
    "cvd",
)


class SpecError(ValueError):
    """A spec that doesn't validate; the message says how to fix it."""


def _section(value: object, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SpecError(f"{where} must be a JSON object.")
    return value


def _reject_unknown(d: dict, where: str, allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(d) - set(allowed))
    if unknown:
        raise SpecError(
            f"{where} has unsupported key(s): {', '.join(unknown)} — allowed: {', '.join(allowed)}."
        )


def _enum(d: dict, where: str, key: str, allowed: tuple[str, ...], default: str) -> str:
    v = d.get(key, default)
    if not isinstance(v, str) or v not in allowed:
        raise SpecError(f"{where}.{key} must be one of: {', '.join(allowed)}.")
    return v


def _number(d: dict, where: str, key: str, lo: float, hi: float, default: float) -> float:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise SpecError(f"{where}.{key} must be a number between {lo} and {hi}.")
    if not lo <= v <= hi:
        raise SpecError(f"{where}.{key} must be between {lo} and {hi} (got {v}).")
    return float(v)


def _integer(d: dict, where: str, key: str, lo: int, hi: int, default: int) -> int:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise SpecError(f"{where}.{key} must be an integer between {lo} and {hi}.")
    if not lo <= v <= hi:
        raise SpecError(f"{where}.{key} must be between {lo} and {hi} (got {v}).")
    return v


def _chart(raw: object) -> dict:
    d = _section(raw, "chart")
    if "type" not in d:
        raise SpecError(f"chart.type is required — one of: {', '.join(CHART_TYPES)}.")
    _reject_unknown(d, "chart", ("type", "aspect"))
    ctype = _enum(d, "chart", "type", CHART_TYPES, "line")
    aspect = d.get("aspect", SECTION_DEFAULTS["chart"]["aspect"])
    if (
        not isinstance(aspect, list | tuple)
        or len(aspect) != 2
        or any(isinstance(v, bool) or not isinstance(v, int | float) for v in aspect)
    ):
        raise SpecError("chart.aspect must be [width, height] in inches, e.g. [5, 3.4].")
    w, h = float(aspect[0]), float(aspect[1])
    if not (1.0 <= w <= 12.0 and 1.0 <= h <= 12.0):
        raise SpecError("chart.aspect sides must be between 1 and 12 inches.")
    if not 0.3 <= w / h <= 4.0:
        raise SpecError("chart.aspect ratio (width/height) must be between 0.3 and 4.")
    if w * h > MAX_AREA_SQIN:
        raise SpecError(
            f"chart.aspect is too large ({w}x{h}in = {w * h:.0f} sq in; max {MAX_AREA_SQIN:.0f}). "
            "A figure card is read at thumbnail size — keep it near [5, 3.4]."
        )
    return {"type": ctype, "aspect": [w, h]}


def _axes(raw: object) -> dict:
    d = _section(raw, "axes")
    _reject_unknown(d, "axes", ("x_scale", "y_scale", "grid", "spines"))
    dflt = SECTION_DEFAULTS["axes"]
    return {
        "x_scale": _enum(d, "axes", "x_scale", SCALES, dflt["x_scale"]),
        "y_scale": _enum(d, "axes", "y_scale", SCALES, dflt["y_scale"]),
        "grid": _enum(d, "axes", "grid", GRIDS, dflt["grid"]),
        "spines": _enum(d, "axes", "spines", SPINES, dflt["spines"]),
    }


def normalize_hex(raw: object) -> str | None:
    """One colour as canonical ``#rrggbb``, or None if it isn't a 6-digit hex.
    The single hex parser — ``moodboard.normalize_hexes`` builds on this."""
    s = str(raw).strip().lower()
    s = s[1:] if s.startswith("#") else s  # exactly one leading '#', not lstrip
    return f"#{s}" if _HEX.fullmatch(s) else None


def _palette(raw: object, strict: bool = True) -> list[str]:
    if raw is None:
        return list(DEFAULT_PALETTE)
    if not isinstance(raw, list) or not raw:
        raise SpecError('palette must be a non-empty list of hex colours like "#0f8f8b".')
    if len(raw) > MAX_SERIES:
        raise SpecError(f"palette can hold at most {MAX_SERIES} colours.")
    out: list[str] = []
    for c in raw:
        hexv = normalize_hex(c)
        if hexv is None:
            raise SpecError(f"palette colour {c!r} is not a 6-digit hex colour like #0f8f8b.")
        if hexv in out:
            # Two spellings of one colour ("#4477AA", "#4477aa") would otherwise
            # satisfy the colour-per-series rule below while the renderer drew
            # both series in the same ink — the exact thing that rule prevents.
            if strict:
                raise SpecError(f"palette repeats the colour {hexv} — each series needs its own.")
            continue  # on read: an older card stored before this rule still renders
        out.append(hexv)
    return out


def _series(raw: object, chart_type: str, n_default: int, strict: bool = True) -> list[dict]:
    default_marker = "circle" if chart_type == "scatter" else SERIES_DEFAULTS["marker"]
    if raw is None:
        raw = [{} for _ in range(n_default)]
    if not isinstance(raw, list) or not raw:
        raise SpecError("series must be a non-empty list of per-series style objects.")
    if len(raw) > MAX_SERIES:
        raise SpecError(f"series can hold at most {MAX_SERIES} entries.")
    out = []
    for i, s in enumerate(raw):
        d = _section(s, f"series[{i}]")
        _reject_unknown(d, f"series[{i}]", ("line_width", "dash", "marker", "drawstyle"))
        sd = SERIES_DEFAULTS
        entry = {
            "line_width": _number(d, f"series[{i}]", "line_width", 0.25, 6.0, sd["line_width"]),
            "dash": _enum(d, f"series[{i}]", "dash", DASHES, sd["dash"]),
            "marker": _enum(d, f"series[{i}]", "marker", MARKERS, default_marker),
        }
        drawstyle = _enum(d, f"series[{i}]", "drawstyle", DRAWSTYLES, sd["drawstyle"])
        if strict and drawstyle != "linear" and chart_type != "line":
            raise SpecError('series[].drawstyle only applies to a "line" chart.')
        entry["drawstyle"] = drawstyle
        out.append(entry)
    return out


def _legend(raw: object, strict: bool = True) -> dict:
    d = _section(raw, "legend")
    if strict:
        _reject_unknown(d, "legend", ("mode", "loc"))
    mode = _enum(d, "legend", "mode", LEGEND_MODES, SECTION_DEFAULTS["legend"]["mode"])
    if strict and mode != "box" and "loc" in d:
        raise SpecError('legend.loc only applies when legend.mode is "box".')
    out = {"mode": mode}
    if mode == "box":
        out["loc"] = _enum(d, "legend", "loc", LEGEND_LOCS, "best")
    return out


def _typography(raw: object) -> dict:
    d = _section(raw, "typography")
    _reject_unknown(d, "typography", ("base_size", "title_weight"))
    dflt = SECTION_DEFAULTS["typography"]
    return {
        "base_size": _number(d, "typography", "base_size", 6.0, 20.0, dflt["base_size"]),
        "title_weight": _enum(d, "typography", "title_weight", WEIGHTS, dflt["title_weight"]),
    }


def _notes(raw: dict) -> str:
    v = raw.get("notes")
    if v is None:
        return ""
    if not isinstance(v, str):
        raise SpecError("notes must be a string.")
    v = v.strip()
    if len(v) > MAX_NOTES:
        raise SpecError(f"notes is limited to {MAX_NOTES} characters.")
    return v


def validate_spec(raw: object, *, strict: bool = True) -> dict:
    """Validate a style-card spec and return it normalised (defaults filled,
    hex colours canonical, ``data_hints.n_series`` reconciled with ``series``).

    ``strict=True`` (writes) enforces everything. ``strict=False`` (reads, via
    :func:`for_render`) still enforces every TYPE and BOUND — the limits that
    keep a spec from being able to do harm — but relaxes the cosmetic
    cross-field rules and tolerates unknown keys, so a card stored before a rule
    existed keeps rendering. Lenient means *additive*, never *unchecked*.

    Raises :class:`SpecError` with a fix-it message on anything invalid. Any
    ``cvd`` block on input is discarded — the server stamps its own at save time.
    """
    if not isinstance(raw, dict):
        raise SpecError("The spec must be a JSON object — see the style-card spec (v1).")
    if strict:
        _reject_unknown(raw, "spec", _TOP_KEYS)
        version = raw.get("spec_version", SPEC_VERSION)
        # `True == 1` and `1.0 == 1` in Python — a bare != would let both through,
        # and route them to the wrong parser the moment a v2 exists.
        if isinstance(version, bool) or not isinstance(version, int) or version != SPEC_VERSION:
            raise SpecError(f"spec_version must be {SPEC_VERSION} (got {version!r}).")

    chart = _chart(raw.get("chart"))
    axes = _axes(raw.get("axes"))
    if (
        strict
        and chart["type"] not in ("line", "scatter")
        and "log" in (axes["x_scale"], axes["y_scale"])
    ):
        # Bars/bins/boxes sit on a zero baseline (and bar groups on ordinal
        # positions including 0) — a log axis masks or garbles them.
        raise SpecError("log axes are only supported for line and scatter charts.")
    palette = _palette(raw.get("palette"), strict)

    hints_d = _section(raw.get("data_hints"), "data_hints")
    if strict:
        _reject_unknown(hints_d, "data_hints", ("n_series", "n_points", "trend", "noise"))
    hd = SECTION_DEFAULTS["data_hints"]
    n_hint = _integer(hints_d, "data_hints", "n_series", 1, MAX_SERIES, hd["n_series"])
    series = _series(raw.get("series"), chart["type"], n_hint, strict)
    # A heatmap draws no series: its palette is a continuous colour RAMP (the
    # stops of a colormap), so "one colour per series" does not apply — demanding
    # it would make the single-hue sequential ramp the renderer supports
    # impossible to ask for.
    if strict and chart["type"] != "heatmap" and len(palette) < len(series):
        # The renderer cycles the palette, so a short one would reuse colours —
        # and the CVD verdict (checked on the palette alone) would overstate.
        if raw.get("palette") is None:
            raise SpecError(
                f"{len(series)} series needs {len(series)} colours, but the CVD-safe default "
                f"palette has only {len(DEFAULT_PALETTE)} — supply a palette with one colour "
                "per series."
            )
        raise SpecError(
            f"palette has {len(palette)} colour(s) for {len(series)} series — give every "
            "series its own colour (extend the palette or reduce the series)."
        )
    data_hints = {
        # series entries are authoritative; a diverging n_series hint is folded in.
        "n_series": len(series),
        "n_points": _integer(
            hints_d, "data_hints", "n_points", 3, MAX_POINTS, _DEFAULT_POINTS.get(chart["type"], 40)
        ),
        "trend": _enum(hints_d, "data_hints", "trend", TRENDS, hd["trend"]),
        "noise": _enum(hints_d, "data_hints", "noise", NOISES, hd["noise"]),
    }

    out = {
        "spec_version": SPEC_VERSION,
        "chart": chart,
        "axes": axes,
        "palette": palette,
        "series": series,
        "legend": _legend(raw.get("legend"), strict),
        "typography": _typography(raw.get("typography")),
        "data_hints": data_hints,
    }
    notes = _notes(raw)
    if notes:
        out["notes"] = notes
    return out


def hydrate(stored: dict) -> dict:
    """A stored spec with every field it predates filled from the current defaults.

    The DB is a *persistence* format: a card written before a field existed will
    never have that field (a card saved before ``drawstyle`` has no drawstyle).
    So reads are lenient — fill defaults — while :func:`validate_spec` keeps
    *writes* strict. Without this split, every addition to the vocabulary
    silently breaks the cards already on the board.

    Idempotent: hydrating an already-validated spec changes nothing.
    """
    chart = {**SECTION_DEFAULTS["chart"], **(stored.get("chart") or {})}
    ctype = chart.get("type", "line")
    marker = "circle" if ctype == "scatter" else SERIES_DEFAULTS["marker"]
    series = [
        {**SERIES_DEFAULTS, "marker": marker, **(s or {})}
        for s in (stored.get("series") or [{}, {}])
    ]
    return {
        **stored,
        "chart": chart,
        "axes": {**SECTION_DEFAULTS["axes"], **(stored.get("axes") or {})},
        "palette": stored.get("palette") or list(DEFAULT_PALETTE),
        "series": series,
        "legend": {**SECTION_DEFAULTS["legend"], **(stored.get("legend") or {})},
        "typography": {**SECTION_DEFAULTS["typography"], **(stored.get("typography") or {})},
        "data_hints": {
            **SECTION_DEFAULTS["data_hints"],
            "n_points": _DEFAULT_POINTS.get(ctype, 40),
            **(stored.get("data_hints") or {}),
        },
    }


def for_render(stored: dict) -> dict:
    """A spec ready to render: defaults filled, types and bounds enforced,
    cosmetic cross-field rules relaxed.

    This is what the renderer accepts. It is deliberately NOT bare ``hydrate``:
    ``figures_update`` RLS lets a row's owner PATCH ``spec`` to arbitrary JSON,
    so the read path has to re-check the bounds (aspect/area, series, points)
    that make "a valid spec cannot do harm" true — a stored ``aspect`` of
    [12000, 12000] would otherwise allocate until the process dies. Lenient
    means additive, never unchecked.
    """
    return validate_spec(hydrate(stored), strict=False)


def spec_seed(spec: dict) -> int:
    """A deterministic RNG seed from a spec's content (key order irrelevant).

    The server-stamped ``cvd`` block is excluded from the hash so the preview
    (rendered before stamping) and the stored card (rendered after) get the
    SAME seed — the user must see on the board exactly the synthetic data they
    approved in the preview, and a re-render from the stored row reproduces it.
    """
    blob = json.dumps(
        {k: v for k, v in spec.items() if k != "cvd"}, sort_keys=True, separators=(",", ":")
    )
    return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:8], "big")
