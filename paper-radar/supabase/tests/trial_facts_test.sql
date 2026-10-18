-- trial_facts_test.sql — a lab's classification of its trials (20261019170000):
-- members correct it as themselves, Claude's rows are the service role's, and
-- other labs see nothing. Isolated `f2…` id space.

begin;
select plan(9);

insert into auth.users (id, email) values
    ('f2000000-0000-0000-0000-0000000000a1', 'tf.ada@lab.test'),
    ('f2000000-0000-0000-0000-0000000000a2', 'tf.bob@lab.test');
insert into public.profiles (id, display_name) values
    ('f2000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('f2000000-0000-0000-0000-0000000000a2', 'Bob') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('f2000000-0000-0000-0000-0000000000b1', 'Facts A', 'facts-a', 'f2000000-0000-0000-0000-0000000000a1'),
    ('f2000000-0000-0000-0000-0000000000b2', 'Facts B', 'facts-b', 'f2000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('f2000000-0000-0000-0000-0000000000b1', 'f2000000-0000-0000-0000-0000000000a1', 'owner'),
    ('f2000000-0000-0000-0000-0000000000b2', 'f2000000-0000-0000-0000-0000000000a2', 'owner');
insert into public.team_features (team_id, feature) values
    ('f2000000-0000-0000-0000-0000000000b1', 'clinical_trials'),
    ('f2000000-0000-0000-0000-0000000000b2', 'clinical_trials');

-- T1 on Lab A's list, classified by Claude; T2 on nobody's list.
insert into public.trials (id, nct_id, title, registry, breast_cancer) values
    ('f2000000-0000-0000-0000-0000000000e1', 'NCT91000001', 'One', '{}', true),
    ('f2000000-0000-0000-0000-0000000000e2', 'NCT91000002', 'Two', '{}', true);
insert into public.trial_posts (trial_id, team_id, source) values
    ('f2000000-0000-0000-0000-0000000000e1', 'f2000000-0000-0000-0000-0000000000b1', 'paper');
insert into public.trial_facts (team_id, trial_id, acronym, settings, classified_by) values
    ('f2000000-0000-0000-0000-0000000000b1', 'f2000000-0000-0000-0000-0000000000e1',
     'NeoTRIPaPDL1', '{neoadjuvant}', 'claude');

select throws_ok($$ insert into public.trial_facts (team_id, trial_id, settings)
    values ('f2000000-0000-0000-0000-0000000000b1', 'f2000000-0000-0000-0000-0000000000e2', '{perioperative}') $$,
    '23514', null, 'values outside the taxonomy are refused');

set local role authenticated;
set local request.jwt.claims to '{"sub":"f2000000-0000-0000-0000-0000000000a1"}';

select is((select acronym from public.trial_facts where trial_id = 'f2000000-0000-0000-0000-0000000000e1'),
    'NeoTRIPaPDL1', 'Ada reads her lab''s row');
select lives_ok($$ update public.trial_facts
    set acronym = 'NeoTRIP', classified_by = 'person', updated_by = 'f2000000-0000-0000-0000-0000000000a1'
    where trial_id = 'f2000000-0000-0000-0000-0000000000e1' $$,
    'Ada corrects the short name as herself');
select is((select acronym from public.trial_facts where trial_id = 'f2000000-0000-0000-0000-0000000000e1'),
    'NeoTRIP', 'the correction is stored');
select throws_ok($$ update public.trial_facts set classified_by = 'claude'
    where trial_id = 'f2000000-0000-0000-0000-0000000000e1' $$,
    '42501', null, 'a member cannot write as Claude');
select throws_ok($$ update public.trial_facts set team_id = 'f2000000-0000-0000-0000-0000000000b2'
    where trial_id = 'f2000000-0000-0000-0000-0000000000e1' $$,
    '42501', null, 'a row cannot be moved to another lab');
select throws_ok($$ insert into public.trial_facts (team_id, trial_id, classified_by, updated_by)
    values ('f2000000-0000-0000-0000-0000000000b1', 'f2000000-0000-0000-0000-0000000000e2',
            'person', 'f2000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'no row for a trial that is not on the list');

set local request.jwt.claims to '{"sub":"f2000000-0000-0000-0000-0000000000a2"}';
select is_empty($$ select 1 from public.trial_facts where team_id = 'f2000000-0000-0000-0000-0000000000b1' $$,
    'Bob sees nothing of Lab A''s');
select throws_ok($$ insert into public.trial_facts (team_id, trial_id, classified_by, updated_by)
    values ('f2000000-0000-0000-0000-0000000000b1', 'f2000000-0000-0000-0000-0000000000e1',
            'person', 'f2000000-0000-0000-0000-0000000000a2') $$,
    '42501', null, 'Bob cannot write into Lab A');

reset role;
select * from finish();
rollback;
