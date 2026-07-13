"""Render a style-card spec to a PNG with synthetic data.

Deterministic by construction: the same (spec, seed) yields the same bytes.
Both the preview tool and the stored card seed from ``spec.spec_seed``, so the
board image is exactly the render the user approved, and re-rendering from the
stored row reproduces it. Nothing of the admired original enters the render —
only the validated style parameters, and rng-generated data shaped by the
spec's ``data_hints``.

matplotlib is imported lazily inside :func:`render` — it is an ``mcp``-extra
dependency, and importing this module must stay cheap for environments that
only validate specs.
"""

from __future__ import annotations

import io

import numpy as np

DPI = 300  # crisp on the board and in downscaled tool previews

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
_INK = "#222222"


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


def _xs(spec: dict, n: int) -> np.ndarray:
    if spec["axes"]["x_scale"] == "log":
        return np.logspace(0.0, 2.0, n)
    return np.linspace(0.0, 10.0, n)


def _draw_line(ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    n = hints["n_points"]
    x = _xs(spec, n)
    t = np.linspace(0.0, 1.0, n)
    sigma = _NOISE[hints["noise"]]
    for i, s in enumerate(spec["series"]):
        y = _curve(hints["trend"], t, i) + rng.normal(0.0, sigma, n)
        y = np.clip(y, 0.02, None)  # keep a log y-axis renderable
        ax.plot(
            x,
            y,
            linestyle=_DASH[s["dash"]],
            linewidth=s["line_width"],
            marker=_MARKER[s["marker"]],
            markersize=4.0 + s["line_width"],
            label=f"series {_letter(i)}",
        )
    ax.set_xlabel("x")
    ax.set_ylabel("signal")


def _draw_scatter(ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    series = spec["series"]
    per = max(hints["n_points"] // len(series), 3)
    for i, s in enumerate(series):
        cx, cy = rng.uniform(0.25, 0.75, 2)
        ax.scatter(
            np.clip(rng.normal(cx, 0.06, per), 0.01, None),
            np.clip(rng.normal(cy, 0.06, per), 0.01, None),
            s=26.0,
            marker=_MARKER[s["marker"]] or "o",
            alpha=0.85,
            linewidths=0,
            label=f"cluster {_letter(i)}",
        )
    ax.set_xlabel("dim 1")
    ax.set_ylabel("dim 2")


def _draw_bar(ax, spec: dict, rng) -> None:
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


def _draw_histogram(ax, spec: dict, rng) -> None:
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


def _draw_heatmap(ax, fig, spec: dict, rng) -> None:
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


def _draw_box(ax, spec: dict, rng) -> None:
    hints = spec["data_hints"]
    series = spec["series"]
    groups = len(series) if len(series) > 1 else 4
    per = max(hints["n_points"] // groups, 5)
    centers = _curve(hints["trend"], np.linspace(0.0, 1.0, groups), 0)
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
    output is identical across machines."""
    from cycler import cycler

    axes_s, typo = spec["axes"], spec["typography"]
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
        "axes.prop_cycle": cycler("color", list(spec["palette"])),
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


def render(spec: dict, seed: int) -> tuple[bytes, int, int]:
    """Render a *validated* spec → ``(png_bytes, width_px, height_px)``.

    Pass the output of ``spec.validate_spec`` only; raw user specs may be
    missing the defaults this renderer assumes.
    """
    import matplotlib

    # Headless, never a display server. Switching with force=True re-initialises
    # the backend, so only do it when something else got there first.
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    rng = np.random.default_rng(seed)
    w_in, h_in = spec["chart"]["aspect"]
    ctype = spec["chart"]["type"]
    buf = io.BytesIO()
    with plt.rc_context(_rc(spec)):
        fig, ax = plt.subplots(figsize=(w_in, h_in), dpi=DPI)
        try:
            if ctype == "line":
                _draw_line(ax, spec, rng)
            elif ctype == "scatter":
                _draw_scatter(ax, spec, rng)
            elif ctype == "bar":
                _draw_bar(ax, spec, rng)
            elif ctype == "histogram":
                _draw_histogram(ax, spec, rng)
            elif ctype == "heatmap":
                _draw_heatmap(ax, fig, spec, rng)
            else:
                _draw_box(ax, spec, rng)
            if ctype != "heatmap":
                _apply_scales(ax, spec)
                _finish_legend(ax, spec, ctype)
            fig.tight_layout()
            # metadata: drop the Software chunk so bytes don't vary across
            # matplotlib versions — determinism is part of the contract.
            fig.savefig(buf, format="png", dpi=DPI, metadata={"Software": None})
        finally:
            plt.close(fig)
    return buf.getvalue(), round(w_in * DPI), round(h_in * DPI)
