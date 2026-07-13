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
    aspect = d.get("aspect", [5.0, 3.4])
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
    return {"type": ctype, "aspect": [w, h]}


def _axes(raw: object) -> dict:
    d = _section(raw, "axes")
    _reject_unknown(d, "axes", ("x_scale", "y_scale", "grid", "spines"))
    return {
        "x_scale": _enum(d, "axes", "x_scale", SCALES, "linear"),
        "y_scale": _enum(d, "axes", "y_scale", SCALES, "linear"),
        "grid": _enum(d, "axes", "grid", GRIDS, "y"),
        "spines": _enum(d, "axes", "spines", SPINES, "open"),
    }


def _palette(raw: object) -> list[str]:
    if raw is None:
        return list(DEFAULT_PALETTE)
    if not isinstance(raw, list) or not raw:
        raise SpecError('palette must be a non-empty list of hex colours like "#0f8f8b".')
    if len(raw) > MAX_SERIES:
        raise SpecError(f"palette can hold at most {MAX_SERIES} colours.")
    out: list[str] = []
    for c in raw:
        s = str(c).strip().lstrip("#").lower()
        if not _HEX.fullmatch(s):
            raise SpecError(f"palette colour {c!r} is not a 6-digit hex colour like #0f8f8b.")
        out.append(f"#{s}")
    return out


def _series(raw: object, chart_type: str, n_default: int) -> list[dict]:
    default_marker = "circle" if chart_type == "scatter" else "none"
    if raw is None:
        raw = [{} for _ in range(n_default)]
    if not isinstance(raw, list) or not raw:
        raise SpecError("series must be a non-empty list of per-series style objects.")
    if len(raw) > MAX_SERIES:
        raise SpecError(f"series can hold at most {MAX_SERIES} entries.")
    out = []
    for i, s in enumerate(raw):
        d = _section(s, f"series[{i}]")
        _reject_unknown(d, f"series[{i}]", ("line_width", "dash", "marker"))
        out.append(
            {
                "line_width": _number(d, f"series[{i}]", "line_width", 0.25, 6.0, 1.8),
                "dash": _enum(d, f"series[{i}]", "dash", DASHES, "solid"),
                "marker": _enum(d, f"series[{i}]", "marker", MARKERS, default_marker),
            }
        )
    return out


def _legend(raw: object) -> dict:
    d = _section(raw, "legend")
    _reject_unknown(d, "legend", ("mode", "loc"))
    mode = _enum(d, "legend", "mode", LEGEND_MODES, "direct")
    if mode != "box" and "loc" in d:
        raise SpecError('legend.loc only applies when legend.mode is "box".')
    out = {"mode": mode}
    if mode == "box":
        out["loc"] = _enum(d, "legend", "loc", LEGEND_LOCS, "best")
    return out


def _typography(raw: object) -> dict:
    d = _section(raw, "typography")
    _reject_unknown(d, "typography", ("base_size", "title_weight"))
    return {
        "base_size": _number(d, "typography", "base_size", 6.0, 20.0, 11.0),
        "title_weight": _enum(d, "typography", "title_weight", WEIGHTS, "bold"),
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


def validate_spec(raw: object) -> dict:
    """Validate a style-card spec and return it normalised (defaults filled,
    hex colours canonical, ``data_hints.n_series`` reconciled with ``series``).

    Raises :class:`SpecError` with a fix-it message on anything invalid. Any
    ``cvd`` block on input is discarded — the server stamps its own at save time.
    """
    if not isinstance(raw, dict):
        raise SpecError("The spec must be a JSON object — see the style-card spec (v1).")
    _reject_unknown(raw, "spec", _TOP_KEYS)
    version = raw.get("spec_version", SPEC_VERSION)
    if version != SPEC_VERSION:
        raise SpecError(f"spec_version must be {SPEC_VERSION} (got {version!r}).")

    chart = _chart(raw.get("chart"))
    axes = _axes(raw.get("axes"))
    if chart["type"] not in ("line", "scatter") and "log" in (axes["x_scale"], axes["y_scale"]):
        # Bars/bins/boxes sit on a zero baseline (and bar groups on ordinal
        # positions including 0) — a log axis masks or garbles them.
        raise SpecError("log axes are only supported for line and scatter charts.")
    palette = _palette(raw.get("palette"))

    hints_d = _section(raw.get("data_hints"), "data_hints")
    _reject_unknown(hints_d, "data_hints", ("n_series", "n_points", "trend", "noise"))
    n_hint = _integer(hints_d, "data_hints", "n_series", 1, MAX_SERIES, 2)
    series = _series(raw.get("series"), chart["type"], n_hint)
    if len(palette) < len(series):
        # The renderer cycles the palette, so a short one would reuse colours —
        # and the CVD verdict (checked on the palette alone) would overstate.
        raise SpecError(
            f"palette has {len(palette)} colour(s) for {len(series)} series — give every "
            "series its own colour (extend the palette or reduce the series)."
        )
    data_hints = {
        # series entries are authoritative; a diverging n_series hint is folded in.
        "n_series": len(series),
        "n_points": _integer(
            hints_d, "data_hints", "n_points", 3, MAX_POINTS, _DEFAULT_POINTS[chart["type"]]
        ),
        "trend": _enum(hints_d, "data_hints", "trend", TRENDS, "rising"),
        "noise": _enum(hints_d, "data_hints", "noise", NOISES, "low"),
    }

    out = {
        "spec_version": SPEC_VERSION,
        "chart": chart,
        "axes": axes,
        "palette": palette,
        "series": series,
        "legend": _legend(raw.get("legend")),
        "typography": _typography(raw.get("typography")),
        "data_hints": data_hints,
    }
    notes = _notes(raw)
    if notes:
        out["notes"] = notes
    return out


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
