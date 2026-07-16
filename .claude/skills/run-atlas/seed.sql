-- Seed a lab for local Atlas runs. Replace __UID__ with the auth.users id of the
-- user you created via the admin API (see SKILL.md), e.g.
--   sed "s/__UID__/$uid/g" seed.sql > /tmp/seed.sql
--
-- Idempotent: safe to re-run.

\set uid '__UID__'

-- profiles.id FKs auth.users; team_members FKs profiles, so this must come first.
insert into public.profiles (id, display_name)
values (:'uid', 'Ellen')
on conflict (id) do update set display_name = excluded.display_name;

insert into public.teams (id, name, slug, created_by)
values ('11111111-1111-1111-1111-111111111111', 'TME Lab', 'tme-lab', :'uid')
on conflict (slug) do nothing;

insert into public.team_members (team_id, user_id, role)
values ('11111111-1111-1111-1111-111111111111', :'uid', 'owner')
on conflict do nothing;

-- Papers are global and deduped on url_norm (not url). No embeddings: without a
-- VOYAGE_API_KEY they can't be computed, so Map/Overview stays empty and
-- /recommendations returns cold_start:true — usually what you want to inspect.
insert into public.papers (id, url, url_norm, title, authors, abstract, venue, year, tags) values
 ('aaaaaaaa-0000-0000-0000-000000000001',
  'https://doi.org/10.1038/s41586-025-01', 'nature-dcis-clonal',
  'Spatially resolved clonal architecture in ductal carcinoma in situ',
  '["R. Patel","D. Werb"]',
  'Spatial profiling of DCIS reveals clonal neighbourhoods that predict invasion.',
  'Nature', 2025, '["spatial-omics","dcis"]'),
 ('aaaaaaaa-0000-0000-0000-000000000002',
  'https://doi.org/10.1016/j.cell.2025.02', 'cell-imc-front',
  'Imaging mass cytometry of the invasive front in triple-negative breast cancer',
  '["M. Chen","A. Ali"]',
  'IMC of the invasive front identifies myeloid niches at the tumour boundary.',
  'Cell', 2025, '["imaging","immune"]'),
 ('aaaaaaaa-0000-0000-0000-000000000003',
  'https://biorxiv.org/10.1101/2026.01.03', 'biorxiv-stromal-atlas',
  'A single-cell atlas of stromal remodelling during tumour progression',
  '["L. Nguyen"]',
  'Single-cell atlas charting stromal remodelling across progression stages.',
  'bioRxiv', 2026, '["single-cell","stroma"]')
on conflict (url_norm) do nothing;

-- paper_posts is the visibility boundary: a paper is only in a lab once posted.
insert into public.paper_posts (paper_id, team_id, posted_by, source)
select id, '11111111-1111-1111-1111-111111111111', :'uid', 'web' from public.papers
on conflict (paper_id, team_id) do nothing;

-- One 🤔 (sceptical, low taste weight) and one 👍 (endorsement) so both
-- reaction-tooltip branches are exercised in the UI.
insert into public.reactions (paper_id, team_id, user_id, emoji) values
 ('aaaaaaaa-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', :'uid', '🤔'),
 ('aaaaaaaa-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', :'uid', '👍')
on conflict do nothing;

select (select count(*) from public.papers)      as papers,
       (select count(*) from public.paper_posts) as posts,
       (select count(*) from public.reactions)   as reactions;
