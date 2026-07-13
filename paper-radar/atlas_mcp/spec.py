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
MAX_SPEC_VERSION = 2  # v2 = composite figures (panels over a shared domain)

CHART_TYPES = ("line", "scatter", "bar", "histogram", "heatmap", "box")

# --- v2: composite figures ---------------------------------------------------
# A v1 spec describes ONE panel. The figures this lab publishes are usually
# composites — a heatmap of phenotype x marker, a percent-stacked composition
# bar, and an abundance count plot, all sharing one row axis where each row is a
# cell phenotype. What makes that a figure rather than three plots glued together
# is SHARED STRUCTURE: the rows must be the same rows, in the same order, and a
# category must keep its colour across panels. So v2 adds a named DOMAIN (the
# shared row axis), named PALETTES (semantic, referenced by name), a LAYOUT
# (GridSpec), and PANELS that bind to them.
PANEL_KINDS = (
    "line", "scatter", "bar", "histogram", "heatmap", "box",  # the v1 forms
    "stacked_bar",       # composition per row (grouped | stacked | percent)
    "annotation_track",  # the categorical colour strip beside a heatmap
    "dendrogram",        # the clustering tree that explains a row order
)
ROW_KINDS = ("heatmap", "stacked_bar", "bar", "annotation_track", "dendrogram")
ORDERS = ("fixed", "by_value", "clustered")
BAR_MODES = ("grouped", "stacked", "percent")
ORIENTATIONS = ("vertical", "horizontal")
SCALE_KINDS = ("sequential", "diverging")
COMPOSITIONS = ("even", "dominant_one", "long_tail")
DISTRIBUTIONS = ("uniform", "long_tail")
FIGURE_LEGENDS = ("figure", "panel", "none")
FIGURE_LEGEND_LOCS = ("right", "below")

MAX_PANELS = 6
MAX_GRID = 4          # rows/cols of the panel grid
MAX_CATEGORIES = 40   # rows in a shared domain
MAX_PALETTES = 6
MAX_LABEL_CHARS = 24
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
MAX_COLUMNS = 24  # heatmap columns (markers/conditions)
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


# --- v2 (composite) validation ----------------------------------------------


def _domains(raw: object, strict: bool) -> dict:
    """The named shared axes. A domain is the keystone of a composite: it names
    the rows once (``phenotype``) so every panel binds to the SAME categories in
    the SAME order — without it each panel would invent its own and the figure
    would be incoherent."""
    d = _section(raw, "domains")
    if not d:
        return {}
    if len(d) > 2:
        raise SpecError("domains: at most 2 shared axes.")
    out = {}
    for name, body in d.items():
        where = f"domains.{name}"
        b = _section(body, where)
        if strict:
            _reject_unknown(b, where, ("n_categories", "order", "labels"))
        entry = {
            "n_categories": _integer(b, where, "n_categories", 2, MAX_CATEGORIES, 10),
            "order": _enum(b, where, "order", ORDERS, "by_value"),
        }
        labels = b.get("labels")
        if labels is not None:
            # Real category names are OPT-IN and travel as data. For an `own`
            # (unpublished) figure the set and ordering of phenotypes can BE the
            # finding, so the default is synthetic labels; the confirm preview
            # shows any real ones so a human sees exactly what would be stored.
            if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
                raise SpecError(f"{where}.labels must be a list of strings.")
            if len(labels) != entry["n_categories"]:
                raise SpecError(
                    f"{where}.labels has {len(labels)} entries but n_categories is "
                    f"{entry['n_categories']} — they must match."
                )
            if any(len(x) > MAX_LABEL_CHARS for x in labels):
                raise SpecError(f"{where}.labels: each label is at most {MAX_LABEL_CHARS} chars.")
            entry["labels"] = [x.strip() for x in labels]
        out[name] = entry
    return out


