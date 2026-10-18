-- connector_taste_test.sql — the Claude connector may read the caller's OWN
-- recommendation inputs (20261019120000_connector_taste.sql), and nothing more of
-- profiles. Run with `supabase test db`.

begin;
select plan(12);

insert into auth.users (id, email) values
    ('0d000000-0000-0000-0000-00000000000a', 'taste-ada@lab.test'),
    ('0d000000-0000-0000-0000-00000000000b', 'taste-bo@lab.test');
insert into public.profiles (id, display_name) values
    ('0d000000-0000-0000-0000-00000000000a', 'Ada Lovelace'),
    ('0d000000-0000-0000-0000-00000000000b', 'Bo Chen')
on conflict (id) do update set display_name = excluded.display_name;
update public.profiles
   set profile_md = 'Tumour microenvironment', interests = '["spatial-omics"]'
 where id = '0d000000-0000-0000-0000-00000000000a';
update public.profiles
   set profile_md = 'Bo''s private research notes'
 where id = '0d000000-0000-0000-0000-00000000000b';
insert into auth.sessions (id, user_id) values
    ('0d5e5510-0000-0000-0000-000000000001', '0d000000-0000-0000-0000-00000000000a');

-- A lab with five recent posts: Ada's own, one she posted from Teams (named in
-- p_exclude), one she reacted to, and two she hasn't seen; plus an old one.
create function pg_temp.v(x real) returns extensions.vector
language sql immutable as $$
    select (array[x, 1 - x] || array_fill(0::real, array[1022]))::extensions.vector(1024);
$$;
insert into public.teams (id, name, slug, created_by) values
    ('0d111111-1111-1111-1111-111111111111', 'Lab T', 'lab-t-taste', '0d000000-0000-0000-0000-00000000000a');
insert into public.team_members (team_id, user_id, role) values
    ('0d111111-1111-1111-1111-111111111111', '0d000000-0000-0000-0000-00000000000a', 'owner'),
    ('0d111111-1111-1111-1111-111111111111', '0d000000-0000-0000-0000-00000000000b', 'member');
insert into public.papers (id, url, url_norm, title, embedding, tags) values
    ('0d100000-0000-0000-0000-000000000001', 'http://taste.test/1', 'taste-test/1', 'Own',      pg_temp.v(1), '[]'),
    ('0d100000-0000-0000-0000-000000000002', 'http://taste.test/2', 'taste-test/2', 'Teams',    pg_temp.v(1), '[]'),
    ('0d100000-0000-0000-0000-000000000003', 'http://taste.test/3', 'taste-test/3', 'Reacted',  pg_temp.v(1), '[]'),
    ('0d100000-0000-0000-0000-000000000004', 'http://taste.test/4', 'taste-test/4', 'Near',     pg_temp.v(1), '["ffpe"]'),
    ('0d100000-0000-0000-0000-000000000005', 'http://taste.test/5', 'taste-test/5', 'Far',      pg_temp.v(0), '[]'),
    ('0d100000-0000-0000-0000-000000000006', 'http://taste.test/6', 'taste-test/6', 'Old',      pg_temp.v(1), '[]');
insert into public.paper_posts (paper_id, team_id, posted_by, posted_by_label, source, posted_at) values
    ('0d100000-0000-0000-0000-000000000001', '0d111111-1111-1111-1111-111111111111',
     '0d000000-0000-0000-0000-00000000000a', null, 'web', now()),
    ('0d100000-0000-0000-0000-000000000002', '0d111111-1111-1111-1111-111111111111',
     null, 'Lovelace, Ada', 'teams', now()),
    ('0d100000-0000-0000-0000-000000000003', '0d111111-1111-1111-1111-111111111111',
     '0d000000-0000-0000-0000-00000000000b', null, 'web', now()),
    ('0d100000-0000-0000-0000-000000000004', '0d111111-1111-1111-1111-111111111111',
     '0d000000-0000-0000-0000-00000000000b', null, 'web', now()),
    ('0d100000-0000-0000-0000-000000000005', '0d111111-1111-1111-1111-111111111111',
     '0d000000-0000-0000-0000-00000000000b', null, 'web', now()),
    ('0d100000-0000-0000-0000-000000000006', '0d111111-1111-1111-1111-111111111111',
     '0d000000-0000-0000-0000-00000000000b', null, 'web', now() - interval '60 days');
insert into public.reactions (paper_id, team_id, user_id, emoji) values
    ('0d100000-0000-0000-0000-000000000003', '0d111111-1111-1111-1111-111111111111',
     '0d000000-0000-0000-0000-00000000000a', '👍');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"0d000000-0000-0000-0000-00000000000a","role":"authenticated",'
    '"client_id":"claude","session_id":"0d5e5510-0000-0000-0000-000000000001"}';

-- The gate lets the two new reads through, and still nothing else.
set local request.method to 'POST';
set local request.path to '/rpc/my_recommendation_inputs';
select lives_ok('select public.connector_request_guard()',
    'connector may read its own recommendation inputs');

set local request.path to '/rpc/recommend_tagged';
select lives_ok('select public.connector_request_guard()',
    'connector may search followed tags');

set local request.path to '/rpc/window_scores';
select lives_ok('select public.connector_request_guard()',
    'connector may score the digest window');

set local request.method to 'GET';
set local request.path to '/profiles';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector still may not read the profiles table');

-- The function returns the caller's row, and only it.
select is((select count(*)::int from public.my_recommendation_inputs()), 1,
    'one row: the caller''s');
select is((select display_name from public.my_recommendation_inputs()), 'Ada Lovelace',
    'it is the caller''s own profile');
select is((select interests from public.my_recommendation_inputs()), '["spatial-omics"]'::jsonb,
    'with the tags they follow');

-- window_scores: only what you haven't posted, excluded or engaged with, in the window.
select is(
    (select array_agg(paper_id order by paper_id) from public.window_scores(
        '0d111111-1111-1111-1111-111111111111', now() - interval '7 days', pg_temp.v(1),
        array['0d100000-0000-0000-0000-000000000002']::uuid[])),
    array['0d100000-0000-0000-0000-000000000004',
          '0d100000-0000-0000-0000-000000000005']::uuid[],
    'window_scores leaves out own, Teams-own, engaged and older posts');
select is(
    (select round(similarity::numeric, 2) from public.window_scores(
        '0d111111-1111-1111-1111-111111111111', now() - interval '7 days', pg_temp.v(1))
     where paper_id = '0d100000-0000-0000-0000-000000000004'),
    1.00, 'and scores the rest against the query');
select is(
    (select tags from public.window_scores(
        '0d111111-1111-1111-1111-111111111111', now() - interval '7 days')
     where paper_id = '0d100000-0000-0000-0000-000000000004'),
    '["ffpe"]'::jsonb, 'with their tags, and no score without a query');
select is(
    (select count(*)::int from public.window_scores(
        '0d222222-2222-2222-2222-222222222222', now() - interval '7 days')),
    0, 'nothing from a lab you are not in');

-- Layer 2 still keeps the table itself shut to a connector token.
select is((select count(*)::int from public.profiles), 0,
    'a connector token selects no profile rows directly');

reset role;
select * from finish();
rollback;
