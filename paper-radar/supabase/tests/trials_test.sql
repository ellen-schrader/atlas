-- trials_test.sql — clinical trials stay dark until switched on, stay inside
-- the lab, and paper links survive a merge (20261019150000, 20261019160000).
-- Isolated `f1…` id space so it rolls back cleanly anywhere.

begin;
select plan(32);

-- Ada: Lab A, which has the feature switched on.
-- Bob and Cara: Lab B, which doesn't. Cara has it switched on just for her.
insert into auth.users (id, email) values
    ('f1000000-0000-0000-0000-0000000000a1', 'tr.ada@lab.test'),
    ('f1000000-0000-0000-0000-0000000000a2', 'tr.bob@lab.test'),
    ('f1000000-0000-0000-0000-0000000000a3', 'tr.cara@lab.test');
insert into public.profiles (id, display_name) values
    ('f1000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('f1000000-0000-0000-0000-0000000000a2', 'Bob'),
    ('f1000000-0000-0000-0000-0000000000a3', 'Cara') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('f1000000-0000-0000-0000-0000000000b1', 'Trials A', 'trials-a', 'f1000000-0000-0000-0000-0000000000a1'),
    ('f1000000-0000-0000-0000-0000000000b2', 'Trials B', 'trials-b', 'f1000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000a1', 'owner'),
    ('f1000000-0000-0000-0000-0000000000b2', 'f1000000-0000-0000-0000-0000000000a2', 'owner'),
    ('f1000000-0000-0000-0000-0000000000b2', 'f1000000-0000-0000-0000-0000000000a3', 'member');

insert into public.team_features (team_id, feature) values
    ('f1000000-0000-0000-0000-0000000000b1', 'clinical_trials');
insert into public.user_features (user_id, feature) values
    ('f1000000-0000-0000-0000-0000000000a3', 'clinical_trials');

-- T1 in Lab A, T2 in Lab B.
insert into public.trials (id, nct_id, title, registry) values
    ('f1000000-0000-0000-0000-0000000000e1', 'NCT90000001', 'Trial one', '{}'),
    ('f1000000-0000-0000-0000-0000000000e2', 'NCT90000002', 'Trial two', '{}');
insert into public.trial_posts (trial_id, team_id, added_by, source) values
    ('f1000000-0000-0000-0000-0000000000e1', 'f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000a1', 'manual'),
    ('f1000000-0000-0000-0000-0000000000e2', 'f1000000-0000-0000-0000-0000000000b2', null, 'paper');

-- P1, P2 in Lab A; P3 in Lab B.
insert into public.papers (id, url, url_norm, title) values
    ('f1000000-0000-0000-0000-0000000000c1', 'http://tr/1', 'tr/1', 'P1'),
    ('f1000000-0000-0000-0000-0000000000c2', 'http://tr/2', 'tr/2', 'P2'),
    ('f1000000-0000-0000-0000-0000000000c3', 'http://tr/3', 'tr/3', 'P3');
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('f1000000-0000-0000-0000-0000000000c1', 'f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000a1', 'web'),
    ('f1000000-0000-0000-0000-0000000000c2', 'f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000a1', 'web'),
    ('f1000000-0000-0000-0000-0000000000c3', 'f1000000-0000-0000-0000-0000000000b2', 'f1000000-0000-0000-0000-0000000000a2', 'web');

insert into public.paper_trials (id, team_id, paper_id, trial_id, source, status) values
    ('f1000000-0000-0000-0000-0000000000d1', 'f1000000-0000-0000-0000-0000000000b1',
     'f1000000-0000-0000-0000-0000000000c1', 'f1000000-0000-0000-0000-0000000000e1', 'nct_in_abstract', 'auto'),
    ('f1000000-0000-0000-0000-0000000000d3', 'f1000000-0000-0000-0000-0000000000b2',
     'f1000000-0000-0000-0000-0000000000c3', 'f1000000-0000-0000-0000-0000000000e2', 'nct_in_abstract', 'auto');

select set_eq(
    $$ select t from public.feature_teams('clinical_trials') t
        where t in ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000b2') $$,
    $$ values ('f1000000-0000-0000-0000-0000000000b1'::uuid), ('f1000000-0000-0000-0000-0000000000b2'::uuid) $$,
    'feature_teams: Lab A by its switch, Lab B by Cara''s');

-- === Ada: Lab A has the feature =============================================
set local role authenticated;
set local request.jwt.claims to '{"sub":"f1000000-0000-0000-0000-0000000000a1"}';

select is(public.my_features('f1000000-0000-0000-0000-0000000000b1'), '{clinical_trials}'::text[],
    'my_features: Ada has it in Lab A');
select is(public.my_features('f1000000-0000-0000-0000-0000000000b2'), '{}'::text[],
    'my_features: nothing for a lab Ada is not in');
select set_eq($$ select nct_id from public.trials where nct_id like 'NCT9000000%' $$,
    $$ values ('NCT90000001') $$, 'Ada sees her lab''s trial, not Lab B''s');
select is((select count(*)::int from public.trial_posts where team_id in
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000b2')), 1,
    'Ada sees only Lab A''s list');
select set_eq($$ select id from public.paper_trials where team_id in
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000b2') $$,
    $$ values ('f1000000-0000-0000-0000-0000000000d1'::uuid) $$, 'Ada sees only Lab A''s links');

select throws_ok($$ select * from public.team_features $$, '42501', null,
    'members cannot read the switches');
select throws_ok($$ insert into public.user_features (user_id, feature)
    values ('f1000000-0000-0000-0000-0000000000a1', 'anything') $$, '42501', null,
    'nobody switches a feature on for themselves');
select throws_ok($$ select public.feature_teams('clinical_trials') $$, '42501', null,
    'feature_teams is service role only');

select throws_ok($$ insert into public.trial_posts (trial_id, team_id, added_by, source)
    values ('f1000000-0000-0000-0000-0000000000e2', 'f1000000-0000-0000-0000-0000000000b1',
            'f1000000-0000-0000-0000-0000000000a1', 'paper') $$, '42501', null,
    'only Atlas adds a trial as source ''paper''');
select lives_ok($$ insert into public.trial_posts (trial_id, team_id, added_by, source)
    values ('f1000000-0000-0000-0000-0000000000e2', 'f1000000-0000-0000-0000-0000000000b1',
            'f1000000-0000-0000-0000-0000000000a1', 'manual') $$,
    'Ada adds a trial to her lab by hand');
select throws_ok($$ insert into public.trial_posts (trial_id, team_id, added_by, source)
    values ('f1000000-0000-0000-0000-0000000000e1', 'f1000000-0000-0000-0000-0000000000b2',
            'f1000000-0000-0000-0000-0000000000a1', 'manual') $$, '42501', null,
    'Ada cannot add to a lab she is not in');

select throws_ok($$ insert into public.paper_trials (team_id, paper_id, trial_id, source, status, reviewed_by)
    values ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c3',
            'f1000000-0000-0000-0000-0000000000e1', 'manual', 'confirmed', 'f1000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'cannot link a paper the lab does not hold');
select lives_ok($$ insert into public.paper_trials (team_id, paper_id, trial_id, source, status, reviewed_by)
    values ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c2',
            'f1000000-0000-0000-0000-0000000000e1', 'manual', 'confirmed', 'f1000000-0000-0000-0000-0000000000a1') $$,
    'Ada links a lab paper to a lab trial');

select lives_ok($$ update public.paper_trials
    set status = 'rejected', reviewed_by = 'f1000000-0000-0000-0000-0000000000a1', reviewed_at = now()
    where id = 'f1000000-0000-0000-0000-0000000000d1' $$,
    'Ada rejects an automatic link');
select throws_ok($$ update public.paper_trials set paper_id = 'f1000000-0000-0000-0000-0000000000c3'
    where id = 'f1000000-0000-0000-0000-0000000000d1' $$, '42501', null,
    'a link cannot be moved to another paper');

-- === Bob: Lab B, no switch for the lab or for him ============================
set local request.jwt.claims to '{"sub":"f1000000-0000-0000-0000-0000000000a2"}';

select is(public.my_features('f1000000-0000-0000-0000-0000000000b2'), '{}'::text[],
    'my_features: Bob has nothing');
select is_empty($$ select 1 from public.trials where nct_id like 'NCT9000000%' $$,
    'Bob sees no trials, though his lab holds one');
select is_empty($$ select 1 from public.paper_trials where team_id = 'f1000000-0000-0000-0000-0000000000b2' $$,
    'Bob sees none of his lab''s links');
select throws_ok($$ insert into public.trial_posts (trial_id, team_id, added_by, source)
    values ('f1000000-0000-0000-0000-0000000000e1', 'f1000000-0000-0000-0000-0000000000b2',
            'f1000000-0000-0000-0000-0000000000a2', 'manual') $$, '42501', null,
    'Bob cannot add trials either');

-- === Cara: Lab B, switched on just for her ==================================
set local request.jwt.claims to '{"sub":"f1000000-0000-0000-0000-0000000000a3"}';

select set_eq($$ select nct_id from public.trials where nct_id like 'NCT9000000%' $$,
    $$ values ('NCT90000002') $$, 'Cara sees Lab B''s trial, and only that');

reset role;

-- === merging P1 into P2 moves the lab's links ===============================
-- Lab A before the merge:
--   T1: P1 rejected by Ada, P2 confirmed by Ada  -> both decisions; the kept paper's stays
--   T2: P1 rejected, P2 automatic                -> the decision beats the automatic link
--   T3: P1 automatic only                         -> moves to P2
--   T4: P1 automatic, P2 suggested               -> the NCT match beats the name match
insert into public.trials (id, nct_id, title, registry) values
    ('f1000000-0000-0000-0000-0000000000e3', 'NCT90000003', 'Trial three', '{}'),
    ('f1000000-0000-0000-0000-0000000000e4', 'NCT90000004', 'Trial four', '{}');
insert into public.trial_posts (trial_id, team_id, added_by, source) values
    ('f1000000-0000-0000-0000-0000000000e3', 'f1000000-0000-0000-0000-0000000000b1', null, 'paper'),
    ('f1000000-0000-0000-0000-0000000000e4', 'f1000000-0000-0000-0000-0000000000b1', null, 'paper');
insert into public.paper_trials (team_id, paper_id, trial_id, source, status, reviewed_by) values
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c1',
     'f1000000-0000-0000-0000-0000000000e2', 'acronym_in_title', 'rejected', 'f1000000-0000-0000-0000-0000000000a1'),
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c2',
     'f1000000-0000-0000-0000-0000000000e2', 'nct_in_abstract', 'auto', null),
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c1',
     'f1000000-0000-0000-0000-0000000000e3', 'nct_in_abstract', 'auto', null),
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c1',
     'f1000000-0000-0000-0000-0000000000e4', 'nct_in_abstract', 'auto', null),
    ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000c2',
     'f1000000-0000-0000-0000-0000000000e4', 'acronym_in_title', 'suggested', null);

