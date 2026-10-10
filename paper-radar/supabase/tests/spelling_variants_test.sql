-- spelling_variants_test.sql — us_spelling / uk_spelling, the either-spelling
-- prefix_tsquery, the filter menus' spelling-blind match, and tags folded to US
-- spelling on write (20261010180000_spelling_variants.sql).

begin;
select plan(19);

-- === the rules ==============================================================
select is(public.us_spelling('tumour-microenvironment'), 'tumor-microenvironment', 'us: tumour');
select is(public.us_spelling('haematological'), 'hematological', 'us: haem- at word start');
select is(public.us_spelling('leukaemia oesophageal oestrogen'), 'leukemia esophageal estrogen', 'us: ae/oe');
select is(public.us_spelling('signalling characterisation randomised'), 'signaling characterization randomized', 'us: doubled l and -ise list');
select is(public.us_spelling('noise precise raised analysis programmed imaging'),
          'noise precise raised analysis programmed imaging',
          'us: look-alikes are left alone (noise, precise, raised, analysis, programmed, imaging)');
select is(public.us_spelling('tumour-metabolism organism specialist metabolised organisation'),
          'tumor-metabolism organism specialist metabolized organization',
          'us: the -ise list only touches real -ise endings (metabolism, organism, specialist stay)');
select is(public.uk_spelling('tumor hematopoietic signaling'), 'tumour haematopoietic signalling', 'uk: the reverse direction');

-- === keyword search matches either spelling =================================
select ok(to_tsvector('english', 'Tumor-infiltrating lymphocytes') @@ public.prefix_tsquery('tumour'),
          'prefix_tsquery: "tumour" finds a US-spelled abstract');
select ok(to_tsvector('english', 'The tumour microenvironment') @@ public.prefix_tsquery('tumor'),
          'prefix_tsquery: "tumor" finds a UK-spelled abstract');
select ok(to_tsvector('english', 'hematological malignancies') @@ public.prefix_tsquery('haematological'),
          'prefix_tsquery: haematological <-> hematological');
select ok(to_tsvector('english', 'Wnt signalling in organoids') @@ public.prefix_tsquery('signaling organoid'),
          'prefix_tsquery: every word may use its own spelling');
select ok(not (to_tsvector('english', 'raised levels') @@ public.prefix_tsquery('noise')),
          'prefix_tsquery: no false variants');
select is(public.prefix_tsquery('fibro')::text, to_tsquery('english', 'fibro:*')::text, 'prefix_tsquery: a word with no variant gives the same query as before');

-- === filter menus and tags ==================================================
insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000e1', 'eve@spell.test', '{"display_name":"Eve"}'::jsonb);
insert into public.profiles (id, display_name) values ('00000000-0000-0000-0000-0000000000e1', 'Eve')
on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('e0000000-0000-0000-0000-0000000000e1', 'Spelling Lab', 'spelling-lab', '00000000-0000-0000-0000-0000000000e1');
insert into public.team_members (team_id, user_id, role) values
    ('e0000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000e1', 'owner');

insert into public.papers (id, url, url_norm, title, abstract, tags, venue) values
    ('e1000000-0000-0000-0000-000000000001', 'http://s/1', 's/1', 'One',
     'The tumour immune landscape in children.',
     '["Tumour Microenvironment", "haematopoiesis", "imaging"]', 'Paediatric Research');

select is((select tags from public.papers where id = 'e1000000-0000-0000-0000-000000000001'),
    '["tumor-microenvironment", "hematopoiesis", "imaging"]'::jsonb,
    'clean_tags: tags are stored in US spelling');

insert into public.paper_posts (paper_id, team_id, posted_by, tags, source) values
    ('e1000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-0000000000e1',
     '00000000-0000-0000-0000-0000000000e1', '[]', 'web');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000e1"}';

select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'tumour') $$,
    $$ values ('tumor-microenvironment'::text) $$,
    'team_tags: "tumour" finds tumor-microenvironment');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'Haemato') $$,
    $$ values ('hematopoiesis'::text) $$,
    'team_tags: case and spelling blind');
select results_eq(
    $$ select venue from public.team_venues('e0000000-0000-0000-0000-0000000000e1', 'pediatric') $$,
    $$ values ('Paediatric Research'::text) $$,
    'team_venues: "pediatric" finds Paediatric Research (the name is shown as stored)');

update public.paper_posts set tags = '["Tumour Biology"]'
 where paper_id = 'e1000000-0000-0000-0000-000000000001';
select is((select tags from public.paper_posts where paper_id = 'e1000000-0000-0000-0000-000000000001'),
    '["tumor-biology"]'::jsonb,
    'clean_tags: a lab tag typed in UK spelling is stored in US spelling');

select is(
    (select count(*)::int from public.search_papers('e0000000-0000-0000-0000-0000000000e1', 'tumor immune')),
    1,
    'search_papers: "tumor immune" finds the UK-spelled abstract'
);

reset role;
select * from finish();
rollback;
