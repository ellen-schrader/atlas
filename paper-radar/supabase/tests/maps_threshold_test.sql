-- maps_threshold_test.sql — the relevance floor: map_members keeps only papers at
-- or above config.min_similarity (pinned always in), and map_member_stats counts
-- either side of the floor. Isolated id space so it rolls back cleanly anywhere.

begin;
select plan(5);

create function pg_temp.qv() returns extensions.vector
language sql immutable as $$
    select array_fill(0.1::real, array[1024])::extensions.vector(1024);
$$;

-- all embeddings == the seed, so similarity is 1.0 for every candidate; the test
-- then isolates the *floor* behaviour (above/below/pinned), not ranking.
insert into auth.users (id, email) values
    ('e6000000-0000-0000-0000-0000000000a1', 'thr.ada@lab.test');
insert into public.profiles (id, display_name) values
    ('e6000000-0000-0000-0000-0000000000a1', 'Ada') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('e6000000-0000-0000-0000-0000000000b1', 'Thr Lab', 'thr-lab', 'e6000000-0000-0000-0000-0000000000a1');
insert into public.team_members (team_id, user_id, role) values
    ('e6000000-0000-0000-0000-0000000000b1', 'e6000000-0000-0000-0000-0000000000a1', 'owner');
insert into public.papers (id, url, url_norm, title, embedding) values
    ('e6000000-0000-0000-0000-0000000000c1', 'http://t/1', 't/1', 'A', pg_temp.qv()),
    ('e6000000-0000-0000-0000-0000000000c2', 'http://t/2', 't/2', 'B', pg_temp.qv()),
    ('e6000000-0000-0000-0000-0000000000c3', 'http://t/3', 't/3', 'C', pg_temp.qv());
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('e6000000-0000-0000-0000-0000000000c1', 'e6000000-0000-0000-0000-0000000000b1', 'e6000000-0000-0000-0000-0000000000a1', 'web'),
    ('e6000000-0000-0000-0000-0000000000c2', 'e6000000-0000-0000-0000-0000000000b1', 'e6000000-0000-0000-0000-0000000000a1', 'web'),
    ('e6000000-0000-0000-0000-0000000000c3', 'e6000000-0000-0000-0000-0000000000b1', 'e6000000-0000-0000-0000-0000000000a1', 'web');

-- mHigh: floor 2.0 (above any cosine) with B pinned and C excluded → only B is in.
-- mLow: floor 0.5 (below the 1.0 similarities) → all three are in.
insert into public.maps (id, team_id, created_by, name, seed, seed_embedding, config) values
    ('e6000000-0000-0000-0000-0000000000d1', 'e6000000-0000-0000-0000-0000000000b1',
     'e6000000-0000-0000-0000-0000000000a1', 'High', 's', pg_temp.qv(),
     '{"min_similarity":2.0,"pinned":["e6000000-0000-0000-0000-0000000000c2"],"excluded":["e6000000-0000-0000-0000-0000000000c3"]}'::jsonb),
    ('e6000000-0000-0000-0000-0000000000d2', 'e6000000-0000-0000-0000-0000000000b1',
     'e6000000-0000-0000-0000-0000000000a1', 'Low', 's', pg_temp.qv(),
     '{"min_similarity":0.5}'::jsonb);

set local role authenticated;
set local request.jwt.claims to '{"sub":"e6000000-0000-0000-0000-0000000000a1"}';

select set_eq(
    $$ select paper_id from public.map_members('e6000000-0000-0000-0000-0000000000d1'::uuid, 100) $$,
    $$ values ('e6000000-0000-0000-0000-0000000000c2'::uuid) $$,
    'a high floor keeps only the pinned paper');

select is(
    (select in_scope from public.map_member_stats('e6000000-0000-0000-0000-0000000000d1'::uuid)),
    1, 'stats: 1 in scope (the pinned paper) under a high floor');

select is(
    (select below from public.map_member_stats('e6000000-0000-0000-0000-0000000000d1'::uuid)),
    1, 'stats: 1 below the floor (A; C is excluded, B is pinned)');

select set_eq(
    $$ select paper_id from public.map_members('e6000000-0000-0000-0000-0000000000d2'::uuid, 100) $$,
    $$ values ('e6000000-0000-0000-0000-0000000000c1'::uuid),
              ('e6000000-0000-0000-0000-0000000000c2'::uuid),
              ('e6000000-0000-0000-0000-0000000000c3'::uuid) $$,
    'a low floor keeps every paper above it');

select is(
    (select below from public.map_member_stats('e6000000-0000-0000-0000-0000000000d2'::uuid)),
    0, 'stats: none below a low floor');

reset role;
select * from finish();
rollback;
