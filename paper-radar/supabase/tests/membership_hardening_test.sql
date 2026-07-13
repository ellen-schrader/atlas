-- membership_hardening_test.sql — proves the C1/H1 fixes from the pre-public
-- audit: clients can't write team_members directly, and joining requires the
-- high-entropy invite code (never the guessable slug) and never grants owner.
-- Run with `supabase test db`.

begin;
select plan(7);

-- === seed (as the superuser test role, RLS bypassed) =======================

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000a1', 'aa@lab.test', '{"display_name":"Aa"}'::jsonb),
    ('00000000-0000-0000-0000-0000000000b1', 'bb@lab.test', '{"display_name":"Bb"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-0000000000a1', 'Aa'),
    ('00000000-0000-0000-0000-0000000000b1', 'Bb')
on conflict (id) do nothing;

-- join_code set explicitly so the test knows Lab BB's secret.
insert into public.teams (id, name, slug, created_by, join_code) values
    ('a1111111-1111-1111-1111-111111111111', 'Lab AA', 'lab-aa', '00000000-0000-0000-0000-0000000000a1', 'aa-secret-code'),
    ('b2222222-2222-2222-2222-222222222222', 'Lab BB', 'lab-bb', '00000000-0000-0000-0000-0000000000b1', 'bb-secret-code');

insert into public.team_members (team_id, user_id, role) values
    ('a1111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-0000000000a1', 'owner'),
    ('b2222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-0000000000b1', 'owner');

-- === act as Aa (member of Lab AA only) =====================================

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000a1"}';

-- 1. The core C1 exploit: Aa cannot insert herself into Lab BB as owner.
select throws_ok(
    $$ insert into public.team_members (team_id, user_id, role)
       values ('b2222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-0000000000a1', 'owner') $$,
    '42501', NULL,
    'authenticated user cannot directly insert a team_members row (no cross-tenant owner-grab)');

-- 2. Joining with a guessed slug-like/wrong code is rejected for the RIGHT reason
--    (no such invite code — SQLSTATE P0002 = no_data_found), not any incidental error.
select throws_ok(
    $$ select public.join_team_by_code('lab-bb') $$,
    'P0002', NULL,
    'join_team_by_code rejects a wrong/guessed code (no_data_found)');

-- 3. Joining with the correct high-entropy code succeeds...
select lives_ok(
    $$ select public.join_team_by_code('bb-secret-code') $$,
    'join_team_by_code accepts the correct invite code');

-- ...but always as a member, never owner.
select is(
    (select role from public.team_members
     where team_id = 'b2222222-2222-2222-2222-222222222222'
       and user_id = '00000000-0000-0000-0000-0000000000a1'),
    'member',
    'join_team_by_code hard-codes role = member (no owner escalation)');

-- 4. Aa cannot self-escalate via a direct UPDATE (update privilege revoked).
select throws_ok(
    $$ update public.team_members set role = 'owner'
       where team_id = 'b2222222-2222-2222-2222-222222222222'
         and user_id = '00000000-0000-0000-0000-0000000000a1' $$,
    '42501', NULL,
    'authenticated user cannot UPDATE a team_members role directly');

-- 5. Aa cannot delete-then-reinsert (delete privilege revoked; use leave_team).
select throws_ok(
    $$ delete from public.team_members
       where team_id = 'b2222222-2222-2222-2222-222222222222'
         and user_id = '00000000-0000-0000-0000-0000000000a1' $$,
    '42501', NULL,
    'authenticated user cannot DELETE a team_members row directly');

-- 6. The real escalation path: Aa (now a member of Lab BB) cannot promote herself
--    to owner via the owner-guarded RPC.
select throws_ok(
    $$ select public.set_member_role('b2222222-2222-2222-2222-222222222222',
                                     '00000000-0000-0000-0000-0000000000a1', 'owner') $$,
    '42501', NULL,
    'a non-owner cannot self-promote via set_member_role');

reset role;
select * from finish();
rollback;
