"""Render a v2 (composite) style-card spec: several panels over a shared axis.

The figures this lab publishes are usually composites — a heatmap of phenotype x
marker, a percent-stacked composition bar, an abundance count plot — three panels
whose ROWS ARE THE SAME ROWS. What makes that one figure rather than three plots
glued together is shared structure, and the piece that carries it is the shared
synthetic **dataset**, not merely a shared axis:

    one domain  ->  one synthetic dataset  ->  every panel projects it

If each panel invented its own categories, row 3 of the heatmap would not be row
3 of the bar and the figure would be a lie. So :class:`_Domain` draws the
abundance, composition and expression matrix ONCE, decides the row order once,
and hands the same rows to every panel bound to it.

Nothing here touches real data: every value is rng-generated from the spec's
gestalt-level ``data_hints`` (``composition: dominant_one``, ``distribution:
long_tail``), which is what keeps a lab's actual results — the thing a
composition plot usually *is* — out of the stored card.

See docs/STYLE_CARDS_PLAN.md ("Spec v2 — composite figures").
"""

from __future__ import annotations

import numpy as np

from . import spec as card_spec

_INK = "#222222"
# A neutral grey midpoint: a diverging scale needs two hues meeting at a neutral,
# never a third hue (that is how a rainbow ramp happens).
_NEUTRAL = "#f2f2f2"


class _Domain:
    """The shared row axis, and the one synthetic dataset every bound panel reads.

    ``order`` is itself a style fact of these figures — they are almost always
    sorted by abundance or by a clustering, and an unordered heatmap looks wrong
    even when every other style parameter is right.
    """

    def __init__(self, name: str, cfg: dict, columns: int, rng, hints: dict) -> None:
        self.name = name
        self.n = cfg["n_categories"]
        # Real category names are opt-in; the default is synthetic, because for an
        # unpublished figure the SET and ORDERING of phenotypes can be the finding.
        self.labels = cfg.get("labels") or [f"Type {_letter(i)}" for i in range(self.n)]

        # abundance: how many cells of each phenotype — a long tail is the norm.
        if hints.get("distribution") == "uniform":
            self.abundance = rng.uniform(0.4, 1.0, self.n)
        else:
            self.abundance = np.sort(rng.pareto(1.6, self.n) + 0.15)[::-1]

        # composition: each row's split across regions/samples (rows sum to 1).
        k = 4
        comp = hints.get("composition", "dominant_one")
        if comp == "even":
            alpha = np.full(k, 6.0)
        elif comp == "long_tail":
            alpha = np.array([4.0, 2.0, 1.0, 0.5])
        else:  # dominant_one — one region dominates each phenotype
            alpha = np.full(k, 0.45)
        self.composition = rng.dirichlet(alpha, self.n)

        # expression: the phenotype x marker matrix behind the heatmap. Built
        # from a few latent programmes so rows genuinely cluster — otherwise the
        # dendrogram and the "clustered" order would be decoration over noise.
        cols = max(columns, 2)
        loadings = rng.normal(0, 1, (self.n, 3))
        programmes = rng.normal(0, 1, (3, cols))
        self.matrix = loadings @ programmes + rng.normal(0, 0.35, (self.n, cols))

        # ONE linkage produces BOTH the clustered row order and the tree drawn
        # beside it. They are the same claim about the same data, so they must not
        # be two algorithms that merely happen to agree — see :meth:`_linkage`.
        self.linkage, self.leaf_order = self._linkage()
        self.order = self._order(cfg["order"])

    def _order(self, rule: str) -> np.ndarray:
        if rule == "fixed":
            return np.arange(self.n)
        if rule == "by_value":
            return np.argsort(-self.abundance)
        return np.array(self.leaf_order)

    def _linkage(self) -> tuple[list, list]:
        """UPGMA (average-linkage) agglomerative clustering of the rows.

        Returns ``(merges, leaf_order)`` where each merge is
        ``(left_id, right_id, height)`` and ids below ``n`` are leaves.

        Why a real linkage and not a schematic tree: a dendrogram's HEIGHT *is*
        distance — tight clusters merge low and early, an outlier joins late on a
        long branch. A tree with evenly-spaced merges is a perfectly balanced comb,
        which no real data produces; it is the detail a domain reader would clock
        as fake. Deriving the leaf order from the same tree also makes the heatmap's
        row order and the tree structurally consistent, instead of two independent
        computations that can quietly disagree about which rows group together.
        """
        n = self.n
        if n < 2:
            return [], list(range(n))
        m = self.matrix
        unit = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        d = 1.0 - unit @ unit.T  # cosine distance

        members = {i: [i] for i in range(n)}
        height = dict.fromkeys(range(n), 0.0)  # a leaf sits at distance 0
        pairs = {(i, j): float(d[i, j]) for i in range(n) for j in range(i + 1, n)}
        merges: list[tuple[int, int, float]] = []
        nid = n

        while len(members) > 1:
            # Tie-break on the ids as well as the distance: a bare min() over a dict
            # would depend on insertion order, and renders must be reproducible.
            (a, b), h = min(pairs.items(), key=lambda kv: (kv[1], kv[0]))
            na, nb = len(members[a]), len(members[b])
            for c in members:
                if c in (a, b):
                    continue
                dac = pairs[(min(a, c), max(a, c))]
                dbc = pairs[(min(b, c), max(b, c))]
                pairs[(min(nid, c), max(nid, c))] = (na * dac + nb * dbc) / (na + nb)  # UPGMA
            for key in [k for k in pairs if a in k or b in k]:
                del pairs[key]
            members[nid] = members[a] + members[b]  # left then right → planar leaves
            height[nid] = h
            del members[a], members[b]
            merges.append((a, b, h))
            nid += 1

        self._height = height
        self._members = members  # only the root survives
        return merges, members[nid - 1]

    def ordered(self, arr):
        return np.asarray(arr)[self.order]

    def ordered_labels(self) -> list[str]:
        return [self.labels[i] for i in self.order]


