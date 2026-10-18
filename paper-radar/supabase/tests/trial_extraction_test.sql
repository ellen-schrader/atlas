-- trial_extraction_test.sql — sources, corrections and checks (20261019190000,
-- 20261019190500): only the lab, only uploads by members, every correction
-- logged, the files invisible to other labs. `f4…` ids.

begin;
select plan(16);

insert into auth.users (id, email) values
    ('f4000000-0000-0000-0000-0000000000a1', 'te.ada@lab.test'),
    ('f4000000-0000-0000-0000-0000000000a2', 'te.bob@lab.test');
insert into public.profiles (id, display_name) values
    ('f4000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('f4000000-0000-0000-0000-0000000000a2', 'Bob') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('f4000000-0000-0000-0000-0000000000b1', 'Ext A', 'ext-a', 'f4000000-0000-0000-0000-0000000000a1'),
    ('f4000000-0000-0000-0000-0000000000b2', 'Ext B', 'ext-b', 'f4000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000a1', 'owner'),
    ('f4000000-0000-0000-0000-0000000000b2', 'f4000000-0000-0000-0000-0000000000a2', 'owner');
insert into public.team_features (team_id, feature) values
    ('f4000000-0000-0000-0000-0000000000b1', 'clinical_trials'),
    ('f4000000-0000-0000-0000-0000000000b2', 'clinical_trials');
insert into public.trials (id, nct_id, title, registry, breast_cancer) values
    ('f4000000-0000-0000-0000-0000000000e1', 'NCT93000001', 'One', '{}', true);
insert into public.trial_posts (trial_id, team_id, source) values
    ('f4000000-0000-0000-0000-0000000000e1', 'f4000000-0000-0000-0000-0000000000b1', 'paper');
insert into public.trial_facts (team_id, trial_id, extraction, extraction_status) values
    ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000e1',
     '{"endpoints": [{"name": "pCR", "exp_value": 58, "ctrl_value": 41}], "enrolment": {"n_randomised": 333}}',
     'done');
insert into public.trial_fact_reviews (team_id, trial_id, path, verified_by) values
    ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000e1',
     'endpoints.0.exp_value', 'f4000000-0000-0000-0000-0000000000a1');
-- A file in Lab A's folder (the bytes don't matter to the policies).
insert into storage.objects (bucket_id, name, owner) values
    ('trial-sources', 'f4000000-0000-0000-0000-0000000000b1/f4000000-0000-0000-0000-0000000000e1/a.pdf',
     'f4000000-0000-0000-0000-0000000000a1');

set local role authenticated;
set local request.jwt.claims to '{"sub":"f4000000-0000-0000-0000-0000000000a1"}';

select lives_ok($$ insert into public.trial_sources (team_id, trial_id, kind, origin, storage_path, filename, media_type, bytes, added_by)
    values ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000e1', 'paper', 'upload',
            'f4000000-0000-0000-0000-0000000000b1/f4000000-0000-0000-0000-0000000000e1/a.pdf', 'a.pdf',
            'application/pdf', 1000, 'f4000000-0000-0000-0000-0000000000a1') $$,
    'Ada records her upload');
select throws_ok($$ insert into public.trial_sources (team_id, trial_id, kind, origin, storage_path, filename, media_type, bytes, added_by)
    values ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000e1', 'paper', 'upload',
            'f4000000-0000-0000-0000-0000000000b2/x/b.pdf', 'b.pdf',
            'application/pdf', 1000, 'f4000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'only at the lab''s own path');
select throws_ok($$ insert into public.trial_sources (team_id, trial_id, kind, origin, storage_path, filename, media_type, bytes, added_by)
    values ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000e1', 'paper', 'europepmc',
            'f4000000-0000-0000-0000-0000000000b1/f4000000-0000-0000-0000-0000000000e1/c.xml', 'c.xml',
            'application/xml', 1000, 'f4000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'Europe PMC rows are Atlas''s, not a member''s');
select is((select count(*)::int from storage.objects where bucket_id = 'trial-sources'
            and name like 'f4000000-0000-0000-0000-0000000000b1/%'), 1, 'Ada sees her lab''s file');

select throws_ok($$ update public.trial_facts set extraction = '{}' where trial_id = 'f4000000-0000-0000-0000-0000000000e1' $$,
    '42501', null, 'the extraction is not writable directly');
select lives_ok($$ select public.edit_trial_fact('f4000000-0000-0000-0000-0000000000b1',
    'f4000000-0000-0000-0000-0000000000e1', 'endpoints.0.exp_value', '58.1') $$, 'a correction goes through edit_trial_fact');
select is((select extraction #>> '{endpoints,0,exp_value}' from public.trial_facts
            where trial_id = 'f4000000-0000-0000-0000-0000000000e1'), '58.1', 'and is stored');
select is((select old_value from public.trial_fact_edits where trial_id = 'f4000000-0000-0000-0000-0000000000e1'),
    '58'::jsonb, 'with the old value logged');
select is_empty($$ select 1 from public.trial_fact_reviews where path = 'endpoints.0.exp_value'
                    and trial_id = 'f4000000-0000-0000-0000-0000000000e1' $$,
    'and its check cleared');
select throws_ok($$ select public.edit_trial_fact('f4000000-0000-0000-0000-0000000000b1',
    'f4000000-0000-0000-0000-0000000000e1', 'endpoints.5.exp_value', '1') $$, '22023', null,
    'an edit never invents structure');
select throws_ok($$ select public.edit_trial_fact('f4000000-0000-0000-0000-0000000000b1',
    'f4000000-0000-0000-0000-0000000000e1', 'endpoints.0.''x', '1') $$, '22023', null, 'paths are checked');
select lives_ok($$ insert into public.trial_fact_reviews (team_id, trial_id, path, verified_by)
    values ('f4000000-0000-0000-0000-0000000000b1', 'f4000000-0000-0000-0000-0000000000e1',
            'enrolment', 'f4000000-0000-0000-0000-0000000000a1') $$, 'Ada verifies a group');

-- === Bob, another lab ========================================================
set local request.jwt.claims to '{"sub":"f4000000-0000-0000-0000-0000000000a2"}';
select is_empty($$ select 1 from storage.objects where bucket_id = 'trial-sources'
                    and name like 'f4000000-0000-0000-0000-0000000000b1/%' $$, 'Bob cannot see Lab A''s files');
select is_empty($$ select 1 from public.trial_sources where team_id = 'f4000000-0000-0000-0000-0000000000b1' $$,
    'nor its sources');
select throws_ok($$ select public.edit_trial_fact('f4000000-0000-0000-0000-0000000000b1',
    'f4000000-0000-0000-0000-0000000000e1', 'enrolment.n_randomised', '1') $$, '42501', null,
    'nor correct its values');
select throws_ok($$ insert into storage.objects (bucket_id, name, owner) values
    ('trial-sources', 'f4000000-0000-0000-0000-0000000000b1/f4000000-0000-0000-0000-0000000000e1/evil.pdf',
     'f4000000-0000-0000-0000-0000000000a2') $$, '42501', null, 'nor upload into its folder');

reset role;
select * from finish();
rollback;
