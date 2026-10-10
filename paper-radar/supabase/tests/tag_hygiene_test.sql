-- tag_hygiene_test.sql — normalise_tag / clean_tags / the clean_tags triggers /
-- apply_tag_cleanup / tag_vocabulary (20261010140000_tag_hygiene.sql): one
-- spelling per tag on every write, aliases applied even for a signed-in
-- writer (RLS hides tag_aliases), and the service-only functions locked down.

begin;
select plan(12);

select is(public.normalise_tag('  Spatial  Transcriptomics '), 'spatial-transcriptomics',
    'normalise_tag: lowercase, trimmed, spaces to one hyphen');
select is(public.normalise_tag('single_cell--RNA-seq-'), 'single-cell-rna-seq',
    'normalise_tag: underscores to hyphens, no repeated or trailing hyphens');

insert into public.tag_aliases (alias, canonical) values ('tme', 'tumor-microenvironment');

select is(public.clean_tags('["TME", "tumor microenvironment", "", "Imaging", "imaging"]'),
    '["tumor-microenvironment", "imaging"]'::jsonb,
    'clean_tags: aliases mapped, blanks and repeats dropped, first occurrence order kept');
select is(public.clean_tags('"not an array"'), '[]'::jsonb,
    'clean_tags: a non-array degrades to empty');

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000c1', 'cy@hyg.test', '{"display_name":"Cy"}'::jsonb);
insert into public.profiles (id, display_name) values ('00000000-0000-0000-0000-0000000000c1', 'Cy')
on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('c0000000-0000-0000-0000-0000000000c1', 'Hygiene Lab', 'hygiene-lab', '00000000-0000-0000-0000-0000000000c1');
insert into public.team_members (team_id, user_id, role) values
    ('c0000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000c1', 'owner');

insert into public.papers (id, url, url_norm, title, tags) values
    ('c1000000-0000-0000-0000-000000000001', 'http://h/1', 'h/1', 'One', '["Deep Learning", "TME"]'),
    ('c1000000-0000-0000-0000-000000000002', 'http://h/2', 'h/2', 'Two', '["deep-learning"]');

select is((select tags from public.papers where id = 'c1000000-0000-0000-0000-000000000001'),
    '["deep-learning", "tumor-microenvironment"]'::jsonb,
    'trigger: papers.tags cleaned on insert');

insert into public.paper_posts (paper_id, team_id, posted_by, tags, source) values
    ('c1000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-0000000000c1',
     '00000000-0000-0000-0000-0000000000c1', '[]', 'web');

-- As the signed-in user, the way the web app writes lab tags and follows.
set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000c1"}';

update public.paper_posts set tags = '["My Tag", "tme"]'
 where paper_id = 'c1000000-0000-0000-0000-000000000001';
update public.profiles set interests = '["TME"]' where id = '00000000-0000-0000-0000-0000000000c1';

select is((select tags from public.paper_posts where paper_id = 'c1000000-0000-0000-0000-000000000001'),
    '["my-tag", "tumor-microenvironment"]'::jsonb,
    'trigger: a signed-in user''s lab tags are cleaned and aliased despite RLS on tag_aliases');
select is((select interests from public.profiles where id = '00000000-0000-0000-0000-0000000000c1'),
    '["tumor-microenvironment"]'::jsonb,
    'trigger: followed tags are cleaned and aliased');

select throws_ok($$ select * from public.tag_vocabulary() $$, '42501', null,
    'tag_vocabulary: not callable by a signed-in user (it spans every lab)');
select throws_ok($$ select * from public.apply_tag_cleanup() $$, '42501', null,
    'apply_tag_cleanup: not callable by a signed-in user');

reset role;

-- A merge added later is applied to rows already stored.
insert into public.tag_aliases (alias, canonical) values ('my-tag', 'mine');
select results_eq(
    $$ select tbl, changed from public.apply_tag_cleanup() where tbl = 'paper_posts' $$,
    $$ values ('paper_posts'::text, 1) $$,
    'apply_tag_cleanup: rewrites rows a new alias affects, and only those'
);

select results_eq(
    $$ select tag, n from public.tag_vocabulary(100000)
       where tag in ('deep-learning', 'tumor-microenvironment') $$,
    $$ values ('deep-learning'::text, 2), ('tumor-microenvironment'::text, 1) $$,
    'tag_vocabulary: AI tags counted across papers, most-used first'
);

select is((select count(*)::int from public.tag_vocabulary(1)), 1,
    'tag_vocabulary: p_limit caps the list');

select * from finish();
rollback;