def _letter(i: int) -> str:
    return chr(ord("A") + i % 26)


def _thin_log_ticks(axis, lo: float, hi: float) -> None:
    """Readable ticks on a log axis in a narrow side panel.

    Two failure modes to avoid: whole decades smear their minor labels over each
    other, and a range that spans LESS than one decade (abundance often does —
    e.g. 0.15 to 0.24) contains no power of ten at all, so decade-only ticks leave
    the axis completely unlabelled.
    """
    from matplotlib.ticker import (
        LogFormatterSciNotation,
        LogLocator,
        NullFormatter,
        ScalarFormatter,
    )

    decades = np.log10(max(hi, 1e-9)) - np.log10(max(lo, 1e-9))
    if decades < 1.0:
        # Inside one decade: label the 1-2-5 subdivisions, or the axis says nothing.
        axis.set_major_locator(LogLocator(base=10.0, subs=(1.0, 2.0, 5.0), numticks=6))
        fmt = ScalarFormatter()
        fmt.set_scientific(False)
        axis.set_major_formatter(fmt)
    else:
        axis.set_major_locator(LogLocator(base=10.0, numticks=4))
        axis.set_major_formatter(LogFormatterSciNotation(base=10.0))
    axis.set_minor_locator(LogLocator(base=10.0, subs=(0.2, 0.4, 0.6, 0.8), numticks=12))
    axis.set_minor_formatter(NullFormatter())


def _palette_of(panel: dict, palettes: dict, fallback: list[str]) -> list[str]:
    """A panel's colours: a NAMED palette (so a category keeps its colour in every
    panel and in the legend) or an inline list."""
    pal = panel.get("palette")
    if isinstance(pal, str):
        return palettes[pal]
    if isinstance(pal, list) and pal:
        return pal
    return fallback


def _colormap(panel: dict, colours: list[str]):
    from matplotlib.colors import LinearSegmentedColormap

    kind = panel["scale"]["kind"]
    if kind == "diverging":
        # Two hues meeting at a NEUTRAL midpoint. A z-scored expression heatmap
        # diverges around zero, and a sequential ramp gets that look plainly wrong.
        lo = colours[0]
        hi = colours[-1] if len(colours) > 1 else "#c23c86"
        stops = [lo, _NEUTRAL, hi]
    else:
        # Sequential = ONE hue, light to dark. Never a rainbow.
        stops = ["#ffffff", colours[0]] if len(colours) < 2 else list(colours)
    return LinearSegmentedColormap.from_list("style_card", stops)


