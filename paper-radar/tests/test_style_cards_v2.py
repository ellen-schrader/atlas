"""Style cards v2 — composite figures: several panels over a shared row axis.

The invariant that matters and that a picture can't prove: every panel bound to a
domain must project the SAME synthetic dataset in the SAME row order. If they
don't, row 3 of the heatmap isn't row 3 of the bar and the figure is a lie.
"""

from __future__ import annotations

import numpy as np
import pytest

from atlas_mcp import spec as card_spec

COMPOSITE = {
    "spec_version": 2,
    "chart": {"aspect": [7.5, 4.2]},
    "domains": {"phenotype": {"n_categories": 12, "order": "clustered"}},
    "palettes": {
        "region": ["#0f8f8b", "#b4791a", "#6a5cd8", "#c23c86"],
        "expr": ["#2166ac", "#b2182b"],
    },
    "layout": {
        "rows": 1,
        "cols": 4,
        "width_ratios": [0.5, 3, 1.4, 1.2],
        "share_y": "phenotype",
    },
    "panels": [
        {"kind": "dendrogram", "position": [0, 0], "rows": "phenotype", "labels": {"rows": False}},
        {
            "kind": "heatmap", "position": [0, 1], "rows": "phenotype", "columns": 10,
            "palette": "expr", "scale": {"kind": "diverging", "midpoint": 0},
            "colorbar": {"show": True, "label": "z-score"}, "labels": {"rows": True},
        },
        {
            "kind": "stacked_bar", "position": [0, 2], "rows": "phenotype", "mode": "percent",
            "orientation": "horizontal", "palette": "region", "labels": {"rows": False},
            "data_hints": {"composition": "dominant_one"},
        },
        {
            "kind": "bar", "position": [0, 3], "rows": "phenotype", "orientation": "horizontal",
            "axes": {"x_scale": "log"}, "labels": {"rows": False},
            "data_hints": {"distribution": "long_tail"},
        },
    ],
    "legend": {"mode": "figure", "loc": "below"},
}


# --- validation --------------------------------------------------------------


def test_composite_validates_and_normalises():
    norm = card_spec.validate_spec(COMPOSITE)
    assert norm["spec_version"] == 2
    assert card_spec.is_composite(norm)
    assert norm["chart"]["type"] == "composite"
    assert [p["kind"] for p in norm["panels"]] == [
        "dendrogram", "heatmap", "stacked_bar", "bar",
    ]
    # a row panel's default orientation is horizontal — a count plot on a row axis
    assert norm["panels"][3]["orientation"] == "horizontal"
    assert norm["palettes"]["region"][0] == "#0f8f8b"


def test_v1_specs_still_take_the_v1_path():
    norm = card_spec.validate_spec({"chart": {"type": "line"}})
    assert norm["spec_version"] == 1
    assert not card_spec.is_composite(norm)
    assert "panels" not in norm


def test_version_is_inferred_from_panels():
    # a spec with panels but no spec_version is a composite, not a broken v1
    norm = card_spec.validate_spec(
        {"panels": [{"kind": "line", "position": [0, 0]}], "layout": {"rows": 1, "cols": 1}}
    )
    assert norm["spec_version"] == 2


@pytest.mark.parametrize(
    "bad",
    [
        # a row panel in a composite must bind to a domain, or its rows can't line up
        {"spec_version": 2, "domains": {"p": {"n_categories": 5}},
         "panels": [{"kind": "heatmap", "position": [0, 0]}]},
        # a panel palette must NAME a declared palette
        {"spec_version": 2, "panels": [{"kind": "line", "position": [0, 0], "palette": "nope"}]},
        # a panel must sit inside the layout
        {"spec_version": 2, "layout": {"rows": 1, "cols": 1},
         "panels": [{"kind": "line", "position": [0, 3]}]},
        # two panels can't share a cell
        {"spec_version": 2, "layout": {"rows": 1, "cols": 2},
         "panels": [{"kind": "line", "position": [0, 0]}, {"kind": "bar", "position": [0, 0]}]},
        # rows must name a declared domain
        {"spec_version": 2, "panels": [{"kind": "heatmap", "position": [0, 0], "rows": "ghost"}]},
        # share_y must name a declared domain
        {"spec_version": 2, "layout": {"share_y": "ghost"},
         "panels": [{"kind": "line", "position": [0, 0]}]},
        # labels must match n_categories — a mismatch would silently mislabel rows
        {"spec_version": 2, "domains": {"p": {"n_categories": 3, "labels": ["a", "b"]}},
         "panels": [{"kind": "heatmap", "position": [0, 0], "rows": "p"}]},
        {"spec_version": 2, "panels": []},  # a composite is made of panels
        {"spec_version": 2, "panels": [{"kind": "violin", "position": [0, 0]}]},
        {"spec_version": 3, "panels": [{"kind": "line", "position": [0, 0]}]},
    ],
)
def test_invalid_composites_are_rejected(bad):
    with pytest.raises(card_spec.SpecError):
        card_spec.validate_spec(bad)