def _palettes(raw: object, strict: bool) -> dict:
    """Named semantic palettes. A composite carries several colour MEANINGS at
    once (the heatmap ramp, the composition categories, an annotation strip), so
    panels reference a palette by name and a category keeps its colour across
    every panel and the legend — colour follows the entity, never the rank."""
    d = _section(raw, "palettes")
    if len(d) > MAX_PALETTES:
        raise SpecError(f"palettes: at most {MAX_PALETTES} named palettes.")
    return {name: _palette(body, strict) for name, body in d.items()}


def _layout(raw: object, n_panels: int, domains: dict, strict: bool) -> dict:
    d = _section(raw, "layout")
    if strict:
        _reject_unknown(
            d, "layout", ("rows", "cols", "width_ratios", "height_ratios", "gap", "share_y")
        )
    rows = _integer(d, "layout", "rows", 1, MAX_GRID, 1)
    cols = _integer(d, "layout", "cols", 1, MAX_GRID, max(1, n_panels))
    if rows * cols < n_panels:
        raise SpecError(f"layout {rows}x{cols} has no room for {n_panels} panels.")

    def _ratios(key: str, n: int) -> list[float]:
        v = d.get(key)
        if v is None:
            return [1.0] * n
        if not isinstance(v, list) or len(v) != n:
            raise SpecError(f"layout.{key} must be a list of {n} positive numbers.")
        out = []
        for x in v:
            if isinstance(x, bool) or not isinstance(x, int | float) or not 0.05 <= x <= 20:
                raise SpecError(f"layout.{key} values must be numbers between 0.05 and 20.")
            out.append(float(x))
        return out

    share = d.get("share_y")
    if share is not None:
        if not isinstance(share, str) or share not in domains:
            raise SpecError(
                f"layout.share_y must name a domain — one of: {', '.join(domains) or '(none)'}."
            )
    return {
        "rows": rows,
        "cols": cols,
        "width_ratios": _ratios("width_ratios", cols),
        "height_ratios": _ratios("height_ratios", rows),
        "gap": _number(d, "layout", "gap", 0.0, 0.5, 0.06),
        **({"share_y": share} if share else {}),
    }


_PANEL_KEYS = (
    "kind", "position", "rows", "palette", "columns", "mode", "orientation", "scale",
    "colorbar", "labels", "axes", "series", "legend", "data_hints", "title",
)


