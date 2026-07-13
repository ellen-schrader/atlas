-- maps_test.sql — proves the maps RLS (lab vs. private vs. cross-lab) and that
-- map_members() ranks a lab's papers by seed similarity while forcing pinned in,
-- dropping excluded, and never crossing lab boundaries. Uses the same JWT-claims
-- trick as rls_isolation_test.sql to switch auth context inside one transaction.
--
-- Fixtures use an isolated `e5…` id space (not the 0000…/1111… ids other tests
-- use) so the whole test rolls back cleanly even against a populated dev database.

begin;
select plan(8);

-- A constant unit-ish vector for every embedding + the seed, so similarities tie
-- and the test isolates set membership (pin / exclude / scope), not ranking order.
create function pg_temp.qv() returns extensions.vector
language sql immutable as $$
    select array_fill(0.1::real, array[1024])::extensions.vector(1024);
$$;

-- === seed (superuser, RLS bypassed) ========================================

insert into auth.users (id, email, raw_user_meta_data) values
    ('e5000000-0000-0000-0000-0000000000a1', 'ada.maps@lab.test',  '{"display_name":"Ada"}'::jsonb),
    ('e5000000-0000-0000-0000-0000000000a2', 'bob.maps@lab.test',  '{"display_name":"Bob"}'::jsonb),
    ('e5000000-0000-0000-0000-0000000000a3', 'cara.maps@lab.test', '{"display_name":"Cara"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('e5000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('e5000000-0000-0000-0000-0000000000a2', 'Bob'),
    ('e5000000-0000-0000-0000-0000000000a3', 'Cara')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('e5000000-0000-0000-0000-0000000000b1', 'Lab A (maps)', 'lab-a-maps', 'e5000000-0000-0000-0000-0000000000a1'),
    ('e5000000-0000-0000-0000-0000000000b2', 'Lab B (maps)', 'lab-b-maps', 'e5000000-0000-0000-0000-0000000000a2');

insert into public.team_members (team_id, user_id, role) values
    ('e5000000-0000-0000-0000-0000000000b1', 'e5000000-0000-0000-0000-0000000000a1', 'owner'),
    ('e5000000-0000-0000-0000-0000000000b1', 'e5000000-0000-0000-0000-0000000000a3', 'member'),
    ('e5000000-0000-0000-0000-0000000000b2', 'e5000000-0000-0000-0000-0000000000a2', 'owner');

insert into public.papers (id, url, url_norm, title, embedding) values
    ('e5000000-0000-0000-0000-0000000000c1', 'http://m/1', 'm/1', 'P1', pg_temp.qv()),
    ('e5000000-0000-0000-0000-0000000000c2', 'http://m/2', 'm/2', 'P2', pg_temp.qv()),
    ('e5000000-0000-0000-0000-0000000000c3', 'http://m/3', 'm/3', 'P3', pg_temp.qv()),
    ('e5000000-0000-0000-0000-0000000000c4', 'http://m/4', 'm/4', 'P4', pg_temp.qv());

-- Lab A posts p1,p2,p3; Lab B posts p4 (must never surface in Lab A's map).
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('e5000000-0000-0000-0000-0000000000c1', 'e5000000-0000-0000-0000-0000000000b1', 'e5000000-0000-0000-0000-0000000000a1', 'web'),
    ('e5000000-0000-0000-0000-0000000000c2', 'e5000000-0000-0000-0000-0000000000b1', 'e5000000-0000-0000-0000-0000000000a1', 'web'),
    ('e5000000-0000-0000-0000-0000000000c3', 'e5000000-0000-0000-0000-0000000000b1', 'e5000000-0000-0000-0000-0000000000a1', 'web'),
    ('e5000000-0000-0000-0000-0000000000c4', 'e5000000-0000-0000-0000-0000000000b2', 'e5000000-0000-0000-0000-0000000000a2', 'web');

-- m1: a lab map with p2 pinned and p3 excluded. m2: Ada's private map.
insert into public.maps (id, team_id, created_by, name, seed, seed_embedding, visibility, config) values
    ('e5000000-0000-0000-0000-0000000000d1', 'e5000000-0000-0000-0000-0000000000b1',
     'e5000000-0000-0000-0000-0000000000a1', 'M1', 'ovarian', pg_temp.qv(), 'lab',
     '{"pinned":["e5000000-0000-0000-0000-0000000000c2"],"excluded":["e5000000-0000-0000-0000-0000000000c3"]}'::jsonb),
    ('e5000000-0000-0000-0000-0000000000d2', 'e5000000-0000-0000-0000-0000000000b1',
     'e5000000-0000-0000-0000-0000000000a1', 'M2', 'stroma', pg_temp.qv(), 'private', '{}'::jsonb);

-- === as Cara (member of Lab A, not the maps' creator) =======================
set local role authenticated;
set local request.jwt.claims to '{"sub":"e5000000-0000-0000-0000-0000000000a3"}';

select is(
    (select count(*)::int from public.maps where id = 'e5000000-0000-0000-0000-0000000000d1'),
    1, 'a member sees a lab map');

select is_empty(
    $$ select 1 from public.maps where id = 'e5000000-0000-0000-0000-0000000000d2' $$,
    'a member cannot see another member''s private map');

select set_eq(
    $$ select paper_id from public.map_members('e5000000-0000-0000-0000-0000000000d1'::uuid, 100) $$,
    $$ values ('e5000000-0000-0000-0000-0000000000c1'::uuid),
              ('e5000000-0000-0000-0000-0000000000c2'::uuid) $$,
    'map_members returns p1 + pinned p2, drops excluded p3 and cross-lab p4');

select is(
    (select pinned from public.map_members('e5000000-0000-0000-0000-0000000000d1'::uuid, 100)
        where paper_id = 'e5000000-0000-0000-0000-0000000000c2'),
    true, 'a pinned paper is flagged pinned');

-- === as Ada (the creator) ===================================================
set local request.jwt.claims to '{"sub":"e5000000-0000-0000-0000-0000000000a1"}';

select is(
    (select count(*)::int from public.maps where id = 'e5000000-0000-0000-0000-0000000000d2'),
    1, 'the creator sees her own private map');

-- === as Bob (Lab B, not a member of Lab A) ==================================
set local request.jwt.claims to '{"sub":"e5000000-0000-0000-0000-0000000000a2"}';

select is_empty(
    $$ select 1 from public.maps where id = 'e5000000-0000-0000-0000-0000000000d1' $$,
    'a non-member cannot see the lab map');

select is_empty(
    $$ select post_id from public.map_members('e5000000-0000-0000-0000-0000000000d1'::uuid, 100) $$,
    'map_members yields nothing to someone who cannot see the map');

select throws_ok(
    $$ insert into public.maps (team_id, created_by, name, seed)
       values ('e5000000-0000-0000-0000-0000000000b1',
               'e5000000-0000-0000-0000-0000000000a2', 'sneaky', 'x') $$,
    NULL, 'RLS blocks creating a map in a lab you do not belong to');

reset role;
select * from finish();
rollback;
