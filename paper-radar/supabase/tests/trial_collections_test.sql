-- trial_collections_test.sql — collections (20261019180000): any member edits,
-- creator or owner deletes, only the lab's trials and papers go in, other labs
-- see nothing, and removals and merges keep them consistent. `f3…` ids.

begin;
select plan(20);

-- Ada (owner) and Cy (member) in Lab A, which has the feature. Bob in Lab B.
insert into auth.users (id, email) values
    ('f3000000-0000-0000-0000-0000000000a1', 'tc.ada@lab.test'),
    ('f3000000-0000-0000-0000-0000000000a2', 'tc.bob@lab.test'),
    ('f3000000-0000-0000-0000-0000000000a3', 'tc.cy@lab.test');
insert into public.profiles (id, display_name) values
    ('f3000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('f3000000-0000-0000-0000-0000000000a2', 'Bob'),
    ('f3000000-0000-0000-0000-0000000000a3', 'Cy') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('f3000000-0000-0000-0000-0000000000b1', 'Coll A', 'coll-a', 'f3000000-0000-0000-0000-0000000000a1'),
    ('f3000000-0000-0000-0000-0000000000b2', 'Coll B', 'coll-b', 'f3000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('f3000000-0000-0000-0000-0000000000b1', 'f3000000-0000-0000-0000-0000000000a1', 'owner'),
    ('f3000000-0000-0000-0000-0000000000b1', 'f3000000-0000-0000-0000-0000000000a3', 'member'),
    ('f3000000-0000-0000-0000-0000000000b2', 'f3000000-0000-0000-0000-0000000000a2', 'owner');
insert into public.team_features (team_id, feature) values
    ('f3000000-0000-0000-0000-0000000000b1', 'clinical_trials'),
    ('f3000000-0000-0000-0000-0000000000b2', 'clinical_trials');

insert into public.trials (id, nct_id, title, registry, breast_cancer) values
    ('f3000000-0000-0000-0000-0000000000e1', 'NCT92000001', 'One', '{}', true),
    ('f3000000-0000-0000-0000-0000000000e2', 'NCT92000002', 'Two', '{}', true),
    ('f3000000-0000-0000-0000-0000000000e3', 'NCT92000003', 'Three', '{}', true);
-- Lab A follows T1 and T2; T3 only Lab B.
insert into public.trial_posts (trial_id, team_id, source) values
    ('f3000000-0000-0000-0000-0000000000e1', 'f3000000-0000-0000-0000-0000000000b1', 'paper'),
    ('f3000000-0000-0000-0000-0000000000e2', 'f3000000-0000-0000-0000-0000000000b1', 'paper'),
    ('f3000000-0000-0000-0000-0000000000e3', 'f3000000-0000-0000-0000-0000000000b2', 'paper');
insert into public.papers (id, url, url_norm, title) values
    ('f3000000-0000-0000-0000-0000000000c1', 'http://tc/1', 'tc/1', 'Meta-analysis'),
    ('f3000000-0000-0000-0000-0000000000c2', 'http://tc/2', 'tc/2', 'Meta-analysis, published'),
    ('f3000000-0000-0000-0000-0000000000c3', 'http://tc/3', 'tc/3', 'Lab B paper');
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('f3000000-0000-0000-0000-0000000000c1', 'f3000000-0000-0000-0000-0000000000b1', 'f3000000-0000-0000-0000-0000000000a1', 'web'),
    ('f3000000-0000-0000-0000-0000000000c2', 'f3000000-0000-0000-0000-0000000000b1', 'f3000000-0000-0000-0000-0000000000a1', 'web'),
    ('f3000000-0000-0000-0000-0000000000c3', 'f3000000-0000-0000-0000-0000000000b2', 'f3000000-0000-0000-0000-0000000000a2', 'web');

-- === Ada creates and fills a collection ======================================
set local role authenticated;
set local request.jwt.claims to '{"sub":"f3000000-0000-0000-0000-0000000000a1"}';

select throws_ok($$ select public.create_collection('f3000000-0000-0000-0000-0000000000b1', 'Mixed', null,
    '{}', '{}', '{}', null, array['f3000000-0000-0000-0000-0000000000e1', 'f3000000-0000-0000-0000-0000000000e3']::uuid[]) $$,
    '42501', null, 'create_collection refuses a trial the lab does not follow');
select is_empty($$ select 1 from public.trial_collections where title = 'Mixed' $$,
    'and leaves no empty collection behind');
reset role;
-- A fixed id for the rest of the test (ids aren't client-writable).
insert into public.trial_collections (id, team_id, title, settings, created_by)
values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000b1',
        'Neoadjuvant immunotherapy in TNBC', '{neoadjuvant}', 'f3000000-0000-0000-0000-0000000000a1');
set local role authenticated;
select throws_ok($$ insert into public.trial_collections (team_id, title, created_by, updated_at)
    values ('f3000000-0000-0000-0000-0000000000b1', 'Backdated', 'f3000000-0000-0000-0000-0000000000a1', '2020-01-01') $$,
    '42501', null, 'timestamps are not the browser''s to set');
select lives_ok($$ insert into public.collection_trials (collection_id, trial_id, added_by)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000e1', 'f3000000-0000-0000-0000-0000000000a1'),
           ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000e2', 'f3000000-0000-0000-0000-0000000000a1') $$,
    'and adds two of the lab''s trials');
select throws_ok($$ insert into public.collection_trials (collection_id, trial_id, added_by)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000e3', 'f3000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'a trial the lab does not follow cannot go in');
select lives_ok($$ insert into public.collection_papers (collection_id, paper_id, added_by)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000c1', 'f3000000-0000-0000-0000-0000000000a1') $$,
    'a lab paper about the question goes in');
select throws_ok($$ insert into public.collection_papers (collection_id, paper_id, added_by)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000c3', 'f3000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'another lab''s paper cannot');
select lives_ok($$ insert into public.collection_notes (collection_id, author_id, body)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000a1', 'Read NeoTRIP with stage in mind.') $$,
    'Ada writes a note');

-- === Cy, a member, edits but can't delete ====================================
set local request.jwt.claims to '{"sub":"f3000000-0000-0000-0000-0000000000a3"}';

select lives_ok($$ update public.trial_collections set title = 'Neoadjuvant IO in TNBC'
    where id = 'f3000000-0000-0000-0000-0000000000d1' $$, 'Cy edits the title');
select is((select updated_by from public.trial_collections where id = 'f3000000-0000-0000-0000-0000000000d1'),
    'f3000000-0000-0000-0000-0000000000a3'::uuid, 'and the database records Cy as the last editor');
select throws_ok($$ update public.trial_collections set team_id = 'f3000000-0000-0000-0000-0000000000b2'
    where id = 'f3000000-0000-0000-0000-0000000000d1' $$, '42501', null, 'nobody moves it to another lab');
select lives_ok($$ insert into public.collection_followers (collection_id, user_id)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000a3') $$, 'Cy follows it');
select throws_ok($$ insert into public.collection_followers (collection_id, user_id)
    values ('f3000000-0000-0000-0000-0000000000d1', 'f3000000-0000-0000-0000-0000000000a1') $$,
    '42501', null, 'but cannot follow it on Ada''s behalf');
select is_empty($$ delete from public.collection_notes returning 1 $$, 'nor delete Ada''s note');
select is_empty($$ delete from public.trial_collections where id = 'f3000000-0000-0000-0000-0000000000d1' returning 1 $$,
    'nor delete the collection');

-- === Bob, another lab ========================================================
set local request.jwt.claims to '{"sub":"f3000000-0000-0000-0000-0000000000a2"}';
select is_empty($$ select 1 from public.trial_collections where id = 'f3000000-0000-0000-0000-0000000000d1' $$,
    'Bob sees nothing of it');
select is_empty($$ select 1 from public.collection_notes where collection_id = 'f3000000-0000-0000-0000-0000000000d1' $$,
    'nor its notes');

reset role;

-- === consistency =============================================================
delete from public.trial_posts
 where team_id = 'f3000000-0000-0000-0000-0000000000b1' and trial_id = 'f3000000-0000-0000-0000-0000000000e2';
select set_eq($$ select trial_id from public.collection_trials where collection_id = 'f3000000-0000-0000-0000-0000000000d1' $$,
    $$ values ('f3000000-0000-0000-0000-0000000000e1'::uuid) $$,
    'a trial taken off the lab''s list leaves its collections');

select public.merge_papers('f3000000-0000-0000-0000-0000000000c1', 'f3000000-0000-0000-0000-0000000000c2', 'manual');
select set_eq($$ select paper_id from public.collection_papers where collection_id = 'f3000000-0000-0000-0000-0000000000d1' $$,
    $$ values ('f3000000-0000-0000-0000-0000000000c2'::uuid) $$,
    'a merged paper stays in the collection as the kept paper');

-- Ada (creator, owner) deletes it.
set local role authenticated;
set local request.jwt.claims to '{"sub":"f3000000-0000-0000-0000-0000000000a1"}';
select isnt_empty($$ delete from public.trial_collections where id = 'f3000000-0000-0000-0000-0000000000d1' returning 1 $$,
    'the creator deletes it');
reset role;

select * from finish();
rollback;
