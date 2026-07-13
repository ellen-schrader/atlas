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
-- (atlas_mcp/render.py) with the RNG seeded from the SPEC'S CONTENT
-- (spec.spec_seed) — not from the figure id, which does not exist yet when the
-- user approves the preview. That is what makes the board image the very image
-- they approved, and lets the stored row reproduce it. See
-- docs/STYLE_CARDS_PLAN.md.
--
-- Everything else reuses the existing figures machinery: the render lives in
-- the private `figures` bucket at the usual `{team_id}/{figure_id}.png` path,
-- width/height feed the masonry, RLS is untouched (the MCP server inserts as
-- the signed-in user), and source_url/attribution are *citation* for the
-- style's inspiration — not a licence for a stored copy.

alter table public.figures
  add column spec jsonb;

comment on column public.figures.spec is
  'Style-card spec (versioned JSON, spec_version 1). Present iff origin = ''style_card'': '
  'the stored image is a synthetic render of this spec; the original figure is never persisted.';

-- Widen the origin vocabulary. `if exists` because the dropped constraint is the
-- AUTO-NAMED column check from 20260712171000_figure_origin.sql — a squashed
-- baseline or a repaired history could carry a different name, and this
-- migration must not abort on it.
alter table public.figures drop constraint if exists figures_origin_check;
alter table public.figures add constraint figures_origin_check
  check (origin in ('own', 'third_party', 'style_card'));

-- A style card always carries its spec; image figures never do. (`spec` must be
-- a real object, not the JSON literal `null`, which `is not null` would pass.)
alter table public.figures add constraint figures_spec_matches_origin
  check ((origin = 'style_card') = (spec is not null and jsonb_typeof(spec) = 'object'));

comment on column public.figures.origin is
  'own = lab''s unpublished work (confidential); third_party = external image, needs '
  'source/licence; style_card = synthetic recreation of `spec` (cite via source_url/attribution).';

-- === the badge has to be true ==============================================
-- A style card's image is a synthetic render OF ITS SPEC, and both the board
-- badge and the MCP read path assert that to the reader: "a synthetic
-- recreation; the original figure was never copied."
--
-- Nothing below the browser was holding that up. `figures_update` (RLS, see
-- 20260712120000_mood_board.sql) lets a row's owner UPDATE any column of their
-- own row, and the storage policies let any lab member PUT bytes into the
-- bucket. So one PostgREST PATCH could repoint `storage_path` at an uploaded
-- copy of the very figure the card claims not to contain — under a badge that
-- denies it. A React guard is an affordance, not an invariant.
--
-- So: on a style card, the fields that bind the image to the spec are immutable.
-- Re-render by creating a new card; edit the title/caption/category/citation
-- freely. (A plain image figure is unaffected — this only fires for style cards.)
create or replace function public.figures_style_card_is_immutable()
returns trigger
language plpgsql
as $$
begin
    if old.origin = 'style_card' then
        if new.origin is distinct from old.origin then
            raise exception 'A style card cannot change origin (create a new figure instead).';
        end if;
        if new.spec is distinct from old.spec then
            raise exception 'A style card''s spec is immutable — its image is a render of it.';
        end if;
        if new.storage_path is distinct from old.storage_path then
            raise exception 'A style card''s image is a render of its spec and cannot be replaced.';
        end if;
    elsif new.origin = 'style_card' then
        -- and an image figure cannot be relabelled INTO a style card, which would
        -- put a real third-party image behind the "never copied" badge.
        raise exception 'An uploaded image cannot become a style card.';
    end if;
    return new;
end;
$$;

create trigger figures_style_card_immutable
    before update on public.figures
    for each row
    execute function public.figures_style_card_is_immutable();