# --- panel drawers ------------------------------------------------------------
# Every drawer takes the same shape, and every row-bound one reads its rows from
# the shared domain, so the panels cannot disagree about what row 3 is.


def _p_heatmap(fig, ax, panel, dom, palettes, rng, base_size):
    # The domain builds ONE matrix sized to the widest heatmap on it; a panel that
    # asked for fewer columns takes the first N, so its validated `columns` is what
    # actually gets drawn.
    data = dom.ordered(dom.matrix)[:, : panel.get("columns", dom.matrix.shape[1])]
    if panel["scale"]["kind"] == "diverging":
        lim = float(np.abs(data).max()) or 1.0
        mid = panel["scale"]["midpoint"]
        vmin, vmax = mid - lim, mid + lim
    else:
        vmin, vmax = float(data.min()), float(data.max())
    cmap = _colormap(panel, _palette_of(panel, palettes, ["#0e7773"]))
    im = ax.imshow(data, aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_xticks([])
    ax.grid(False)
    if panel["colorbar"]["show"]:
        cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
        cb.outline.set_visible(False)
        cb.ax.tick_params(labelsize=base_size - 2, length=2)
        if panel["colorbar"]["label"]:
            cb.set_label(panel["colorbar"]["label"], fontsize=base_size - 1)


def _p_stacked_bar(fig, ax, panel, dom, palettes, rng, base_size):
    comp = dom.ordered(dom.composition)
    mode = panel["mode"]
    if mode == "percent":
        comp = comp / comp.sum(axis=1, keepdims=True)
    colours = _palette_of(panel, palettes, list(card_spec.DEFAULT_PALETTE))
    y = np.arange(dom.n, dtype=float)
    horizontal = panel["orientation"] == "horizontal"
    k_n = comp.shape[1]

    if mode == "grouped":
        # Side by side, not stacked — that IS the mode. Drawing it stacked would
        # make the card claim one composition idiom and show its opposite.
        thick = 0.82 / k_n
        for k in range(k_n):
            off = (k - (k_n - 1) / 2) * thick
            c = colours[k % len(colours)]
            label = f"Region {_letter(k)}"
            if horizontal:
                ax.barh(y + off, comp[:, k], height=thick * 0.92, color=c, label=label,
                        linewidth=0)
            else:
                ax.bar(y + off, comp[:, k], width=thick * 0.92, color=c, label=label,
                       linewidth=0)
        span = float(comp.max())
    else:
        base = np.zeros(dom.n)
        for k in range(k_n):
            c = colours[k % len(colours)]
            label = f"Region {_letter(k)}"
            if horizontal:
                ax.barh(y, comp[:, k], left=base, height=0.82, color=c, label=label, linewidth=0)
            else:
                ax.bar(y, comp[:, k], bottom=base, width=0.82, color=c, label=label, linewidth=0)
            base = base + comp[:, k]
        span = float(base.max())

    lim = 1.0 if mode == "percent" else span
    if horizontal:
        ax.set_xlim(0, lim)
    else:
        ax.set_ylim(0, lim)
    ax.grid(False)


def _p_bar(fig, ax, panel, dom, palettes, rng, base_size):
    vals = dom.ordered(dom.abundance)
    colours = _palette_of(panel, palettes, ["#576466"])
    y = np.arange(dom.n)
    lo, hi = float(vals.min()), float(vals.max())
    if panel["orientation"] == "horizontal":
        ax.barh(y, vals, height=0.82, color=colours[0], linewidth=0)
        if panel["axes"]["x_scale"] == "log":
            ax.set_xscale("log")
            _thin_log_ticks(ax.xaxis, lo, hi)
    else:
        ax.bar(y, vals, width=0.82, color=colours[0], linewidth=0)
        if panel["axes"]["y_scale"] == "log":
            ax.set_yscale("log")
            _thin_log_ticks(ax.yaxis, lo, hi)


def _p_annotation_track(fig, ax, panel, dom, palettes, rng, base_size):
    """The categorical colour strip beside a heatmap — one cell per row."""
    colours = _palette_of(panel, palettes, list(card_spec.DEFAULT_PALETTE))
    groups = rng.integers(0, max(2, min(len(colours), 5)), dom.n)
    strip = dom.ordered(groups).reshape(-1, 1)
    from matplotlib.colors import ListedColormap

    ax.imshow(strip, aspect="auto", cmap=ListedColormap(colours), interpolation="nearest")
    ax.set_xticks([])
    ax.grid(False)


def _p_dendrogram(fig, ax, panel, dom, palettes, rng, base_size):
    """The tree that explains the row order — drawn from the SAME UPGMA linkage
    that produced it (``_Domain._linkage``), so the branches and the heatmap's rows
    cannot disagree, and the merge heights are real distances: tight clusters join
    early on short branches, an outlier joins last on a long one."""
    n = dom.n
    if n < 2 or not dom.linkage:
        ax.set_xticks([])
        ax.set_yticks([])
        for side in ("top", "right", "bottom", "left"):
            ax.spines[side].set_visible(False)
        return

    # Where each row sits on the shared axis (the tree's leaves are the heatmap's
    # rows, by construction — dom.order IS the linkage's leaf order when the domain
    # is clustered, and a row still maps to its own y otherwise).
    pos_of_row = {int(r): i for i, r in enumerate(dom.order)}
    ypos = {i: float(pos_of_row[i]) for i in range(n)}  # leaves
    hmax = max(h for _, _, h in dom.linkage) or 1.0

    def x_at(cid: int) -> float:
        # Leaves sit against the heatmap (x=1) and the root is furthest from it —
        # the conventional orientation for a row dendrogram on the left.
        return 1.0 - 0.95 * (dom._height[cid] / hmax)

    for k, (a, b, h) in enumerate(dom.linkage):
        node = n + k  # ids are handed out in merge order, so this is the new cluster
        ya, yb = ypos[a], ypos[b]
        x = 1.0 - 0.95 * (h / hmax)
        # each child's own branch out to the join, then the connector between them
        ax.plot([x_at(a), x], [ya, ya], color=_INK, linewidth=0.8)
        ax.plot([x_at(b), x], [yb, yb], color=_INK, linewidth=0.8)
        ax.plot([x, x], [ya, yb], color=_INK, linewidth=0.8, solid_capstyle="butt")
        ypos[node] = (ya + yb) / 2.0

    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.grid(False)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_visible(False)


_ROW_DRAW = {
    "heatmap": _p_heatmap,
    "stacked_bar": _p_stacked_bar,
    "bar": _p_bar,
    "annotation_track": _p_annotation_track,
    "dendrogram": _p_dendrogram,
}


def draw(fig, spec: dict, rng) -> None:
    """Draw a validated v2 composite onto ``fig``."""
    from matplotlib.gridspec import GridSpec

    from . import render as v1

    layout = spec["layout"]
    base_size = spec["typography"]["base_size"]

    # Build each domain ONCE — this is what makes the panels agree on their rows.
    cols_for = {}
    for p in spec["panels"]:
        if p.get("rows") and p["kind"] == "heatmap":
            cols_for[p["rows"]] = max(cols_for.get(p["rows"], 0), p.get("columns", 8))
    domains = {}
    # SORTED, not dict order: each domain consumes draws from the shared rng, so
    # the iteration order decides the synthetic data. Postgres jsonb does NOT
    # preserve object key order (it sorts by key length, then bytewise), so a spec
    # read back from the DB hands us its domains in a different order than the one
    # we wrote — and an unsorted loop would re-render a *different* figure from the
    # same stored spec. Sorting makes the draw order canonical either way.
    for name, cfg in sorted(spec["domains"].items()):
        hints = next(
            (p["data_hints"] for p in spec["panels"] if p.get("rows") == name),
            {"composition": "dominant_one", "distribution": "long_tail"},
        )
        domains[name] = _Domain(name, cfg, cols_for.get(name, 8), rng, hints)

    # The figure uses matplotlib's `constrained` layout engine (colorbars and a
    # figure legend are beyond tight_layout), so panel spacing is expressed through
    # the engine rather than GridSpec's wspace/hspace, which it would override.
    fig.get_layout_engine().set(w_pad=layout["gap"], h_pad=layout["gap"], wspace=0, hspace=0)
    gs = GridSpec(
        layout["rows"],
        layout["cols"],
        figure=fig,
        width_ratios=layout["width_ratios"],
        height_ratios=layout["height_ratios"],
    )

    handles: dict[str, tuple] = {}

    for p in spec["panels"]:
        r, c = p["position"]
        ax = fig.add_subplot(gs[r, c])

        dom = domains.get(p.get("rows")) if p.get("rows") else None
        if dom is not None and p["kind"] in _ROW_DRAW:
            _ROW_DRAW[p["kind"]](fig, ax, p, dom, spec["palettes"], rng, base_size)
            # WHICH axis carries the categories depends on the panel: a bar drawn
            # `vertical` puts them on x and its VALUES on y. Pinning the category
            # limits to y regardless would clamp the value axis to the row-index
            # range and hang the row labels off the value scale.
            cat_axis = "x" if p.get("orientation") == "vertical" else "y"
            # Every row panel spans the same rows in the same direction (top-down,
            # as imshow draws them). Deliberately NOT matplotlib's sharey: shared
            # axes share one tick locator, so a panel that hides its row ticks
            # would wipe the labels off the panel that shows them.
            if cat_axis == "y":
                ax.set_ylim(dom.n - 0.5, -0.5)
            else:
                ax.set_xlim(-0.5, dom.n - 0.5)
            cat, val = (ax.yaxis, ax.xaxis) if cat_axis == "y" else (ax.xaxis, ax.yaxis)
            # Row labels on ONE panel — this is what makes several plots read as
            # one figure rather than three stuck together.
            if p["labels"]["rows"]:
                cat.set_ticks(np.arange(dom.n))
                cat.set_ticklabels(
                    dom.ordered_labels(),
                    fontsize=base_size - 2,
                    **({"rotation": 90} if cat_axis == "x" else {}),
                )
            else:
                cat.set_ticks([])
            if not p["labels"]["values"]:
                val.set_ticks([])
        else:
            # A free panel: a plain v1 chart inside the composite.
            colours = _palette_of(p, spec["palettes"], list(card_spec.DEFAULT_PALETTE))
            # v1's line/scatter/bar/histogram drawers colour from the axes prop_cycle,
            # so the panel's palette has to BE that cycle — otherwise the palette it
            # names is ignored and a category doesn't keep its colour across panels.
            ax.set_prop_cycle(color=colours)
            panel_spec = {
                "chart": {"type": p["kind"], "aspect": [1, 1]},
                "axes": p["axes"],
                "palette": colours,
                "series": p.get("series") or [dict(card_spec.SERIES_DEFAULTS)],
                "legend": p.get("legend") or {"mode": "none"},
                "typography": spec["typography"],
                "data_hints": {**p["data_hints"], "n_series": len(p.get("series") or [1])},
            }
            v1._DRAW[p["kind"]](fig, ax, panel_spec, rng)
            if p["kind"] != "heatmap":
                v1._apply_scales(ax, panel_spec)

        if p.get("title"):
            ax.set_title(p["title"], fontsize=base_size, pad=4)
        ax.tick_params(labelsize=base_size - 2, length=2)
        for side in ("top", "right"):
            if p["axes"]["spines"] == "open" and p["kind"] not in ("heatmap", "annotation_track"):
                ax.spines[side].set_visible(False)

        h, lbl = ax.get_legend_handles_labels()
        if spec["legend"]["mode"] == "panel" and h:
            ax.legend(h, lbl, frameon=False, fontsize=base_size - 2, loc="best")
        for handle, name in zip(h, lbl, strict=False):
            handles.setdefault(name, (handle, name))

    # In a composite the legend belongs to the FIGURE, not to one panel.
    if spec["legend"]["mode"] == "figure" and handles:
        hs = [h for h, _ in handles.values()]
        ls = [n for _, n in handles.values()]
        # "outside …" is what makes the constrained-layout engine RESERVE room for
        # the legend. A plain "lower center" is placed over the axes, and the
        # legend lands on top of the panels' tick labels.
        if spec["legend"]["loc"] == "below":
            fig.legend(
                hs, ls, loc="outside lower center", ncols=min(len(ls), 4),
                frameon=False, fontsize=base_size - 1,
            )
        else:
            fig.legend(
                hs, ls, loc="outside center right", frameon=False, fontsize=base_size - 1,
            )