select lives_ok($$ select public.merge_papers('f1000000-0000-0000-0000-0000000000c1',
    'f1000000-0000-0000-0000-0000000000c2', 'manual') $$, 'merge_papers runs');
select set_eq(
    $$ select trial_id, status from public.paper_trials
        where paper_id = 'f1000000-0000-0000-0000-0000000000c2' $$,
    $$ values ('f1000000-0000-0000-0000-0000000000e1'::uuid, 'confirmed'),
              ('f1000000-0000-0000-0000-0000000000e2'::uuid, 'rejected'),
              ('f1000000-0000-0000-0000-0000000000e3'::uuid, 'auto'),
              ('f1000000-0000-0000-0000-0000000000e4'::uuid, 'auto') $$,
    'the kept paper has one link per trial: kept decision, decision over automatic, moved, auto over suggested');
select is((select count(*)::int from public.paper_trials
            where paper_id = 'f1000000-0000-0000-0000-0000000000c1'), 0,
    'nothing is left on the merged-away paper');

-- === taking a trial off the list ===========================================
-- Lab A: P2–T1 confirmed (a decision), P2–T4 auto. Ada takes both trials off.
set local role authenticated;
set local request.jwt.claims to '{"sub":"f1000000-0000-0000-0000-0000000000a1"}';

