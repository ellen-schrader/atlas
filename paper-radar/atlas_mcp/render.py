"""Render a style-card spec to a PNG with synthetic data.

Deterministic for a GIVEN renderer: the same (spec, seed) yields the same bytes.
Both the preview tool and the stored card seed from ``spec.spec_seed``, so the
board image is exactly the render the user approved. Nothing of the admired
original enters the render — only the validated style parameters, and
rng-generated data shaped by the spec's ``data_hints``.

The determinism is scoped, and worth being precise about: it holds within one
version of this module and of matplotlib. It is what makes *preview == stored*
true (the promise the user actually relies on when they approve an image). It is
NOT a promise that a card rendered last year still reproduces bit-for-bit after
this module or matplotlib changes — figure layout and glyph rasterisation move
across versions. So the stored PNG, not a re-render, remains the card's image;
a re-render is a fresh render of the same style, not a checksum of the old one.

matplotlib is imported lazily inside :func:`render` — it is an ``mcp``-extra
dependency, and importing this module must stay cheap for environments that
only validate specs.
"""

from __future__ import annotations

import io
import os
import threading

import numpy as np

from . import spec as card_spec

# Headless before matplotlib is imported anywhere: reading rcParams["backend"]
# resolves the auto-sentinel by probing and importing GUI backends (macosx, qt,
# gtk, tk) — work this process must never do. Setting the env var skips it.
os.environ.setdefault("MPLBACKEND", "Agg")

DPI = 300  # crisp on the board and in downscaled tool previews

# pyplot's rcParams and figure registry are PROCESS-GLOBAL. FastMCP runs sync
# tools in a worker-thread pool, so two concurrent previews would interleave
# inside one rcParams and each render would come out wearing the other's palette
# and type — silently breaking the determinism the whole feature rests on.
# Renders are CPU-bound and short; serialise them.
_RENDER_LOCK = threading.Lock()

_DASH = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
_MARKER = {
    "none": None,
    "circle": "o",
    "square": "s",
    "triangle": "^",
    "diamond": "D",
    "plus": "P",
    "x": "X",
}
_NOISE = {"none": 0.0, "low": 0.02, "medium": 0.05, "high": 0.12}
# "step" holds each value until the next x — the staircase that makes a
# Kaplan-Meier curve or an empirical CDF legible as such.
_DRAWSTYLE = {"linear": "default", "step": "steps-post"}
_INK = "#222222"
# A composite's axes live per panel; these are the figure-wide fallbacks.
SECTION_DEFAULTS_AXES = card_spec.SECTION_DEFAULTS["axes"]


def _letter(i: int) -> str:
    """The i-th label letter (A, B, C, …) for series and group names — cycles
    rather than indexing a fixed tuple, so it can't fall behind spec.MAX_SERIES."""
    return chr(ord("A") + i % 26)


def _curve(trend: str, x: np.ndarray, i: int) -> np.ndarray:
    """A clean base curve in roughly [0.1, 0.9] for series ``i``. Series get a
    slightly different exponent/centre and a mild vertical offset so they stay
    visually separable without overlapping into mush."""
    if trend == "mixed":
        trend = ("rising", "falling", "saturating", "peaked")[i % 4]
    if trend == "rising":
        y = x ** (0.7 + 0.25 * i)
    elif trend == "falling":
        y = 1.0 - x ** (0.7 + 0.25 * i)
    elif trend == "saturating":
        h = 0.06 + 0.09 * i
        y = x / (x + h)
    elif trend == "peaked":
        c = 0.3 + 0.15 * (i % 3)
        y = np.exp(-((x - c) ** 2) / 0.02)
    else:  # flat
        y = np.full_like(x, 0.55)
    return 0.1 + 0.8 * y * (1.0 - 0.09 * i)


def _monotone_like(base: np.ndarray, noisy: np.ndarray) -> np.ndarray:
    """``noisy`` forced to follow ``base``'s monotone direction, if it has one.

    A base that only ever rises → running max; only ever falls → running min;
    anything else (a peak, a flat line) is returned untouched.
    """
    d = np.diff(base)
    if np.all(d >= 0) and np.any(d > 0):
        return np.maximum.accumulate(noisy)
    if np.all(d <= 0) and np.any(d < 0):
        return np.minimum.accumulate(noisy)
    return noisy


