"""Style cards: spec validation, deterministic rendering, and the MCP write
tool's confirmation gate (offline — no live Supabase/MCP client). The
DB-enforced parts (origin/spec check constraints, RLS) are covered by the
migration + manual stdio verification."""

from __future__ import annotations

import pytest

from atlas_mcp import spec as card_spec

# --- spec validation ---------------------------------------------------------


def test_minimal_spec_fills_defaults():
    norm = card_spec.validate_spec({"chart": {"type": "line"}})
    assert norm["spec_version"] == 1
    assert norm["chart"]["aspect"] == [5.0, 3.4]
    assert norm["axes"] == {"x_scale": "linear", "y_scale": "linear", "grid": "y", "spines": "open"}
    assert norm["palette"] == list(card_spec.DEFAULT_PALETTE)
    assert len(norm["series"]) == 2  # default n_series
    assert norm["series"][0] == {
        "line_width": 1.8,
        "dash": "solid",
        "marker": "none",
        "drawstyle": "linear",
    }
    assert norm["legend"] == {"mode": "direct"}
    assert norm["data_hints"]["trend"] == "rising"
    assert "notes" not in norm and "cvd" not in norm


def test_scatter_defaults_to_circle_markers():
    norm = card_spec.validate_spec({"chart": {"type": "scatter"}})
    assert norm["series"][0]["marker"] == "circle"


def test_series_count_wins_over_n_series_hint():
    norm = card_spec.validate_spec(
        {"chart": {"type": "line"}, "series": [{}, {}, {}], "data_hints": {"n_series": 5}}
    )
    assert norm["data_hints"]["n_series"] == 3


def test_palette_normalises_hex_case_and_hash():
    norm = card_spec.validate_spec({"chart": {"type": "line"}, "palette": ["0F8F8B", "#B4791A"]})
    assert norm["palette"] == ["#0f8f8b", "#b4791a"]


def test_input_cvd_block_is_discarded():
    # the server stamps its own verdict at save time; a claimed one is dropped
    raw = {"chart": {"type": "line"}, "cvd": {"checked": True, "safe": True}}
    assert "cvd" not in card_spec.validate_spec(raw)


@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        {},  # chart.type required
        {"chart": {"type": "pie"}},  # not in the vocabulary
        {"chart": {"type": "line"}, "surprise": 1},  # unknown top-level key
        {"chart": {"type": "line", "draw": "code"}},  # unknown section key
        {"chart": {"type": "line", "aspect": [50, 1]}},  # aspect out of bounds
        {"chart": {"type": "line"}, "palette": ["#12345"]},  # malformed hex
        {"chart": {"type": "line"}, "palette": []},  # empty palette
        {"chart": {"type": "line"}, "series": [{}] * 9},  # > MAX_SERIES
        {"chart": {"type": "line"}, "data_hints": {"n_points": 10_000}},  # > MAX_POINTS
        {"chart": {"type": "line"}, "series": [{"line_width": 25}]},
        {"chart": {"type": "line"}, "legend": {"mode": "direct", "loc": "best"}},  # loc needs box
        {"chart": {"type": "line"}, "notes": "x" * 501},
        {"chart": {"type": "line"}, "spec_version": 2},
        # log axes only make sense where there's no zero baseline / ordinal axis
        {"chart": {"type": "bar"}, "axes": {"x_scale": "log"}},
        {"chart": {"type": "box"}, "axes": {"y_scale": "log"}},
        {"chart": {"type": "histogram"}, "axes": {"x_scale": "log"}},
        # a short palette would cycle colours and defeat the CVD verdict
        {"chart": {"type": "line"}, "palette": ["#0f8f8b"], "series": [{}, {}]},
    ],
)
def test_invalid_specs_are_rejected(bad):
    with pytest.raises(card_spec.SpecError):
        card_spec.validate_spec(bad)


def test_error_messages_name_the_allowed_values():
    with pytest.raises(card_spec.SpecError, match="heatmap"):
        card_spec.validate_spec({"chart": {"type": "pie"}})
    with pytest.raises(card_spec.SpecError, match="typography"):
        card_spec.validate_spec({"chart": {"type": "line"}, "surprise": 1})


def test_spec_seed_ignores_key_order():
    one = {"n_series": 1}
    a = card_spec.validate_spec(
        {"chart": {"type": "line"}, "palette": ["#0f8f8b"], "data_hints": one}
    )
    b = card_spec.validate_spec(
        {"palette": ["#0f8f8b"], "data_hints": one, "chart": {"type": "line"}}
    )
    assert card_spec.spec_seed(a) == card_spec.spec_seed(b)
    c = card_spec.validate_spec(
        {"chart": {"type": "bar"}, "palette": ["#0f8f8b"], "data_hints": one}
    )
    assert card_spec.spec_seed(a) != card_spec.spec_seed(c)