select lives_ok($$ delete from public.trial_posts
    where team_id = 'f1000000-0000-0000-0000-0000000000b1'
      and trial_id in ('f1000000-0000-0000-0000-0000000000e1', 'f1000000-0000-0000-0000-0000000000e4') $$,
    'Ada takes two trials off the list');
select set_eq($$ select trial_id from public.trial_removals where team_id = 'f1000000-0000-0000-0000-0000000000b1' $$,
    $$ values ('f1000000-0000-0000-0000-0000000000e1'::uuid), ('f1000000-0000-0000-0000-0000000000e4'::uuid) $$,
    'the lab remembers both removals');
select set_eq($$ select trial_id, status from public.paper_trials
                  where team_id = 'f1000000-0000-0000-0000-0000000000b1'
                    and trial_id in ('f1000000-0000-0000-0000-0000000000e1', 'f1000000-0000-0000-0000-0000000000e4') $$,
    $$ values ('f1000000-0000-0000-0000-0000000000e1'::uuid, 'confirmed') $$,
    'the automatic link goes, the confirmed one stays');
select throws_ok($$ insert into public.trial_removals (team_id, trial_id)
    values ('f1000000-0000-0000-0000-0000000000b1', 'f1000000-0000-0000-0000-0000000000e2') $$,
    '42501', null, 'members cannot write removals directly');
select lives_ok($$ insert into public.trial_posts (trial_id, team_id, added_by, source)
    values ('f1000000-0000-0000-0000-0000000000e1', 'f1000000-0000-0000-0000-0000000000b1',
            'f1000000-0000-0000-0000-0000000000a1', 'manual') $$,
    'Ada puts T1 back by hand');
select set_eq($$ select trial_id from public.trial_removals where team_id = 'f1000000-0000-0000-0000-0000000000b1' $$,
    $$ values ('f1000000-0000-0000-0000-0000000000e4'::uuid) $$,
    'putting it back forgets that removal only');

reset role;

-- Deleting a whole lab empties its list without recording removals.
select lives_ok($$ delete from public.teams where id = 'f1000000-0000-0000-0000-0000000000b2' $$,
    'a lab with trials can still be deleted');
select is((select count(*)::int from public.trial_removals where team_id = 'f1000000-0000-0000-0000-0000000000b2'), 0,
    'and leaves no removals behind');

select * from finish();
rollback;
