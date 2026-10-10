-- spelling_variants_test.sql — whole-word British/American spelling
-- (20261010180000_spelling_variants.sql + the VarCon pairs in
-- 20261010180100_spelling_variants_data.sql): us_spelling, the either-spelling
-- prefix_tsquery, the filter menus' match, tags folded to US spelling, and the
-- false matches pattern rules produced (colour -> colorectal, centred ->
-- centerd, metabolism -> metabolizm).

begin;
select plan(25);

-- === the word list ==========================================================
select is(public.us_spelling('tumour-microenvironment'), 'tumor-microenvironment', 'us: tumour');
select is(public.us_spelling('haematopoietic oesophageal leukaemia foetal'),
          'hematopoietic esophageal leukemia fetal', 'us: ae/oe words, incl. a common British variant (foetal)');
select is(public.us_spelling('patient-centred-care'), 'patient-centered-care', 'us: centred -> centered, not centerd');
select is(public.us_spelling('signalling characterisation randomised'),
          'signaling characterization randomized', 'us: doubled l and -ise');
select is(public.us_spelling('metabolism organism specialist analyses noise colorectal imaging'),
          'metabolism organism specialist analyses noise colorectal imaging',
          'us: words that only look British are left alone');
select results_eq($$ select * from public.spelling_alternatives('tumor') order by 1 $$,
                  $$ values ('tumour'::text) $$, 'alternatives: US -> UK');
select results_eq($$ select * from public.spelling_alternatives('tumour') order by 1 $$,
                  $$ values ('tumor'::text) $$, 'alternatives: UK -> US');

-- === keyword search ==========================================================
select ok(to_tsvector('english', 'Tumor-infiltrating lymphocytes') @@ public.prefix_tsquery('tumour'),
          'search: "tumour" finds a US-spelled abstract');
select ok(to_tsvector('english', 'The tumour microenvironment') @@ public.prefix_tsquery('tumor'),
          'search: "tumor" finds a UK-spelled abstract');
select ok(to_tsvector('english', 'Tumours of the breast') @@ public.prefix_tsquery('tumors'),
          'search: plurals too');
select ok(to_tsvector('english', 'Wnt signalling in organoids') @@ public.prefix_tsquery('signaling organoid'),
          'search: each word may use its own spelling; the typed word keeps its prefix match');
select ok(not (to_tsvector('english', 'Colorectal cancer screening') @@ public.prefix_tsquery('colour')),
          'search: "colour" does not match colorectal (the variant is a whole word)');
select ok(not (to_tsvector('english', 'Laboratory protocols') @@ public.prefix_tsquery('labour')),
          'search: "labour" does not match laboratory');
select is(public.prefix_tsquery('fibroblast')::text, to_tsquery('english', 'fibroblast:*')::text,
          'search: a word with no variant gives the same query as before');

-- === filter menus and tags ===================================================
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
     '["Tumour Microenvironment", "haematopoiesis", "colorectal-cancer", "patient-centred-care"]',
     'Paediatric Research');

select is((select tags from public.papers where id = 'e1000000-0000-0000-0000-000000000001'),
    '["tumor-microenvironment", "hematopoiesis", "colorectal-cancer", "patient-centered-care"]'::jsonb,
    'clean_tags: tags are stored in US spelling, word by word');

insert into public.paper_posts (paper_id, team_id, posted_by, tags, source) values
    ('e1000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-0000000000e1',
     '00000000-0000-0000-0000-0000000000e1', '[]', 'web');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000e1"}';

select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'tumour') $$,
    $$ values ('tumor-microenvironment'::text) $$,
    'menus: "tumour" finds tumor-microenvironment');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'tumour micro') $$,
    $$ values ('tumor-microenvironment'::text) $$,
    'menus: a half-typed second word still matches');
select is_empty(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'colour') $$,
    'menus: "colour" does not find colorectal-cancer');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'environment') $$,
    $$ values ('tumor-microenvironment'::text) $$,
    'menus: the old substring match still works');
select results_eq(
    $$ select venue from public.team_venues('e0000000-0000-0000-0000-0000000000e1', 'pediatric') $$,
    $$ values ('Paediatric Research'::text) $$,
    'menus: "pediatric" finds Paediatric Research (shown as stored)');
select is(
    (select count(*)::int from public.search_papers('e0000000-0000-0000-0000-0000000000e1', 'tumor immune')),
    1,
    'search_papers: "tumor immune" finds the UK-spelled abstract');

update public.paper_posts set tags = '["Tumour Biology"]'
 where paper_id = 'e1000000-0000-0000-0000-000000000001';
select is((select tags from public.paper_posts where paper_id = 'e1000000-0000-0000-0000-000000000001'),
    '["tumor-biology"]'::jsonb,
    'clean_tags: a lab tag typed in UK spelling is stored in US spelling');

select throws_ok($$ select * from public.clean_tag_map(array['x']) $$, '42501', null,
    'clean_tag_map: service role only');
reset role;

select results_eq(
    $$ select raw, cleaned from public.clean_tag_map(array['Tumour Biology', 'imaging']) $$,
    $$ values ('Tumour Biology'::text, 'tumor-biology'::text), ('imaging', 'imaging') $$,
    'clean_tag_map: what each raw tag becomes when stored');

select throws_ok(
    $$ insert into public.tag_aliases (alias, canonical) values ('anti-tumour-immunity', 'antitumor-immunity') $$,
    '23514', null,
    'tag_aliases: a UK-spelled alias is refused (it could never match)');

select * from finish();
rollback;
