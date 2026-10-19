-- trial_extraction_queue_test.sql — a trial queues itself when it gets its
-- first source (20261019210000), never re-queues a finished one, and each
-- lab sees only its own spend. `f6…` ids.

begin;
select plan(6);

insert into auth.users (id, email) values
    ('f6000000-0000-0000-0000-0000000000a1', 'q.ada@lab.test'),
    ('f6000000-0000-0000-0000-0000000000a2', 'q.bob@lab.test');
insert into public.profiles (id, display_name) values
    ('f6000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('f6000000-0000-0000-0000-0000000000a2', 'Bob') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('f6000000-0000-0000-0000-0000000000b1', 'Q A', 'q-a', 'f6000000-0000-0000-0000-0000000000a1'),
    ('f6000000-0000-0000-0000-0000000000b2', 'Q B', 'q-b', 'f6000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('f6000000-0000-0000-0000-0000000000b1', 'f6000000-0000-0000-0000-0000000000a1', 'owner'),
    ('f6000000-0000-0000-0000-0000000000b2', 'f6000000-0000-0000-0000-0000000000a2', 'owner');
insert into public.team_features (team_id, feature) values
    ('f6000000-0000-0000-0000-0000000000b1', 'clinical_trials'),
    ('f6000000-0000-0000-0000-0000000000b2', 'clinical_trials');
insert into public.trials (id, nct_id, title, registry, breast_cancer) values
    ('f6000000-0000-0000-0000-0000000000e1', 'NCT95000001', 'New', '{}', true),
    ('f6000000-0000-0000-0000-0000000000e2', 'NCT95000002', 'Done', '{}', true);
insert into public.trial_posts (trial_id, team_id, source) values
    ('f6000000-0000-0000-0000-0000000000e1', 'f6000000-0000-0000-0000-0000000000b1', 'paper'),
    ('f6000000-0000-0000-0000-0000000000e2', 'f6000000-0000-0000-0000-0000000000b1', 'paper');
insert into public.trial_facts (team_id, trial_id, extraction, extraction_status) values
    ('f6000000-0000-0000-0000-0000000000b1', 'f6000000-0000-0000-0000-0000000000e2', '{}', 'done');

insert into public.trial_sources (team_id, trial_id, kind, origin, storage_path, filename, media_type, bytes) values
    ('f6000000-0000-0000-0000-0000000000b1', 'f6000000-0000-0000-0000-0000000000e1', 'paper', 'europepmc',
     'f6000000-0000-0000-0000-0000000000b1/f6000000-0000-0000-0000-0000000000e1/a.xml', 'a', 'application/xml', 10),
    ('f6000000-0000-0000-0000-0000000000b1', 'f6000000-0000-0000-0000-0000000000e2', 'paper', 'europepmc',
     'f6000000-0000-0000-0000-0000000000b1/f6000000-0000-0000-0000-0000000000e2/b.xml', 'b', 'application/xml', 10);

select is((select extraction_status from public.trial_facts where trial_id = 'f6000000-0000-0000-0000-0000000000e1'),
    'queued', 'a first source queues a never-extracted trial');
select is((select extraction_mode from public.trial_facts where trial_id = 'f6000000-0000-0000-0000-0000000000e1'),
    'batch', 'for the half-price batch');
select is((select extraction_status from public.trial_facts where trial_id = 'f6000000-0000-0000-0000-0000000000e2'),
    'done', 'a new source never re-queues a finished extraction');

insert into public.trial_extraction_spend (team_id, trial_id, usd, mode) values
    ('f6000000-0000-0000-0000-0000000000b1', 'f6000000-0000-0000-0000-0000000000e1', 0.15, 'batch');

set local role authenticated;
set local request.jwt.claims to '{"sub":"f6000000-0000-0000-0000-0000000000a1"}';
select is((select sum(usd) from public.trial_extraction_spend
            where team_id = 'f6000000-0000-0000-0000-0000000000b1'), 0.15::numeric, 'the lab sees its spend');
select throws_ok($$ insert into public.trial_extraction_spend (team_id, trial_id, usd, mode)
    values ('f6000000-0000-0000-0000-0000000000b1', 'f6000000-0000-0000-0000-0000000000e1', 0, 'now') $$,
    '42501', null, 'members cannot write spend');
set local request.jwt.claims to '{"sub":"f6000000-0000-0000-0000-0000000000a2"}';
select is_empty($$ select 1 from public.trial_extraction_spend
                    where team_id = 'f6000000-0000-0000-0000-0000000000b1' $$, 'another lab sees none of it');
reset role;

select * from finish();
rollback;
