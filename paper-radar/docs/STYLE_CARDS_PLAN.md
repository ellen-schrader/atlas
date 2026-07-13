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
    from the hash), so **the board shows exactly the approved preview**. That
    determinism is scoped to one version of the renderer + matplotlib; it is not
    a claim that a year-old card re-renders bit-for-bit after either changes
    (layout and glyph rasterisation move). The stored PNG stays the card's
    image. Renders are serialised behind a lock (pyplot's rcParams are
    process-global, and FastMCP runs sync tools on a thread pool) and start from
    matplotlib's defaults, so a developer's own `matplotlibrc` can't change what
    a lab's board looks like. Bounded by the schema (≤8 series, ≤500 points,
    ≤40 sq in, log axes only for line/scatter, one colour per series), 300 dpi.
  - The read path is lenient but never *unchecked*: `spec.for_render` fills
    defaults for fields a stored card predates, while still enforcing every type
    and bound — `figures_update` RLS lets a row's owner PATCH `spec`, so a
    hostile stored spec must not be able to allocate the process to death.
  - The badge is enforced in the DATABASE, not in React: a trigger freezes a
    style card's `spec`, `storage_path` and `origin`, so nobody can repoint a
    card's image at an uploaded copy of the very figure the badge says was never
    copied (RLS alone would have allowed exactly that via one PostgREST PATCH).
  - Spec v1 vocabulary: six chart types; per-series `line_width` / `dash` /
    `marker` / `drawstyle` (`step` is what makes a Kaplan–Meier curve or a CDF
    read as itself — a smooth line through the same points does not, and the
    synthetic data is made monotone so a survival staircase never steps back up).
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

## Spec v2 — composite figures (BUILT)

The v1 spec describes **one panel**. The figures this lab actually publishes are
often composites: a heatmap of phenotype × marker, a **percent-stacked bar** of
each phenotype's composition, and a **count plot** of its abundance — three
panels sharing one row axis, where **each row is a cell phenotype**. v1 cannot
express that, and the gap is not "more fields": it's that a composite has
**shared structure across panels**, which a flat single-chart spec has nowhere
to put.

What v2 has to add, in rough order of how load-bearing it is:

1. **A shared categorical domain — the keystone.** Name the row axis once
   (`domains: {phenotype: {n_categories: 12, order: "clustered"}}`) and let each
   panel bind to it (`rows: "$phenotype"`). Without this, every panel would
   generate its own synthetic categories and the rows wouldn't correspond —
   the figure would be nonsense. The domain also carries the **row order rule**
   (`clustered` / `by_value` / `fixed`), which is itself a style fact: these
   figures are usually sorted by abundance or by a dendrogram.
2. **Named semantic palettes, not one flat cycle.** A composite has *several*
   colour meanings at once: the heatmap's scale, the stacked bar's category
   colours (region / sample / compartment), and any annotation strip. v1's
   single `palette` can't keep "colour follows the entity" true across panels.
   v2 needs `palettes: {region: [...], lineage: [...]}` with panels referencing
   a palette **by name**, so the same category is the same colour everywhere
   (and in the legend).
3. **A layout block**: `layout: {rows, cols, width_ratios, height_ratios, gap,
   share_y: "$phenotype"}` → a matplotlib GridSpec. Width ratios are a genuine
   style fact of these figures (a wide heatmap, a narrow bar strip).
4. **`panels: [...]`** — each entry a v1-shaped chart spec plus `kind`, grid
   `position`/`span`, and per-panel `ticks`/`labels` visibility. "Row labels on
   the leftmost panel only, ticks hidden elsewhere" is exactly the kind of thing
   that makes a composite read as one figure rather than three glued together.
5. **New panel kinds** the composite needs: `stacked_bar` (with
   `mode: grouped | stacked | percent`), `annotation_track` (the categorical
   colour strips beside a heatmap), and `dendrogram`. Plus `orientation:
   horizontal|vertical` — a count plot on a row axis is horizontal, which v1's
   bar renderer cannot do.
6. **Colour-scale kind on the heatmap**: `sequential` vs `diverging` with a
   neutral midpoint. A z-scored expression heatmap is diverging around 0, and
   rendering it with v1's single-hue ramp gets the look materially wrong.
7. **A colorbar block** (`show`, `loc`, `label`) and **figure-level legend
   placement** (outside right / below) — in a composite the legend usually
   belongs to the figure, not to a panel.
