-- 20260713190000_style_cards.sql — style cards: spec-backed synthetic figures.
--
-- A mood-board entry can now be a STYLE CARD: instead of storing someone else's
-- figure image (copyright exposure) or the lab's own unpublished plot
-- (confidentiality exposure), we store a small versioned JSON *spec* of the
-- figure's style — chart form, palette, line styles, axes, typography, and
-- gestalt-level data hints — and render it with synthetic data. The stored
-- image is that render (our own work); the admired original is processed
-- ephemerally at capture time and never persisted. Specs are validated against
-- a closed vocabulary (atlas_mcp/spec.py) and rendered deterministically
-- (atlas_mcp/render.py, RNG seeded from the figure id). See
-- docs/STYLE_CARDS_PLAN.md.
--
-- Everything else reuses the existing figures machinery: the render lives in
-- the private `figures` bucket at the usual `{team_id}/{figure_id}.png` path,
-- width/height feed the masonry, RLS is untouched (the MCP server inserts as
-- the signed-in user), and source_url/license/attribution double as *citation*
-- for the style's inspiration — not as a stored-copy licence.

alter table public.figures
  add column spec jsonb;

comment on column public.figures.spec is
  'Style-card spec (versioned JSON, spec_version 1). Present iff origin = ''style_card'': '
  'the stored image is a synthetic render of this spec; the original figure is never persisted.';

-- Widen the origin vocabulary. The dropped constraint is the auto-named column
-- check from 20260712171000_figure_origin.sql.
alter table public.figures drop constraint figures_origin_check;
alter table public.figures add constraint figures_origin_check
  check (origin in ('own', 'third_party', 'style_card'));

-- A style card always carries its spec; image figures never do.
alter table public.figures add constraint figures_spec_matches_origin
  check ((origin = 'style_card') = (spec is not null));

comment on column public.figures.origin is
  'own = lab''s unpublished work (confidential); third_party = external image, needs '
  'source/licence; style_card = synthetic recreation of `spec` (cite via source_url/attribution).';
