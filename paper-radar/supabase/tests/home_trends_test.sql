-- home_trends_test.sql — trending_tags / trending_authors / tag_volume
-- (20261008120000_home_trends.sql): the 30-day vs previous-30-day windows, the
-- "lab tags win over paper tags" rule, lab scoping through RLS, zero-filled
-- weeks, and the ?tag= filter in search_papers agreeing with Trending.
-- Same JWT-claims trick as rls_isolation_test.sql to act as a user.

begin;
select plan(12);

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-00000000000a', 'ada@lab.test', '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-00000000000b', 'bob@lab.test', '{"display_name":"Bob"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-00000000000a', 'Ada'),
    ('00000000-0000-0000-0000-00000000000b', 'Bob')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('33333333-3333-3333-3333-333333333333', 'Lab A', 'trends-lab-a', '00000000-0000-0000-0000-00000000000a'),
    ('44444444-4444-4444-4444-444444444444', 'Lab B', 'trends-lab-b', '00000000-0000-0000-0000-00000000000b');

insert into public.team_members (team_id, user_id, role) values
    ('33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', 'owner'),
    ('44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-00000000000b', 'owner');

insert into public.papers (id, url, url_norm, title, authors, tags) values
    -- current window
    ('10000000-0000-0000-0000-000000000001', 'http://x/1', 'x/1', 'One',   '["Wu","Ali"]', '["spatial","imaging"]'),
    ('10000000-0000-0000-0000-000000000002', 'http://x/2', 'x/2', 'Two',   '["Wu"]',       '["spatial"]'),
    -- has lab tags on its post: its paper tag "ignored" must NOT count
    ('10000000-0000-0000-0000-000000000003', 'http://x/3', 'x/3', 'Three', '["Ali"]',      '["ignored"]'),
    -- previous window
    ('10000000-0000-0000-0000-000000000004', 'http://x/4', 'x/4', 'Four',  '["Wu"]',       '["imaging"]'),
    ('10000000-0000-0000-0000-000000000005', 'http://x/5', 'x/5', 'Five',  '["Wu"]',       '["imaging"]'),
    -- older than both windows
    ('10000000-0000-0000-0000-000000000006', 'http://x/6', 'x/6', 'Six',   '["Wu"]',       '["spatial"]'),
    -- Lab B only
    ('10000000-0000-0000-0000-000000000007', 'http://x/7', 'x/7', 'Seven', '["Wu"]',       '["spatial"]');

insert into public.paper_posts (paper_id, team_id, posted_by, posted_by_label, posted_at, tags, source) values
    ('10000000-0000-0000-0000-000000000001', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', null,  now() - interval '1 day',  '[]', 'web'),
    ('10000000-0000-0000-0000-000000000002', '33333333-3333-3333-3333-333333333333', null, 'Teams Tom',                         now() - interval '2 days', '[]', 'teams'),
    ('10000000-0000-0000-0000-000000000003', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', null,  now() - interval '3 days', '["spatial"]', 'web'),
    ('10000000-0000-0000-0000-000000000004', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', null,  now() - interval '40 days', '[]', 'web'),
    ('10000000-0000-0000-0000-000000000005', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', null,  now() - interval '45 days', '[]', 'web'),
    ('10000000-0000-0000-0000-000000000006', '33333333-3333-3333-3333-333333333333', '00000000-0000-0000-0000-00000000000a', null,  now() - interval '90 days', '[]', 'web'),
    ('10000000-0000-0000-0000-000000000007', '44444444-4444-4444-4444-444444444444', '00000000-0000-0000-0000-00000000000b', null,  now() - interval '1 day',  '[]', 'web');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000a"}';

-- === trending_tags ==========================================================
select results_eq(
    $$ select tag, n, prev from public.trending_tags('33333333-3333-3333-3333-333333333333', 30, 6) $$,
    $$ values ('spatial'::text, 3, 0), ('imaging'::text, 1, 2) $$,
    'trending_tags: current vs previous window; lab tags replace paper tags; older posts ignored'
);

select is(
    (select count(*)::int from public.trending_tags('33333333-3333-3333-3333-333333333333') where tag = 'ignored'),
    0,
    'a post with lab tags does not also count its paper tags'
);

select is(
    (select count(*)::int from public.trending_tags('44444444-4444-4444-4444-444444444444')),
    0,
    'another lab''s posts are invisible (RLS)'
);

select is(
    (select count(*)::int from public.trending_tags('33333333-3333-3333-3333-333333333333', 30, 1)),
    1,
    'p_limit caps the rows'
);

-- === trending_authors =======================================================
select results_eq(
    $$ select author, n, sharers from public.trending_authors('33333333-3333-3333-3333-333333333333', 30, 5) $$,
    $$ values ('Wu'::text, 2, 2), ('Ali'::text, 2, 1) $$,
    'trending_authors: papers in window; a Teams label counts as a sharer; ties go to more sharers'
);

-- === tag_volume =============================================================
select is(
    (select count(*)::int from public.tag_volume('33333333-3333-3333-3333-333333333333', 12, array['spatial', 'imaging'])),
    24,
    'tag_volume: every tag gets every week (zero-filled)'
);

select is(
    (select sum(n)::int from public.tag_volume('33333333-3333-3333-3333-333333333333', 12, array['spatial'])),
    3,
    'tag_volume: counts only posts inside the window (the 90-day-old one is out)'
);

select is(
    (select max(week) from public.tag_volume('33333333-3333-3333-3333-333333333333', 12, array['spatial'])),
    date_trunc('week', now())::date,
    'tag_volume: the last bucket is the current week'
);

select is(
    (select sum(n)::int from public.tag_volume('44444444-4444-4444-4444-444444444444', 12, array['spatial'])),
    0,
    'tag_volume: another lab''s posts are invisible (RLS)'
);

-- === the ?tag= filter agrees with Trending ==================================
select is(
    public.search_papers_count('33333333-3333-3333-3333-333333333333', '', 'spatial'),
    4,
    'search_papers_count: tag filter matches paper tags on posts without lab tags (3 + the 90-day one)'
);

select is(
    (select count(*)::int from public.search_papers('33333333-3333-3333-3333-333333333333', '', 'ignored')),
    0,
    'search_papers: a paper tag hidden by lab tags does not match'
);

select is(
    (select n from public.team_tags('33333333-3333-3333-3333-333333333333') where tag = 'spatial'),
    public.search_papers_count('33333333-3333-3333-3333-333333333333', '', 'spatial'),
    'team_tags: the tag menu''s count equals the filtered result count'
);

select * from finish();
rollback;
