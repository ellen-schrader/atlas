-- author_filter_test.sql — team_authors and the p_author filter on
-- search_papers / search_papers_count (20261010120000_author_filter.sql):
-- counts per author, lab scoping through RLS, exact matching, and the author
-- menu's count agreeing with the filtered result count.
-- Same JWT-claims trick as rls_isolation_test.sql to act as a user.

begin;
select plan(10);

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-00000000000a', 'ada@lab.test', '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-00000000000b', 'bob@lab.test', '{"display_name":"Bob"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-00000000000a', 'Ada'),
    ('00000000-0000-0000-0000-00000000000b', 'Bob')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('33333333-3333-3333-3333-333333333333', 'Lab A', 'authors-lab-a', '00000000-0000-0000-0000-00000000000a'),
    ('44444444-4444-4444-4444-444444444444', 'Lab B', 'authors-lab-b', '00000000-0000-0000-0000-00000000000b');

insert into public.team_members (team_id, user_id, role) values
    ('33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', 'owner'),
    ('44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-00000000000b', 'owner');

insert into public.papers (id, url, url_norm, title, authors, venue) values
    ('10000000-0000-0000-0000-000000000001', 'http://x/1', 'x/1', 'One',   '["Wu","Ali"]', 'Cell'),
    ('10000000-0000-0000-0000-000000000002', 'http://x/2', 'x/2', 'Two',   '["Wu"," "]', 'Nature'),
    ('10000000-0000-0000-0000-000000000003', 'http://x/3', 'x/3', 'Three', '["Ali Khan"]', null),
    -- Lab B only
    ('10000000-0000-0000-0000-000000000004', 'http://x/4', 'x/4', 'Four',  '["Wu","Zed"]', 'Cell');

insert into public.paper_posts (paper_id, team_id, posted_by, tags, source) values
    ('10000000-0000-0000-0000-000000000001', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', '[]', 'web'),
    ('10000000-0000-0000-0000-000000000002', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', '[]', 'web'),
    ('10000000-0000-0000-0000-000000000003', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', '[]', 'web'),
    ('10000000-0000-0000-0000-000000000004', '44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-00000000000b', '[]', 'web');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000a"}';

select results_eq(
    $$ select author, n from public.team_authors('33333333-3333-3333-3333-333333333333') $$,
    $$ values ('Wu'::text, 2), ('Ali'::text, 1), ('Ali Khan'::text, 1) $$,
    'team_authors: most papers first, blank names dropped, other labs'' papers not counted'
);

select is_empty(
    $$ select * from public.team_authors('44444444-4444-4444-4444-444444444444') $$,
    'team_authors: RLS hides another lab''s authors'
);

select is(
    (select count(*)::int from public.search_papers('33333333-3333-3333-3333-333333333333', p_author => 'Wu')),
    2,
    'search_papers: p_author matches any author on the paper'
);

select is(
    public.search_papers_count('33333333-3333-3333-3333-333333333333', p_author => 'Ali'),
    1,
    'search_papers_count: p_author is an exact name match ("Ali" is not "Ali Khan")'
);

select is(
    (select n from public.team_authors('33333333-3333-3333-3333-333333333333') where author = 'Wu'),
    public.search_papers_count('33333333-3333-3333-3333-333333333333', p_author => 'Wu'),
    'team_authors: the author menu''s count equals the filtered result count'
);

select is(
    public.search_papers_count('33333333-3333-3333-3333-333333333333'),
    3,
    'search_papers_count: no author filter leaves the result unchanged'
);

select results_eq(
    $$ select author from public.team_authors('33333333-3333-3333-3333-333333333333', 'ALI') $$,
    $$ values ('Ali'::text), ('Ali Khan'::text) $$,
    'team_authors: p_q matches anywhere in the name, case-insensitively'
);

select is(
    (select count(*)::int from public.team_authors('33333333-3333-3333-3333-333333333333', p_limit => 1)),
    1,
    'team_authors: p_limit pages the list'
);

select is(
    (select count(*)::int from public.team_authors('33333333-3333-3333-3333-333333333333', '%')),
    0,
    'team_authors: p_q is literal, not a LIKE pattern'
);

select is(
    (select count(*)::int from public.team_venues('33333333-3333-3333-3333-333333333333', 'cel')),
    1,
    'team_venues: p_q narrows venues too'
);

select * from finish();
rollback;
