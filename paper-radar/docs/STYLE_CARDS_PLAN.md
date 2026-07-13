# Style cards — keep the look, not the copy

Goal: stop storing third-party figure images (copyright exposure, esp. under
German/EU law with no fair use) and avoid putting confidential own plots on the
board. Instead a mood-board entry can be a **style card**: a validated JSON
**spec** of the figure's style (chart form, palette, line styles, axes, legend,
typography, gestalt-level data hints) plus a PNG **synthetic render** of that
spec. The admired original is processed ephemerally at capture time and never
persisted; the stored render is our own work. `source_url`/`attribution` double
as scholarly citation of the inspiration.

Extends the mood board from `docs/MOODBOARD_MCP_PLAN.md` (M1–M3, merged).
Design report (mock-ups, spec v1, threat model):
https://claude.ai/code/artifact/a42e0cc4-b28a-448f-8422-69c53b09756a

## Design constraints (from the legal analysis; not legal advice)

- Store **style facts**, never expression: no annotation geometry, no exact
  ticks, no text from the original beyond free-form `notes`. The recreation
  echoes the gestalt, it does not clone the composition.
- Synthetic data only — `data_hints` carries shape (`n_series`, `n_points`,
  `trend`, `noise`), never values. Also closes the GDPR/confidentiality flank
  for own figures.
- Free text (`title`, `notes`) is the remaining leak vector: capture copy
  nudges toward style language, and the read path frames it as untrusted.

## Phases

- **P1 — done (this branch).** Spec v1 + renderer + MCP tools + minimal web.
  - Migration `20260713190000_style_cards.sql`: `figures.spec jsonb`,
    `origin` gains `'style_card'`, check `(origin='style_card') = (spec is not null)`.
    RLS untouched (the MCP server inserts as the signed-in user).
  - `atlas_mcp/spec.py`: hand-rolled, closed-vocabulary validation
    (`additionalProperties`-style rejection everywhere); friendly fix-it errors;
    `spec_seed` for stable previews. Stdlib-only on purpose.
  - `atlas_mcp/render.py`: matplotlib/Agg, deterministic — preview and stored
    card both seed from `spec_seed(spec)` (the server's `cvd` stamp is excluded
    from the hash), so the board shows exactly the approved preview and the
    stored row reproduces it byte-identically. Bounded by the schema (≤8
    series, ≤500 points, log axes only for line/scatter, palette ≥ series),
    300 dpi.
  - MCP: `preview_plot_spec` (validate + render, writes nothing) and
    `add_plot_to_moodboard` (previews by default; `confirm=true` + elicitation
    gate, exactly the `post_paper` pattern; `@audited`; CVD verdict stamped
    into the spec at save time). First write path to the board — content risk
    is structurally capped because the server accepts a spec, never image bytes.
    The inspiration is citable three ways: `source_url` (e.g. a DOI link),
    `attribution` (display credit), and `paper_id` (a lab paper, validated for
    membership; renders as the linked-paper chip on the board).
  - Web (minimal): "Style card" badge on the card, provenance panel + spec
    viewer (copy JSON) in the detail modal, image-replacement and origin toggle
    disabled for style cards.
- **P2 — next.** Web capture & editing: spec editor with live re-render in the
  upload dialog (third origin option), "copy as `.mplstyle`", and a spec-aware
  `get_moodboard_style` that reads stored specs before falling back to pixel
  palette extraction.
- **P3 — then.** Assisted capture from the web app: drop an image into the
  dialog → FastAPI endpoint (has the `anthropic` dep; holds the image in
  memory only) → Claude vision emits the spec (structured output) → validate +
  render with the same modules → side-by-side preview → browser saves under its
  own auth (RLS unchanged); the original is discarded. Prereqs: lift
  `spec.py`/`render.py` into a module both `atlas_mcp` and `api/` import, and a
  plain consent line (the image goes to Anthropic — matters for own figures).

## Backlog

- **Convert existing `third_party` figures to style cards** — a "Convert to
  style card" action that runs the P3 flow on the stored image and then deletes
  the original object. This is what actually *retires* the existing legal
  exposure; P1 only stops accruing new exposure.
- `?figure=` deep link in `get_figure_image` output (parallel to `?paper=`).
- `figures.embedding` for multi-modal similarity search (noted since the
  mood_board migration).
- Per-user daily cap on MCP card creation, if abuse ever appears.