8. **Per-panel `data_hints`, plus distribution shape for the new kinds**:
   composition needs `even | dominant_one | long_tail`, counts need
   `uniform | long_tail`. Still shape-level only.

### Two constraints that get *sharper* for composites, not looser

- **Row labels are the leak vector.** For a composite, the natural instinct is
  to write the real phenotype names into the spec. For an `own` (unpublished)
  figure, the *set and ordering* of phenotypes can itself be the finding.
  Default to synthetic labels (`Phenotype A…N`); allow real `category_labels`
  only on explicit opt-in, and warn on `own` figures. Likewise the composition
  fractions and counts **are** the result in most of these papers — they must
  stay synthetic, which is what keeps `data_hints` shape-level by design.
- **Composition-cloning risk.** A faithful panel-by-panel reproduction of a
  specific published composite edges toward copying its "selection and
  arrangement" — the one copyright flank a style card is supposed to close. So
  v2 should offer a vocabulary of common layout *idioms*, and the capture copy
  should steer toward "a heatmap with a composition bar beside it" rather than
  "panel-for-panel, this exact figure".

### Sketch

```json
{
  "spec_version": 2,
  "domains": { "phenotype": { "n_categories": 12, "order": "clustered" } },
  "palettes": { "region": ["#0f8f8b", "#b4791a", "#6a5cd8", "#c23c86"] },
  "layout":  { "rows": 1, "cols": 3, "width_ratios": [3, 1, 1], "gap": 0.04,
               "share_y": "$phenotype" },
  "panels": [
    { "kind": "heatmap", "rows": "$phenotype", "position": [0, 0],
      "scale": { "kind": "diverging", "midpoint": 0 },
      "colorbar": { "show": true, "loc": "right", "label": "z-score" },
      "labels": { "rows": true } },
    { "kind": "stacked_bar", "rows": "$phenotype", "position": [0, 1],
      "mode": "percent", "orientation": "horizontal", "palette": "$region",
      "labels": { "rows": false },
      "data_hints": { "composition": "dominant_one" } },
    { "kind": "bar", "rows": "$phenotype", "position": [0, 2],
      "orientation": "horizontal", "axes": { "x_scale": "log" },
      "labels": { "rows": false },
      "data_hints": { "distribution": "long_tail" } }
  ],
  "legend": { "mode": "figure", "loc": "below" },
  "notes": "Rows ordered by clustering; ticks only on the heatmap; hairline panel gaps."
}
```

### What shipped

`atlas_mcp/composite.py`, routed from `validate_spec`/`render` on `spec_version`
(v1 specs already on the board keep the v1 path untouched, forever).

The load-bearing implementation decision, and the one the design under-stated:
panels must share a synthetic **dataset**, not merely an axis.

    one domain  ->  one synthetic dataset  ->  every panel projects it

`_Domain` draws the abundance, the composition and the expression matrix once,
decides the row order once, and hands the same rows to every bound panel. If each
panel generated its own categories, row 3 of the heatmap would not be row 3 of
the composition bar — the figure would be a lie, and it would *look* fine. That
invariant is what `test_every_panel_sees_the_same_rows_in_the_same_order` pins,
because no rendering test can catch it.

Also true of the implementation:

- The expression matrix is built from a few latent programmes, so the rows
  genuinely cluster — otherwise `order: clustered` and the dendrogram would be
  decoration over noise.
- Row panels are aligned by pinning identical limits, NOT by matplotlib's
  `sharey`: shared axes share one tick locator, so the panel that hides its row
  ticks would wipe the labels off the panel that shows them.
- Composites lay out with matplotlib's `constrained` engine and put the figure
  legend `outside`; `tight_layout` cannot place a colorbar plus a figure legend
  (it says so, and it is right).
- The CVD verdict checks each named *categorical* palette and skips a heatmap's
  ramp — a pairwise check says nothing about a continuous scale.
- Real category labels are opt-in and echoed in the confirm preview, so a human
  approving the write sees exactly which phenotype names would be stored.

## Backlog

- **Convert existing `third_party` figures to style cards** — a "Convert to
  style card" action that runs the P3 flow on the stored image and then deletes
  the original object. This is what actually *retires* the existing legal
  exposure; P1 only stops accruing new exposure.
- `?figure=` deep link in `get_figure_image` output (parallel to `?paper=`).
- `figures.embedding` for multi-modal similarity search (noted since the
  mood_board migration).
- Per-user daily cap on MCP card creation, if abuse ever appears.