def test_composite_bounds_hold_on_the_read_path():
    # same rule as v1: a stored spec is attacker-controllable via figures_update RLS
    with pytest.raises(card_spec.SpecError):
        card_spec.for_render({**COMPOSITE, "chart": {"aspect": [12000, 12000]}})
    with pytest.raises(card_spec.SpecError):
        card_spec.for_render(
            {**COMPOSITE, "domains": {"phenotype": {"n_categories": 10**6}}}
        )


# --- the shared-domain invariant ---------------------------------------------


def _domain(order="clustered", n=12, seed=3):
    pytest.importorskip("matplotlib")
    from atlas_mcp import composite as comp

    rng = np.random.default_rng(seed)
    return comp._Domain(
        "phenotype",
        {"n_categories": n, "order": order},
        columns=10,
        rng=rng,
        hints={"composition": "dominant_one", "distribution": "long_tail"},
    )


def test_every_panel_sees_the_same_rows_in_the_same_order():
    """The keystone: one domain -> one dataset -> every panel projects it. The
    heatmap's row i, the composition bar's row i and the count plot's row i must
    all be the SAME phenotype."""
    dom = _domain()
    order = dom.order
    # each projection is indexed by the one order, so row i is one phenotype
    assert dom.ordered(dom.matrix).shape[0] == dom.n
    assert dom.ordered(dom.composition).shape[0] == dom.n
    assert dom.ordered(dom.abundance).shape[0] == dom.n
    assert len(dom.ordered_labels()) == dom.n
    # row i of every projection comes from the same source row
    for i in (0, 5, 11):
        src = order[i]
        assert np.allclose(dom.ordered(dom.matrix)[i], dom.matrix[src])
        assert np.allclose(dom.ordered(dom.composition)[i], dom.composition[src])
        assert dom.ordered(dom.abundance)[i] == dom.abundance[src]
        assert dom.ordered_labels()[i] == dom.labels[src]


def test_order_rules_actually_order():
    by_value = _domain(order="by_value")
    vals = by_value.ordered(by_value.abundance)
    assert np.all(np.diff(vals) <= 1e-12), "by_value must sort rows by abundance"

    fixed = _domain(order="fixed")
    assert list(fixed.order) == list(range(fixed.n))

    clustered = _domain(order="clustered")
    assert sorted(clustered.order) == list(range(clustered.n))  # a permutation
    assert list(clustered.order) != list(range(clustered.n))  # …and a real one


def test_composition_rows_sum_to_one():
    dom = _domain()
    assert np.allclose(dom.composition.sum(axis=1), 1.0)


def test_labels_default_to_synthetic():
    # real phenotype names are opt-in: for an unpublished figure the SET of
    # phenotypes can itself be the finding
    dom = _domain()
    assert dom.labels[0] == "Type A"
    named = _domain()
    named.labels = ["CD8 T cell"] * named.n  # only when the spec asks for it
    assert named.ordered_labels()[0] == "CD8 T cell"


# --- rendering ----------------------------------------------------------------


def _render(spec_dict, seed=7):
    pytest.importorskip("matplotlib")
    from atlas_mcp import render as card_render

    return card_render.render(card_spec.validate_spec(spec_dict), seed)


