-- 20260712170000_figure_origin.sql — provenance on mood-board figures.
--
-- A figure is either the lab's OWN (unpublished) work or a THIRD-PARTY image
-- (e.g. a published figure kept for inspiration). The distinction drives how the
-- MCP tools treat it (docs/MOODBOARD_MCP_PLAN.md):
--   * own          → the lab holds the rights; treat as confidential unpublished work.
--   * third_party  → record where it came from + its licence, so Claude attributes
--                    the source and derives *style* rather than reproducing the figure.
--
-- `license` for third-party figures may be prefilled from the linked paper's DOI
-- (OpenAlex/Crossref) as an advisory hint, then confirmed by the uploader. Own
-- figures leave source_url/license/attribution null.

alter table public.figures
  add column origin      text not null default 'own'
             check (origin in ('own', 'third_party')),
  add column source_url  text,
  add column license     text,
  add column attribution text;

comment on column public.figures.origin is
  'own = lab''s unpublished work (confidential); third_party = external image, needs source/licence.';