def _panel(raw: object, i: int, domains: dict, palettes: dict, grid: tuple, strict: bool) -> dict:
    where = f"panels[{i}]"
    d = _section(raw, where)
    if strict:
        _reject_unknown(d, where, _PANEL_KEYS)
    if "kind" not in d:
        raise SpecError(f"{where}.kind is required — one of: {', '.join(PANEL_KINDS)}.")
    kind = _enum(d, where, "kind", PANEL_KINDS, "line")

    pos = d.get("position", [0, i])
    if (
        not isinstance(pos, list | tuple)
        or len(pos) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) for v in pos)
    ):
        raise SpecError(f"{where}.position must be [row, col].")
    r, c = int(pos[0]), int(pos[1])
    if not (0 <= r < grid[0] and 0 <= c < grid[1]):
        raise SpecError(f"{where}.position {[r, c]} is outside the {grid[0]}x{grid[1]} layout.")

    panel = {"kind": kind, "position": [r, c]}

    rows = d.get("rows")
    if rows is not None:
        if not isinstance(rows, str) or rows not in domains:
            raise SpecError(
                f"{where}.rows must name a domain — one of: {', '.join(domains) or '(none)'}."
            )
        panel["rows"] = rows
    elif strict and kind in ROW_KINDS and domains:
        raise SpecError(
            f"{where}.rows: a {kind} panel in a composite must bind to a domain "
            f"(one of: {', '.join(domains)}) so its rows line up with the other panels."
        )

    # A panel's palette is either a NAME (shared, so a category keeps its colour
    # across panels) or an inline list.
    pal = d.get("palette")
    if isinstance(pal, str):
        if pal not in palettes:
            raise SpecError(
                f"{where}.palette names no palette — declare it under `palettes` "
                f"(have: {', '.join(palettes) or 'none'})."
            )
        panel["palette"] = pal
    elif pal is not None:
        panel["palette"] = _palette(pal, strict)

    if kind == "heatmap":
        panel["columns"] = _integer(d, where, "columns", 2, MAX_COLUMNS, 8)
        sc = _section(d.get("scale"), f"{where}.scale")
        if strict:
            _reject_unknown(sc, f"{where}.scale", ("kind", "midpoint"))
        panel["scale"] = {
            # A z-scored expression heatmap DIVERGES around zero; rendering it on
            # a single-hue sequential ramp gets the look materially wrong.
            "kind": _enum(sc, f"{where}.scale", "kind", SCALE_KINDS, "sequential"),
            "midpoint": _number(sc, f"{where}.scale", "midpoint", -10.0, 10.0, 0.0),
        }
        cb = _section(d.get("colorbar"), f"{where}.colorbar")
        if strict:
            _reject_unknown(cb, f"{where}.colorbar", ("show", "label"))
        show = cb.get("show", True)
        if not isinstance(show, bool):
            raise SpecError(f"{where}.colorbar.show must be true or false.")
        label = cb.get("label", "")
        if not isinstance(label, str) or len(label) > MAX_LABEL_CHARS:
            raise SpecError(f"{where}.colorbar.label must be a string ≤ {MAX_LABEL_CHARS} chars.")
        panel["colorbar"] = {"show": show, "label": label.strip()}

    if kind in ("bar", "stacked_bar"):
        panel["mode"] = _enum(
            d, where, "mode", BAR_MODES, "percent" if kind == "stacked_bar" else "grouped"
        )
    if kind in ("bar", "stacked_bar", "box", "histogram"):
        # A count plot on a ROW axis is horizontal — v1's bar renderer could only
        # draw vertical bars, which is why a composite needed this.
        panel["orientation"] = _enum(
            d, where, "orientation", ORIENTATIONS,
            "horizontal" if panel.get("rows") else "vertical",
        )

    lab_d = _section(d.get("labels"), f"{where}.labels")
    if strict:
        _reject_unknown(lab_d, f"{where}.labels", ("rows", "values"))
    for k in ("rows", "values"):
        if k in lab_d and not isinstance(lab_d[k], bool):
            raise SpecError(f"{where}.labels.{k} must be true or false.")
    # Row labels on the leftmost panel only is what makes a composite read as ONE
    # figure rather than three glued together — so it is a per-panel style fact.
    panel["labels"] = {
        "rows": bool(lab_d.get("rows", c == 0)),
        "values": bool(lab_d.get("values", True)),
    }

    panel["axes"] = _axes(d.get("axes"))
    if kind in ("line", "scatter", "bar", "histogram", "box"):
        hints_d = _section(d.get("data_hints"), f"{where}.data_hints")
        n_hint = _integer(hints_d, f"{where}.data_hints", "n_series", 1, MAX_SERIES, 1)
        panel["series"] = _series(d.get("series"), kind, n_hint, strict)
        panel["legend"] = _legend(d.get("legend"), strict)

    hints_d = _section(d.get("data_hints"), f"{where}.data_hints")
    if strict:
        _reject_unknown(
            hints_d, f"{where}.data_hints",
            ("n_series", "n_points", "trend", "noise", "composition", "distribution"),
        )
    hd = SECTION_DEFAULTS["data_hints"]
    hints = {
        "n_points": _integer(
            hints_d, f"{where}.data_hints", "n_points", 3, MAX_POINTS,
            _DEFAULT_POINTS.get(kind, 40),
        ),
        "trend": _enum(hints_d, f"{where}.data_hints", "trend", TRENDS, hd["trend"]),
        "noise": _enum(hints_d, f"{where}.data_hints", "noise", NOISES, hd["noise"]),
        # Shape only — a composition IS the finding in most of these papers, so
        # the spec may say "one category dominates", never the actual fractions.
        "composition": _enum(
            hints_d, f"{where}.data_hints", "composition", COMPOSITIONS, "dominant_one"
        ),
        "distribution": _enum(
            hints_d, f"{where}.data_hints", "distribution", DISTRIBUTIONS, "long_tail"
        ),
    }
    if "series" in panel:
        hints["n_series"] = len(panel["series"])
    panel["data_hints"] = hints

    title = d.get("title")
    if title is not None:
        if not isinstance(title, str) or len(title) > MAX_LABEL_CHARS:
            raise SpecError(f"{where}.title must be a string ≤ {MAX_LABEL_CHARS} chars.")
        panel["title"] = title.strip()
    return panel