def test_composite_renders():
    png, w, h = _render(COMPOSITE)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert (w, h) == (2250, 1260)


def test_composite_render_is_deterministic():
    a, _, _ = _render(COMPOSITE, seed=9)
    b, _, _ = _render(COMPOSITE, seed=9)
    assert a == b
    c, _, _ = _render(COMPOSITE, seed=10)
    assert a != c


def test_render_survives_jsonb_key_reordering():
    """Postgres jsonb does NOT preserve object key order (it sorts by key length,
    then bytewise), so a spec read back from `figures.spec` hands us its domains
    in a different order than we wrote. Each domain consumes draws from the shared
    rng, so an order-dependent loop would re-render a DIFFERENT figure from the
    same stored spec — silently breaking "the stored row reproduces the board
    image". The renderer must be blind to key order.
    """
    two_domains = {
        "spec_version": 2,
        "chart": {"aspect": [6, 3.5]},
        "domains": {
            "zzz_phenotype": {"n_categories": 6, "order": "by_value"},
            "b": {"n_categories": 5, "order": "fixed"},
        },
        "layout": {"rows": 1, "cols": 2},
        "panels": [
            {"kind": "heatmap", "position": [0, 0], "rows": "zzz_phenotype", "columns": 6},
            {"kind": "bar", "position": [0, 1], "rows": "b", "orientation": "horizontal"},
        ],
    }
    norm = card_spec.validate_spec(two_domains)
    # exactly what jsonb does to the key order on the way back out
    reordered = {
        **norm,
        "domains": dict(sorted(norm["domains"].items(), key=lambda kv: (len(kv[0]), kv[0]))),
    }
    assert list(reordered["domains"]) != list(norm["domains"]), "the fixture must reorder"

    pytest.importorskip("matplotlib")
    from atlas_mcp import render as card_render

    seed = card_spec.spec_seed(norm)
    assert seed == card_spec.spec_seed(reordered)  # the seed already sorts keys
    a, _, _ = card_render.render(norm, seed)
    b, _, _ = card_render.render(reordered, seed)
    assert a == b, "a jsonb key reorder must not change the rendered figure"


@pytest.mark.parametrize("kind", card_spec.PANEL_KINDS)
def test_every_panel_kind_renders(kind):
    rows_bound = kind in card_spec.ROW_KINDS
    panel = {"kind": kind, "position": [0, 0]}
    if rows_bound:
        panel["rows"] = "phenotype"
    spec = {
        "spec_version": 2,
        "domains": {"phenotype": {"n_categories": 8, "order": "by_value"}},
        "layout": {"rows": 1, "cols": 1},
        "panels": [panel],
    }
    png, _, _ = _render(spec)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_sequential_and_diverging_heatmaps_both_render():
    for kind in card_spec.SCALE_KINDS:
        spec = {
            "spec_version": 2,
            "domains": {"p": {"n_categories": 6, "order": "clustered"}},
            "palettes": {"ramp": ["#f1f3f2", "#0e7773"]},
            "layout": {"rows": 1, "cols": 1},
            "panels": [
                {
                    "kind": "heatmap", "position": [0, 0], "rows": "p", "palette": "ramp",
                    "scale": {"kind": kind, "midpoint": 0},
                }
            ],
        }
        png, _, _ = _render(spec)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


# --- the MCP surface ----------------------------------------------------------


def test_cvd_checks_each_named_palette_but_not_the_heatmap_ramp():
    pytest.importorskip("mcp")
    pytest.importorskip("supabase")
    from atlas_mcp import server

    norm = card_spec.validate_spec(COMPOSITE)
    safe, verdict = server._spec_cvd(norm)
    assert "region" in verdict  # the categorical palette IS checked
    assert "expr" not in verdict  # the heatmap's ramp is not a categorical set
    assert isinstance(safe, bool)


def test_spec_summary_describes_a_composite():
    pytest.importorskip("mcp")
    pytest.importorskip("supabase")
    from atlas_mcp import server

    text = server._spec_summary(card_spec.validate_spec(COMPOSITE))
    assert "composite" in text and "4 panels" in text and "phenotype" in text
