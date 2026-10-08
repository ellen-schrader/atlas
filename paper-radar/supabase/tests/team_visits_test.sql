-- team_visits_test.sql — new_since_last_visit / mark_team_visit
-- (20261008140000_team_visits.sql): NULL before the first visit, counts other
-- people's posts after it, ignores your own, resets on a new visit, and can't
-- touch a lab you're not in or someone else's row.

begin;
select plan(7);

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000a1', 'ada-v@lab.test', '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-0000000000b1', 'bob-v@lab.test', '{"display_name":"Bob"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('00000000-0000-0000-0000-0000000000b1', 'Bob')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('55555555-5555-5555-5555-555555555555', 'Visit Lab A', 'visit-lab-a', '00000000-0000-0000-0000-0000000000a1'),
    ('66666666-6666-6666-6666-666666666666', 'Visit Lab B', 'visit-lab-b', '00000000-0000-0000-0000-0000000000b1');

insert into public.team_members (team_id, user_id, role) values
    ('55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000a1', 'owner'),
    ('55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000b1', 'member'),
    ('66666666-6666-6666-6666-666666666666', '00000000-0000-0000-0000-0000000000b1', 'owner');

insert into public.papers (id, url, url_norm, title) values
    ('a0000000-0000-0000-0000-000000000001', 'http://v/1', 'v/1', 'Before the visit'),
    ('a0000000-0000-0000-0000-000000000002', 'http://v/2', 'v/2', 'Bob after'),
    ('a0000000-0000-0000-0000-000000000003', 'http://v/3', 'v/3', 'Teams after'),
    ('a0000000-0000-0000-0000-000000000004', 'http://v/4', 'v/4', 'Ada after');

-- Ada last visited Lab A two days ago.
insert into public.team_visits (user_id, team_id, last_seen_at) values
    ('00000000-0000-0000-0000-0000000000a1', '55555555-5555-5555-5555-555555555555', now() - interval '2 days');

insert into public.paper_posts (paper_id, team_id, posted_by, posted_by_label, posted_at, source) values
    ('a0000000-0000-0000-0000-000000000001', '55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000b1', null, now() - interval '3 days', 'web'),
    ('a0000000-0000-0000-0000-000000000002', '55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000b1', null, now() - interval '1 day', 'web'),
    ('a0000000-0000-0000-0000-000000000003', '55555555-5555-5555-5555-555555555555', null, 'Teams Tom', now() - interval '1 hour', 'teams'),
    ('a0000000-0000-0000-0000-000000000004', '55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000a1', null, now() - interval '1 hour', 'web');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000a1"}';

select is(
    public.new_since_last_visit('55555555-5555-5555-5555-555555555555'),
    2,
    'counts posts by others (incl. a Teams post) since the last visit, not your own'
);

select is(
    public.new_since_last_visit('66666666-6666-6666-6666-666666666666'),
    null,
    'no visit row → NULL, not the lab''s whole history'
);

select lives_ok(
    $$ select public.mark_team_visit('55555555-5555-5555-5555-555555555555') $$,
    'mark_team_visit stamps a lab you belong to'
);

select is(
    public.new_since_last_visit('55555555-5555-5555-5555-555555555555'),
    0,
    'after a fresh visit nothing is new'
);

select throws_ok(
    $$ select public.mark_team_visit('66666666-6666-6666-6666-666666666666') $$,
    '42501',
    null,
    'cannot stamp a lab you are not in (RLS)'
);

-- Bob can't see Ada's row.
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000b1"}';

select is(
    (select count(*)::int from public.team_visits where user_id = '00000000-0000-0000-0000-0000000000a1'),
    0,
    'another user''s visit rows are invisible'
);

select is(
    public.new_since_last_visit('55555555-5555-5555-5555-555555555555'),
    null,
    'Bob has never visited Lab A'
);

select * from finish();
rollback;