_V2_TOP_KEYS = (
    "spec_version", "chart", "domains", "palettes", "layout", "panels",
    "typography", "legend", "notes", "cvd",
)


def _validate_v2(raw: dict, strict: bool) -> dict:
    if strict:
        _reject_unknown(raw, "spec", _V2_TOP_KEYS)

    chart_d = _section(raw.get("chart"), "chart")
    if strict:
        _reject_unknown(chart_d, "chart", ("type", "aspect"))
    aspect = _chart({"type": "line", **{k: v for k, v in chart_d.items() if k == "aspect"}})[
        "aspect"
    ]

    domains = _domains(raw.get("domains"), strict)
    palettes = _palettes(raw.get("palettes"), strict)

    panels_raw = raw.get("panels")
    if not isinstance(panels_raw, list) or not panels_raw:
        raise SpecError("panels must be a non-empty list — a composite is made of panels.")
    if len(panels_raw) > MAX_PANELS:
        raise SpecError(f"panels: at most {MAX_PANELS} per figure.")

    layout = _layout(raw.get("layout"), len(panels_raw), domains, strict)
    grid = (layout["rows"], layout["cols"])
    panels = [_panel(p, i, domains, palettes, grid, strict) for i, p in enumerate(panels_raw)]

    seen = set()
    for p in panels:
        pos = tuple(p["position"])
        if pos in seen:
            raise SpecError(f"two panels both sit at position {list(pos)}.")
        seen.add(pos)

    leg_d = _section(raw.get("legend"), "legend")
    if strict:
        _reject_unknown(leg_d, "legend", ("mode", "loc"))
    legend = {
        # In a composite the legend usually belongs to the FIGURE, not a panel.
        "mode": _enum(leg_d, "legend", "mode", FIGURE_LEGENDS, "figure"),
        "loc": _enum(leg_d, "legend", "loc", FIGURE_LEGEND_LOCS, "right"),
    }

    out = {
        "spec_version": 2,
        "chart": {"type": "composite", "aspect": aspect},
        "domains": domains,
        "palettes": palettes,
        "layout": layout,
        "panels": panels,
        "typography": _typography(raw.get("typography")),
        "legend": legend,
    }
    notes = _notes(raw)
    if notes:
        out["notes"] = notes
    return out


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
        raise SpecError("The spec must be a JSON object — see the style-card spec.")

    # Route on the version. `True == 1` and `1.0 == 1` in Python, so a bare
    # comparison would route a bool or a float to the wrong parser.
    version = raw.get("spec_version", 2 if "panels" in raw else SPEC_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise SpecError(f"spec_version must be 1 or {MAX_SPEC_VERSION} (got {version!r}).")
    if version not in (1, MAX_SPEC_VERSION):
        raise SpecError(f"spec_version must be 1 or {MAX_SPEC_VERSION} (got {version!r}).")
    if version == 2:
        return _validate_v2(raw, strict)

    if strict:
        _reject_unknown(raw, "spec", _TOP_KEYS)

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


def is_composite(spec: dict) -> bool:
    """Whether a spec is a v2 composite (panels over a shared domain)."""
    return spec.get("spec_version") == 2 or "panels" in spec


def hydrate(stored: dict) -> dict:
    """A stored spec with every field it predates filled from the current defaults.

    The DB is a *persistence* format: a card written before a field existed will
    never have that field (a card saved before ``drawstyle`` has no drawstyle).
    So reads are lenient — fill defaults — while :func:`validate_spec` keeps
    *writes* strict. Without this split, every addition to the vocabulary
    silently breaks the cards already on the board.

    Idempotent: hydrating an already-validated spec changes nothing.
    """
    if is_composite(stored):
        # A composite's defaults are per-panel; _validate_v2 fills them itself.
        return dict(stored)
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