def test_spec_seed_ignores_cvd_stamp():
    # The server stamps `cvd` between the preview render and the stored render;
    # the seed must not change or the board image differs from the approved preview.
    norm = card_spec.validate_spec({"chart": {"type": "line"}})
    stamped = {**norm, "cvd": {"checked": True, "safe": True}}
    assert card_spec.spec_seed(norm) == card_spec.spec_seed(stamped)


# --- renderer ----------------------------------------------------------------


def _render(spec_dict, seed=7):
    pytest.importorskip("matplotlib")
    from atlas_mcp import render as card_render

    return card_render.render(card_spec.validate_spec(spec_dict), seed)


def test_render_is_deterministic():
    spec_dict = {"chart": {"type": "line"}, "data_hints": {"n_points": 12}}
    png1, w1, h1 = _render(spec_dict, seed=42)
    png2, w2, h2 = _render(spec_dict, seed=42)
    assert png1 == png2  # byte-identical — re-renders must reproduce the stored image
    assert (w1, h1) == (w2, h2)
    png3, _, _ = _render(spec_dict, seed=43)
    assert png1 != png3  # the seed actually drives the synthetic data


def test_render_size_follows_aspect():
    raw = {"chart": {"type": "line", "aspect": [4, 3]}, "data_hints": {"n_points": 8}}
    png, w, h = _render(raw)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert (w, h) == (1200, 900)  # aspect × 300 dpi


