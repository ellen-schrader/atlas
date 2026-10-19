-- trial_events_test.sql — the feed's events (20261019200000): written by
-- triggers for links, extractions and checks; read only by the lab. `f5…` ids.

begin;
select plan(7);

insert into auth.users (id, email) values
    ('f5000000-0000-0000-0000-0000000000a1', 'ev.ada@lab.test'),
    ('f5000000-0000-0000-0000-0000000000a2', 'ev.bob@lab.test');
insert into public.profiles (id, display_name) values
    ('f5000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('f5000000-0000-0000-0000-0000000000a2', 'Bob') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('f5000000-0000-0000-0000-0000000000b1', 'Ev A', 'ev-a', 'f5000000-0000-0000-0000-0000000000a1'),
    ('f5000000-0000-0000-0000-0000000000b2', 'Ev B', 'ev-b', 'f5000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('f5000000-0000-0000-0000-0000000000b1', 'f5000000-0000-0000-0000-0000000000a1', 'owner'),
    ('f5000000-0000-0000-0000-0000000000b2', 'f5000000-0000-0000-0000-0000000000a2', 'owner');
insert into public.team_features (team_id, feature) values
    ('f5000000-0000-0000-0000-0000000000b1', 'clinical_trials'),
    ('f5000000-0000-0000-0000-0000000000b2', 'clinical_trials');
insert into public.trials (id, nct_id, title, registry, breast_cancer) values
    ('f5000000-0000-0000-0000-0000000000e1', 'NCT94000001', 'One', '{}', true);
insert into public.trial_posts (trial_id, team_id, source) values
    ('f5000000-0000-0000-0000-0000000000e1', 'f5000000-0000-0000-0000-0000000000b1', 'paper');
insert into public.papers (id, url, url_norm, title) values
    ('f5000000-0000-0000-0000-0000000000c1', 'http://ev/1', 'ev/1', 'P1');
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('f5000000-0000-0000-0000-0000000000c1', 'f5000000-0000-0000-0000-0000000000b1', 'f5000000-0000-0000-0000-0000000000a1', 'web');

-- A suggestion is not news; confirming it is.
insert into public.paper_trials (id, team_id, paper_id, trial_id, source, status) values
    ('f5000000-0000-0000-0000-0000000000d1', 'f5000000-0000-0000-0000-0000000000b1',
     'f5000000-0000-0000-0000-0000000000c1', 'f5000000-0000-0000-0000-0000000000e1', 'acronym_in_title', 'suggested');
select is_empty($$ select 1 from public.trial_events where trial_id = 'f5000000-0000-0000-0000-0000000000e1' $$,
    'a suggested link is not an event');

set local role authenticated;
set local request.jwt.claims to '{"sub":"f5000000-0000-0000-0000-0000000000a1"}';
update public.paper_trials set status = 'confirmed', reviewed_by = 'f5000000-0000-0000-0000-0000000000a1', reviewed_at = now()
 where id = 'f5000000-0000-0000-0000-0000000000d1';
select is((select actor from public.trial_events where kind = 'paper_linked'
            and trial_id = 'f5000000-0000-0000-0000-0000000000e1'),
    'f5000000-0000-0000-0000-0000000000a1'::uuid, 'confirming a link records it, with who');
reset role;

insert into public.trial_facts (team_id, trial_id, extraction_status) values
    ('f5000000-0000-0000-0000-0000000000b1', 'f5000000-0000-0000-0000-0000000000e1', 'running');
update public.trial_facts set extraction_status = 'done', extracted_at = now(), extraction = '{}'
 where trial_id = 'f5000000-0000-0000-0000-0000000000e1';
select is((select count(*)::int from public.trial_events where kind = 'extraction_done'
            and trial_id = 'f5000000-0000-0000-0000-0000000000e1'), 1, 'a finished extraction is recorded');
update public.trial_facts set updated_at = now() where trial_id = 'f5000000-0000-0000-0000-0000000000e1';
select is((select count(*)::int from public.trial_events where kind = 'extraction_done'
            and trial_id = 'f5000000-0000-0000-0000-0000000000e1'), 1, 'other edits record nothing');

set local role authenticated;
set local request.jwt.claims to '{"sub":"f5000000-0000-0000-0000-0000000000a1"}';
insert into public.trial_fact_reviews (team_id, trial_id, path, verified_by) values
    ('f5000000-0000-0000-0000-0000000000b1', 'f5000000-0000-0000-0000-0000000000e1', 'design', 'f5000000-0000-0000-0000-0000000000a1');
select is((select count(*)::int from public.trial_events where kind = 'values_verified'
            and trial_id = 'f5000000-0000-0000-0000-0000000000e1'), 1, 'a check is recorded');
select throws_ok($$ insert into public.trial_events (team_id, trial_id, kind)
    values ('f5000000-0000-0000-0000-0000000000b1', 'f5000000-0000-0000-0000-0000000000e1', 'results_posted') $$,
    '42501', null, 'members cannot write events');

set local request.jwt.claims to '{"sub":"f5000000-0000-0000-0000-0000000000a2"}';
select is_empty($$ select 1 from public.trial_events where team_id = 'f5000000-0000-0000-0000-0000000000b1' $$,
    'another lab sees none of them');
reset role;

select * from finish();
rollback;