def _xs(spec: dict, n: int) -> np.ndarray:
    if spec["axes"]["x_scale"] == "log":
        return np.logspace(0.0, 2.0, n)
    return np.linspace(0.0, 10.0, n)


def _draw_line(fig, ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    n = hints["n_points"]
    x = _xs(spec, n)
    t = np.linspace(0.0, 1.0, n)
    sigma = _NOISE[hints["noise"]]
    for i, s in enumerate(spec["series"]):
        base = _curve(hints["trend"], t, i)
        y = np.clip(base + rng.normal(0.0, sigma, n), 0.02, None)  # log-y renderable
        if s["drawstyle"] == "step":
            # A survival/CDF staircase must not walk back against its own trend:
            # noise may dent the step heights, never reverse them. The direction
            # comes from THIS SERIES' base curve, not from the trend name —
            # `saturating` rises, and `mixed` resolves per series — so keying off
            # the name flattens a rising curve into a horizontal line. A
            # non-monotone base (peaked, flat) is left alone: forcing it monotone
            # would erase the very feature it has.
            y = _monotone_like(base, y)
        ax.plot(
            x,
            y,
            linestyle=_DASH[s["dash"]],
            linewidth=s["line_width"],
            marker=_MARKER[s["marker"]],
            markersize=4.0 + s["line_width"],
            drawstyle=_DRAWSTYLE[s["drawstyle"]],
            label=f"series {_letter(i)}",
        )
    ax.set_xlabel("x")
    ax.set_ylabel("signal")


def _draw_scatter(fig, ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    series = spec["series"]
    per = max(hints["n_points"] // len(series), 3)
    # Cluster spread follows `noise` (a spec that says "none" must look tighter
    # than one that says "high" — otherwise a model iterating on the preview can
    # never converge), and clusters are spread along a diagonal so they separate
    # instead of landing on top of each other.
    spread = 0.03 + 1.4 * _NOISE[hints["noise"]]
    n = len(series)
    for i, s in enumerate(series):
        step = (i + 0.5) / n
        jitter = rng.uniform(-0.06, 0.06, 2)
        cx = 0.2 + 0.6 * step + jitter[0]
        cy = 0.2 + 0.6 * (1.0 - step if hints["trend"] == "falling" else step) + jitter[1]
        ax.scatter(
            np.clip(rng.normal(cx, spread, per), 0.01, None),
            np.clip(rng.normal(cy, spread, per), 0.01, None),
            s=26.0,
            marker=_MARKER[s["marker"]] or "o",
            alpha=0.85,
            linewidths=0,
            label=f"cluster {_letter(i)}",
        )
    ax.set_xlabel("dim 1")
    ax.set_ylabel("dim 2")


def _draw_bar(fig, ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    series = spec["series"]
    k = int(min(max(hints["n_points"], 2), 12))  # n_points reads as "groups" here
    t = np.linspace(0.0, 1.0, k)
    width = 0.8 / len(series)
    sigma = _NOISE[hints["noise"]]
    for i in range(len(series)):
        vals = np.clip(_curve(hints["trend"], t, i) + rng.normal(0.0, sigma, k), 0.02, None)
        ax.bar(
            np.arange(k) + (i - (len(series) - 1) / 2) * width,
            vals,
            width=width * 0.9,
            label=f"series {_letter(i)}",
        )
    ax.set_xticks(np.arange(k))
    ax.set_xticklabels([_letter(j) for j in range(k)])
    ax.set_xlabel("group")
    ax.set_ylabel("value")


def _draw_histogram(fig, ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    series = spec["series"]
    n = hints["n_points"]
    many = len(series) > 1
    for i in range(len(series)):
        data = rng.normal(0.35 + 0.3 * i / max(len(series) - 1, 1), 0.09 + 0.02 * i, n)
        ax.hist(
            data,
            bins=min(max(n // 8, 8), 30),
            alpha=0.75 if many else 1.0,
            edgecolor="white",
            linewidth=0.4,
            label=f"series {_letter(i)}",
        )
    ax.set_xlabel("value")
    ax.set_ylabel("count")


def _draw_heatmap(fig, ax, spec: dict, rng) -> None:
    from matplotlib.colors import LinearSegmentedColormap

    side = int(np.clip(round(spec["data_hints"]["n_points"] ** 0.5), 8, 40))
    yy, xx = np.mgrid[0:side, 0:side] / max(side - 1, 1)
    field = np.zeros((side, side))
    for _ in range(4):  # a few smooth bumps read as "spatial signal"
        cx, cy = rng.uniform(0.15, 0.85, 2)
        field += rng.uniform(0.5, 1.0) * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / 0.04)
    pal = spec["palette"]
    stops = list(pal) if len(pal) >= 2 else ["#ffffff", pal[0]]
    im = ax.imshow(field, cmap=LinearSegmentedColormap.from_list("style_card", stops),
                   origin="lower")
    fig.colorbar(im, ax=ax, shrink=0.85)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)


def _draw_box(fig, ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    series = spec["series"]
    # One box per series — inventing extra groups would cycle the palette and
    # give two groups the same colour on a card stamped "colourblind-safe".
    groups = len(series)
    per = max(hints["n_points"] // groups, 5)
    centers = _curve(hints["trend"], np.linspace(0.0, 1.0, max(groups, 2)), 0)[:groups]
    data = [rng.normal(centers[g], 0.08 + _NOISE[hints["noise"]], per) for g in range(groups)]
    bp = ax.boxplot(
        data,
        patch_artist=True,
        widths=0.55,
        medianprops={"color": _INK, "linewidth": 1.2},
    )
    pal = spec["palette"]
    for g, box in enumerate(bp["boxes"]):
        box.set_facecolor(pal[g % len(pal)])
        box.set_alpha(0.85)
        box.set_linewidth(0.8)
    ax.set_xticklabels([_letter(g) for g in range(groups)])
    ax.set_xlabel("group")
    ax.set_ylabel("value")


def _rc(spec: dict) -> dict:
    """rcParams for the spec — white scientific ground, neutral ink, the spec's
    palette as the colour cycle. The font is matplotlib's bundled DejaVu Sans so
    output is identical across machines.

    A composite (v2) carries axes and palettes PER PANEL, so the figure-wide
    rcParams take the ink/type defaults and let each panel set its own.
    """
    from cycler import cycler

    typo = spec["typography"]
    if card_spec.is_composite(spec):
        axes_s = SECTION_DEFAULTS_AXES
        first = next(iter(spec.get("palettes", {}).values()), None)
        palette = first or list(card_spec.DEFAULT_PALETTE)
    else:
        axes_s = spec["axes"]
        palette = spec["palette"]
    open_spines = axes_s["spines"] == "open"
    rc = {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.edgecolor": _INK,
        "axes.labelcolor": _INK,
        "text.color": _INK,
        "xtick.color": _INK,
        "ytick.color": _INK,
        "axes.linewidth": 0.8,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "axes.spines.top": not open_spines,
        "axes.spines.right": not open_spines,
        "font.family": "DejaVu Sans",
        "font.size": typo["base_size"],
        "axes.titlesize": typo["base_size"] + 2,
        "axes.titleweight": typo["title_weight"],
        "axes.prop_cycle": cycler("color", list(palette)),
        "axes.grid": axes_s["grid"] != "none",
        "grid.color": "#dddddd",
        "grid.linewidth": 0.6,
        "legend.frameon": False,
    }
    if axes_s["grid"] in ("x", "y"):
        rc["axes.grid.axis"] = axes_s["grid"]
    return rc


def _apply_scales(ax, spec: dict) -> None:
    if spec["axes"]["x_scale"] == "log":
        ax.set_xscale("log")
    if spec["axes"]["y_scale"] == "log":
        ax.set_yscale("log")


def _finish_legend(ax, spec: dict, ctype: str) -> None:
    mode = spec["legend"]["mode"]
    # box charts label their groups on the x-axis; there are no series artists
    # to put in a legend.
    if mode == "none" or ctype == "box" or len(spec["series"]) < 2:
        return
    if mode == "direct" and ctype == "line":
        ax.margins(x=0.14)  # room for the end-of-line labels
        for line in ax.get_lines():
            x, y = line.get_xdata(), line.get_ydata()
            if len(x):
                ax.annotate(
                    f" {line.get_label()}",
                    (x[-1], y[-1]),
                    color=line.get_color(),
                    va="center",
                    fontsize=spec["typography"]["base_size"] - 1,
                )
        return
    # "direct" on a non-line chart falls back to a boxed legend — there is no
    # honest direct-label position for bars/bins/clusters at render time.
    ax.legend(loc=spec["legend"].get("loc", "best"))


# One entry per spec.CHART_TYPES member — a missing one is a KeyError at the
# first test, not a silently wrong card.
_DRAW = {
    "line": _draw_line,
    "scatter": _draw_scatter,
    "bar": _draw_bar,
    "histogram": _draw_histogram,
    "heatmap": _draw_heatmap,
    "box": _draw_box,
}

def render(raw_spec: dict, seed: int) -> tuple[bytes, int, int]:
    """Render a spec → ``(png_bytes, width_px, height_px)``.

    New specs come from ``spec.validate_spec``; specs read back from the DB are
    hydrated here, so a card stored before a field existed still renders (see
    ``spec.hydrate``). Hydration is idempotent, so a validated spec passes
    through unchanged — and with the same seed, byte-identical.
    """
    import matplotlib
    import matplotlib.pyplot as plt

    spec = card_spec.for_render(raw_spec)
    rng = np.random.default_rng(seed)
    w_in, h_in = spec["chart"]["aspect"]
    ctype = spec["chart"]["type"]
    composite = card_spec.is_composite(spec)
    buf = io.BytesIO()

    # Start from matplotlib's DEFAULTS, not the ambient rcParams: a developer's
    # ~/.config/matplotlib/matplotlibrc (a stray `savefig.bbox: tight` is enough
    # to change the output size, and with it the width/height we store) must not
    # be able to change what a lab's board looks like. `backend` is excluded —
    # we are already on Agg and switching it here would re-initialise it.
    base = {k: v for k, v in matplotlib.rcParamsDefault.items() if k != "backend"}
    with _RENDER_LOCK, plt.rc_context({**base, **_rc(spec)}):
        if composite:
            # `constrained`, not tight_layout: a composite has colorbar axes and a
            # figure-level legend, which tight_layout cannot lay out (it warns that
            # "results might be incorrect" — and they are).
            fig = plt.figure(figsize=(w_in, h_in), dpi=DPI, layout="constrained")
        else:
            fig, ax = plt.subplots(figsize=(w_in, h_in), dpi=DPI)
        try:
            if composite:
                from . import composite as comp

                comp.draw(fig, spec, rng)
            else:
                # Table, not an if/elif chain ending in a fallback: an unhandled
                # chart type must raise here, not quietly render as some other
                # chart and get stored as the style the user approved.
                _DRAW[ctype](fig, ax, spec, rng)
                if ctype != "heatmap":
                    _apply_scales(ax, spec)
                    _finish_legend(ax, spec, ctype)
            if not composite:
                fig.tight_layout()
            # metadata: drop the Software chunk so bytes don't vary across
            # matplotlib versions — determinism is part of the contract.
            fig.savefig(buf, format="png", dpi=DPI, metadata={"Software": None})
            # The TRUE raster size: Agg truncates inches*dpi, it doesn't round,
            # so round(w_in * DPI) is off by a pixel for many aspects — and these
            # numbers are stored as figures.width/height and drive the masonry.
            width, height = (int(v) for v in fig.canvas.get_width_height())
        finally:
            plt.close(fig)
    return buf.getvalue(), width, height