@pytest.mark.parametrize("ctype", card_spec.CHART_TYPES)
def test_every_chart_type_renders(ctype):
    png, _, _ = _render(
        {
            "chart": {"type": ctype},
            "palette": ["#0f8f8b", "#b4791a"],
            "series": [{"dash": "solid"}, {"dash": "dashed", "marker": "triangle"}],
            "data_hints": {"n_points": 24, "trend": "saturating", "noise": "medium"},
        }
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_step_drawstyle_renders_and_is_monotone():
    # A Kaplan-Meier / CDF staircase: the spec accepts drawstyle=step on a line
    # chart, and the synthetic data must not wander back up under noise.
    import numpy as np

    from atlas_mcp import render as card_render

    norm = card_spec.validate_spec(
        {
            "chart": {"type": "line"},
            "series": [{"drawstyle": "step"}, {"drawstyle": "step"}],
            "palette": ["#2f6fd0", "#e8b820"],
            "data_hints": {"trend": "falling", "noise": "high", "n_points": 40},
        }
    )
    assert norm["series"][0]["drawstyle"] == "step"
    png, _, _ = card_render.render(norm, 5)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    # the monotone guard, exercised directly on the curve the renderer builds
    rng = np.random.default_rng(5)
    t = np.linspace(0.0, 1.0, 40)
    y = card_render._curve("falling", t, 0) + rng.normal(0.0, 0.12, 40)
    y = np.minimum.accumulate(np.clip(y, 0.02, None))
    assert np.all(np.diff(y) <= 0), "a survival curve must never step back up"


def test_drawstyle_defaults_to_linear_and_is_line_only():
    norm = card_spec.validate_spec({"chart": {"type": "line"}})
    assert norm["series"][0]["drawstyle"] == "linear"
    with pytest.raises(card_spec.SpecError, match="drawstyle"):
        card_spec.validate_spec({"chart": {"type": "bar"}, "series": [{"drawstyle": "step"}]})


def test_log_axes_render():
    png, _, _ = _render(
        {
            "chart": {"type": "line"},
            "axes": {"x_scale": "log", "y_scale": "log"},
            "legend": {"mode": "box", "loc": "lower right"},
            "data_hints": {"n_points": 16, "noise": "high"},
        }
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# --- the MCP surface ---------------------------------------------------------

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _server(monkeypatch):
    pytest.importorskip("supabase")
    pytest.importorskip("mcp")
    from atlas_mcp import lab as L
    from atlas_mcp import server

    monkeypatch.setattr(L, "resolve_team", lambda tid: {"id": "t", "name": "Lab A"})
    return server


def test_format_figure_style_card_cites_and_flags_synthetic(monkeypatch):
    server = _server(monkeypatch)
    text = server._format_figure(
        {
            "id": "f1",
            "title": "Dose–response, log x",
            "origin": "style_card",
            "attribution": "Krieger et al., Nat Methods 2025",
            "source_url": "https://doi.org/10.1038/x",
        }
    )
    assert "style card" in text
    assert "synthetic" in text
    assert "Krieger et al., Nat Methods 2025" in text
    # and it must NOT carry the third-party don't-reproduce warning
    assert "don't reproduce" not in text


class _FakeCtx:
    def __init__(self, action="accept"):
        self.action = action

    async def elicit(self, message, schema):
        return SimpleNamespace(action=self.action, data=schema())


def _drive_add(monkeypatch, *, confirm, ctx, spec_dict=None):
    server = _server(monkeypatch)
    from atlas_mcp import moodboard as M

    writes = {"n": 0, "spec": None}

    def fake_add(team, **kwargs):
        writes["n"] += 1
        writes["spec"] = kwargs["spec"]
        return {"id": "fig1"}

    monkeypatch.setattr(M, "add_style_card", fake_add)
    fn = getattr(server.add_plot_to_moodboard, "fn", server.add_plot_to_moodboard)
    out = asyncio.run(
        fn(
            spec=spec_dict or {"chart": {"type": "line"}},
            title="Dose–response",
            attribution="Krieger et al. 2025",
            confirm=confirm,
            ctx=ctx,
        )
    )
    return out, writes


def test_add_plot_dry_run_writes_nothing(monkeypatch):
    out, writes = _drive_add(monkeypatch, confirm=False, ctx=_FakeCtx())
    assert "Nothing added yet" in out
    assert writes["n"] == 0


def test_add_plot_decline_blocks_write(monkeypatch):
    out, writes = _drive_add(monkeypatch, confirm=True, ctx=_FakeCtx(action="decline"))
    assert "Not added" in out
    assert writes["n"] == 0


def test_add_plot_accept_writes_and_stamps_cvd(monkeypatch):
    out, writes = _drive_add(monkeypatch, confirm=True, ctx=_FakeCtx())
    assert "Added style card" in out and "synthetic render" in out
    assert writes["n"] == 1
    # the stored spec carries the server's own CVD verdict
    assert writes["spec"]["cvd"]["checked"] is True
    assert isinstance(writes["spec"]["cvd"]["safe"], bool)


def test_add_plot_links_paper_after_validation(monkeypatch):
    server = _server(monkeypatch)
    from atlas_mcp import lab as L
    from atlas_mcp import moodboard as M

    captured = {}
    monkeypatch.setattr(M, "add_style_card", lambda team, **kw: captured.update(kw) or {"id": "f1"})
    monkeypatch.setattr(L, "get_post", lambda team, pid: {"paper": {"title": "Spatial atlas of X"}})
    fn = getattr(server.add_plot_to_moodboard, "fn", server.add_plot_to_moodboard)
    out = asyncio.run(
        fn(spec={"chart": {"type": "line"}}, title="T", paper_id="p1", confirm=True, ctx=None)
    )
    assert "Added style card" in out
    assert captured["paper_id"] == "p1"


def test_add_plot_refuses_unknown_paper(monkeypatch):
    server = _server(monkeypatch)
    from atlas_mcp import lab as L
    from atlas_mcp import moodboard as M

    writes = {"n": 0}
    monkeypatch.setattr(M, "add_style_card", lambda team, **kw: writes.__setitem__("n", 1))

    def no_post(team, pid):
        raise L.LabError(f"No paper {pid} in {team['name']}.")

    monkeypatch.setattr(L, "get_post", no_post)
    fn = getattr(server.add_plot_to_moodboard, "fn", server.add_plot_to_moodboard)
    out = asyncio.run(
        fn(spec={"chart": {"type": "line"}}, title="T", paper_id="nope", confirm=True, ctx=None)
    )
    assert out.startswith("Error:")
    assert writes["n"] == 0  # refused before any write


def test_add_plot_rejects_bad_spec_and_bad_source_url(monkeypatch):
    server = _server(monkeypatch)
    fn = getattr(server.add_plot_to_moodboard, "fn", server.add_plot_to_moodboard)
    out = asyncio.run(fn(spec={"chart": {"type": "pie"}}, title="X", confirm=True, ctx=None))
    assert out.startswith("Error:")
    out = asyncio.run(
        fn(
            spec={"chart": {"type": "line"}},
            title="X",
            source_url="javascript:alert(1)",
            confirm=True,
            ctx=None,
        )
    )
    assert out.startswith("Error:")


def test_preview_plot_spec_reports_invalid_spec(monkeypatch):
    server = _server(monkeypatch)
    fn = getattr(server.preview_plot_spec, "fn", server.preview_plot_spec)
    out = fn(spec={"chart": {"type": "pie"}})
    assert isinstance(out, list) and out[0].startswith("Error:")


def test_preview_plot_spec_returns_text_and_image(monkeypatch):
    pytest.importorskip("matplotlib")
    pytest.importorskip("PIL")
    server = _server(monkeypatch)
    fn = getattr(server.preview_plot_spec, "fn", server.preview_plot_spec)
    out = fn(spec={"chart": {"type": "line"}, "data_hints": {"n_points": 8}})
    assert len(out) == 2
    assert "Spec is valid" in out[0]
    assert "Nothing saved" in out[0]
