-- spelling_variants_test.sql — British/American spelling in search
-- (20261010180000_spelling_variants.sql + the VarCon pairs in
-- 20261010180100_spelling_variants_data.sql): us_spelling, the either-spelling
-- prefix_tsquery, the filter menus' match, ?tag= in either spelling, stored
-- tags left as they are, and the false matches pattern rules produced
-- (colour -> colorectal, centred -> centerd, metabolism -> metabolizm).

begin;
select plan(37);

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
select is(public.us_spelling('ret-fusion cre-lox tae sae prev gre'),
          'ret-fusion cre-lox tae sae prev gre',
          'us: gene names and abbreviations are not touched (no unverified fragment pairs)');
select is(public.us_spelling('tumourigenesis hypoglycaemia lymphoedema leucocyte oesophagitis'),
          'tumorigenesis hypoglycemia lymphedema leukocyte esophagitis',
          'us: biomedical words VarCon lacks or never verified');
select is(public.us_spelling('formulae trabeculae notre jours archaea'),
          'formulae trabeculae notre jours archaea',
          'us: Latin plurals and short unverified fragments are not in the list');
select is(public.spelling_forms('tumour-microenvironment'),
          array['tumour-microenvironment', 'tumor-microenvironment'], 'forms: a tag in both spellings, as given first');
select is((public.spelling_forms('colour-colour-colour-colour-colour-colour-colour'))[1],
          'colour-colour-colour-colour-colour-colour-colour', 'forms: past the cap, the tag as given is kept');
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
select ok(to_tsvector('english', 'Tumorigenesis in mice') @@ public.prefix_tsquery('tumour'),
          'search: "tumour" finds the American form of a longer word (tumorigenesis)');
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

update public.profiles set profile_md = 'Tumour Microenvironment and signalling'
 where id = '00000000-0000-0000-0000-0000000000e1';
select is((select public.profile_md_us(p) from public.profiles p where id = '00000000-0000-0000-0000-0000000000e1'),
          'tumor microenvironment and signaling', 'profile_md_us: the profile in American spelling');

select is((select tags from public.papers where id = 'e1000000-0000-0000-0000-000000000001'),
    '["tumour-microenvironment", "haematopoiesis", "colorectal-cancer", "patient-centred-care"]'::jsonb,
    'clean_tags: stored tags keep their spelling (the list only widens searches)');

insert into public.paper_posts (paper_id, team_id, posted_by, tags, source) values
    ('e1000000-0000-0000-0000-000000000001', 'e0000000-0000-0000-0000-0000000000e1',
     '00000000-0000-0000-0000-0000000000e1', '[]', 'web');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000e1"}';

select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'tumour') $$,
    $$ values ('tumour-microenvironment'::text) $$,
    'menus: "tumour" finds tumour-microenvironment');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'tumor micro') $$,
    $$ values ('tumour-microenvironment'::text) $$,
    'menus: "tumor" finds the UK-spelled tag; a half-typed second word still matches');
select is_empty(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'colour') $$,
    'menus: "colour" does not find colorectal-cancer');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'environment') $$,
    $$ values ('tumour-microenvironment'::text) $$,
    'menus: the old substring match still works');
select is_empty(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', '--') $$,
    'menus: a query with no letters does not match every tag');
select results_eq(
    $$ select venue from public.team_venues('e0000000-0000-0000-0000-0000000000e1', 'pediatric') $$,
    $$ values ('Paediatric Research'::text) $$,
    'menus: "pediatric" finds Paediatric Research (shown as stored)');
select is(
    (select count(*)::int from public.search_papers('e0000000-0000-0000-0000-0000000000e1', 'tumor immune')),
    1,
    'search_papers: "tumor immune" finds the UK-spelled abstract');

select is(
    (select count(*)::int from public.search_papers('e0000000-0000-0000-0000-0000000000e1', '', 'tumour-microenvironment')),
    1,
    'search_papers: ?tag= in the stored spelling');
select is(
    (select count(*)::int from public.search_papers('e0000000-0000-0000-0000-0000000000e1', '', 'Tumor Microenvironment')),
    1,
    'search_papers: ?tag= in the other spelling finds the paper too');
select is(
    public.search_papers_count('e0000000-0000-0000-0000-0000000000e1', '', 'tumor-microenvironment'),
    1,
    'search_papers_count: agrees with the list for the other spelling');
select is(
    (select count(*)::int from public.search_papers('e0000000-0000-0000-0000-0000000000e1', '', 'colorectal')),
    0,
    'search_papers: ?tag= is still a whole tag, not a prefix');

-- A US-tagged paper, for the half-typed and short-word menu matches.
reset role;
insert into public.papers (id, url, url_norm, title, tags) values
    ('e1000000-0000-0000-0000-000000000002', 'http://s/2', 's/2', 'Two',
     '["tumorigenesis", "t-cell-exhaustion", "tissue-imaging"]');
insert into public.paper_posts (paper_id, team_id, posted_by, tags, source) values
    ('e1000000-0000-0000-0000-000000000002', 'e0000000-0000-0000-0000-0000000000e1',
     '00000000-0000-0000-0000-0000000000e1', '[]', 'web');
set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000e1"}';

select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'tumou') order by 1 $$,
    $$ values ('tumorigenesis'::text), ('tumour-microenvironment') $$,
    'menus: a half-typed British word finds US tags (and still the UK one)');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 'haemato') $$,
    $$ values ('haematopoiesis'::text) $$,
    'menus: half-typed, as stored');
select results_eq(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 't exhaus') $$,
    $$ values ('t-cell-exhaustion'::text) $$,
    'menus: a one-letter word matches only the whole word "t" (not tumour-, tissue-)');
select is_empty(
    $$ select tag from public.team_tags('e0000000-0000-0000-0000-0000000000e1', 't micro') $$,
    'menus: "t" no longer matches as the start of tumour-microenvironment');
reset role;

select * from finish();
rollback;
