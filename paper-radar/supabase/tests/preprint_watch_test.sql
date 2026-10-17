-- preprint_watch_test.sql — promote_to_published turns a preprint into its
-- published version in place; notifications are private to their person;
-- any member of the lab can merge or dismiss a merge suggestion, nobody else.
-- Isolated id space so it rolls back cleanly anywhere.

begin;
select plan(25);

-- Ada and Bo in lab B1, Cy alone in lab B2.
insert into auth.users (id, email) values
    ('e9000000-0000-0000-0000-0000000000a1', 'pw.ada@lab.test'),
    ('e9000000-0000-0000-0000-0000000000a2', 'pw.bo@lab.test'),
    ('e9000000-0000-0000-0000-0000000000a3', 'pw.cy@lab.test');
insert into public.profiles (id, display_name) values
    ('e9000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('e9000000-0000-0000-0000-0000000000a2', 'Bo'),
    ('e9000000-0000-0000-0000-0000000000a3', 'Cy') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('e9000000-0000-0000-0000-0000000000b1', 'PW Lab', 'pw-lab', 'e9000000-0000-0000-0000-0000000000a1'),
    ('e9000000-0000-0000-0000-0000000000b2', 'PW Two', 'pw-two', 'e9000000-0000-0000-0000-0000000000a3');
insert into public.team_members (team_id, user_id, role) values
    ('e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000a1', 'owner'),
    ('e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000a2', 'member'),
    ('e9000000-0000-0000-0000-0000000000b2', 'e9000000-0000-0000-0000-0000000000a3', 'owner');

-- c1: a bioRxiv preprint whose venue a person set by hand. c2/c3: a suggested
-- pair. c4: holds a DOI, for the conflict check.
insert into public.papers (id, doi, url, url_norm, title, venue, year, abstract, edited_fields, embedded_at, enriched_at) values
    ('e9000000-0000-0000-0000-0000000000c1', '10.1101/2025.02.02.000001',
     'https://www.biorxiv.org/content/10.1101/2025.02.02.000001v1', 'pw/pre',
     'Preprint title', 'bioRxiv (hand)', 2025, 'Preprint abstract.', '["venue"]', now(), now()),
    ('e9000000-0000-0000-0000-0000000000c2', '10.1101/2025.03.03.000002', 'https://x/pre2', 'pw/pre2',
     'Same paper', 'bioRxiv', 2025, null, '[]', null, null),
    ('e9000000-0000-0000-0000-0000000000c3', '10.1038/pw-published', 'https://x/pub2', 'pw/pub2',
     'Same paper', 'Nature', 2026, null, '[]', null, null),
    ('e9000000-0000-0000-0000-0000000000c4', '10.1016/pw-taken', 'https://x/taken', 'pw/taken',
     'Taken', 'Cell', 2026, null, '[]', null, null);
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('e9000000-0000-0000-0000-0000000000c1', 'e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000a1', 'web'),
    ('e9000000-0000-0000-0000-0000000000c2', 'e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000a2', 'web'),
    ('e9000000-0000-0000-0000-0000000000c3', 'e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000a1', 'web');

-- === promote_to_published ==================================================

-- A pending suggestion treating c1 as a preprint.
insert into public.merge_suggestions (team_id, preprint_id, published_id, score, status) values
    ('e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000c1',
     'e9000000-0000-0000-0000-0000000000c4', 0.9, 'pending');

select throws_ok(
    $$ select public.promote_to_published('e9000000-0000-0000-0000-0000000000c1',
         '{"doi":"10.1016/pw-taken","url":"https://doi.org/10.1016/pw-taken","url_norm":"pw/new"}', 'crossref') $$,
    '23505', null, 'a DOI another paper holds is refused (the job merges instead)');

select lives_ok(
    $$ select public.promote_to_published('e9000000-0000-0000-0000-0000000000c1',
         '{"doi":"10.1016/pw-published","url":"https://doi.org/10.1016/pw-published",
           "url_norm":"//doi.org/10.1016/pw-published","title":"Published title","venue":"Cell",
           "year":2026,"abstract":null,"authors":["Ada Lovelace"],"metadata_source":"crossref"}',
         'crossref') $$,
    'a preprint is promoted to its published version');

select is((select doi || ' | ' || url_norm || ' | ' || title || ' | ' || year from public.papers
            where id = 'e9000000-0000-0000-0000-0000000000c1'),
    '10.1016/pw-published | //doi.org/10.1016/pw-published | Published title | 2026',
    'same id, published identity and record');
select is((select venue from public.papers where id = 'e9000000-0000-0000-0000-0000000000c1'),
    'bioRxiv (hand)', 'a field a person edited is kept');
select is((select abstract from public.papers where id = 'e9000000-0000-0000-0000-0000000000c1'),
    'Preprint abstract.', 'a missing value in the published record never blanks a field');
select is((select embedded_at is null and enriched_at is null from public.papers
            where id = 'e9000000-0000-0000-0000-0000000000c1'),
    true, 'a new title queues re-embedding and re-tagging');
select is((select kind || ' | ' || reason || ' | ' || doi || ' | ' || url_norm from public.paper_aliases
            where paper_id = 'e9000000-0000-0000-0000-0000000000c1'),
    'preprint | crossref | 10.1101/2025.02.02.000001 | pw/pre', 'the preprint is kept as an alias');
select is((select count(*)::int from public.merge_suggestions
            where preprint_id = 'e9000000-0000-0000-0000-0000000000c1'),
    0, 'a promoted paper is no longer offered as the preprint of another');
select is((select after ->> 'title' from public.paper_edits
            where paper_id = 'e9000000-0000-0000-0000-0000000000c1' and kind = 'resolve'),
    'Published title', 'the change is in the paper''s history');

-- === notifications =========================================================

insert into public.notifications (id, user_id, team_id, paper_id, kind, payload) values
    ('e9000000-0000-0000-0000-0000000000d1', 'e9000000-0000-0000-0000-0000000000a1',
     'e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000c2',
     'preprint_published', '{"title":"Same paper"}');

set local role authenticated;
set local request.jwt.claims to '{"sub":"e9000000-0000-0000-0000-0000000000a2"}';
select is((select count(*)::int from public.notifications), 0, 'nobody sees another person''s notifications');

set local request.jwt.claims to '{"sub":"e9000000-0000-0000-0000-0000000000a1"}';
select is((select count(*)::int from public.notifications), 1, 'you see your own');
select lives_ok(
    $$ update public.notifications set seen_at = now() where id = 'e9000000-0000-0000-0000-0000000000d1' $$,
    'and can mark it seen');
select throws_ok(
    $$ update public.notifications set payload = '{}' where id = 'e9000000-0000-0000-0000-0000000000d1' $$,
    '42501', null, 'but not rewrite it');
select throws_ok(
    $$ select public.promote_to_published('e9000000-0000-0000-0000-0000000000c2', '{}', 'manual') $$,
    '42501', null, 'members cannot promote papers');
reset role;

-- === merge suggestions =====================================================

-- Ada was told about both papers of the pair: the merge must not collide.
insert into public.notifications (id, user_id, team_id, paper_id, kind) values
    ('e9000000-0000-0000-0000-0000000000d2', 'e9000000-0000-0000-0000-0000000000a1',
     'e9000000-0000-0000-0000-0000000000b1', 'e9000000-0000-0000-0000-0000000000c3',
     'preprint_published');

insert into public.merge_suggestions (id, team_id, preprint_id, published_id, score) values
    ('e9000000-0000-0000-0000-0000000000e1', 'e9000000-0000-0000-0000-0000000000b1',
     'e9000000-0000-0000-0000-0000000000c2', 'e9000000-0000-0000-0000-0000000000c3', 0.97);

set local role authenticated;
set local request.jwt.claims to '{"sub":"e9000000-0000-0000-0000-0000000000a3"}';
select is((select count(*)::int from public.merge_suggestions), 0, 'another lab cannot see the suggestion');
select throws_ok(
    $$ select public.decide_merge_suggestion('e9000000-0000-0000-0000-0000000000e1', true) $$,
    '42501', null, 'nor act on it');

set local request.jwt.claims to '{"sub":"e9000000-0000-0000-0000-0000000000a2"}';
select is(public.decide_merge_suggestion('e9000000-0000-0000-0000-0000000000e1', false),
    'dismissed', 'a plain member can say they are not the same');
select throws_ok(
    $$ select public.decide_merge_suggestion('e9000000-0000-0000-0000-0000000000e1', true) $$,
    '55000', null, 'an answered suggestion cannot be answered again');
reset role;

-- Asked again (say a later run found a closer match): Bo merges this time.
update public.merge_suggestions set status = 'pending', decided_by = null, decided_at = null
 where id = 'e9000000-0000-0000-0000-0000000000e1';

set local role authenticated;
set local request.jwt.claims to '{"sub":"e9000000-0000-0000-0000-0000000000a2"}';
select is(public.decide_merge_suggestion('e9000000-0000-0000-0000-0000000000e1', true),
    'merged', 'a plain member can merge');
reset role;

select is((select count(*)::int from public.papers where id = 'e9000000-0000-0000-0000-0000000000c2'), 0,
    'the preprint row is gone');
select is((select merged_by from public.paper_aliases where old_paper_id = 'e9000000-0000-0000-0000-0000000000c2'),
    'e9000000-0000-0000-0000-0000000000a2'::uuid, 'the alias records who merged it');
select is((select reason from public.paper_aliases where old_paper_id = 'e9000000-0000-0000-0000-0000000000c2'),
    'manual', 'as a manual merge');
select is((select count(*)::int from public.notifications
            where user_id = 'e9000000-0000-0000-0000-0000000000a1'
              and paper_id = 'e9000000-0000-0000-0000-0000000000c3'),
    1, 'a person told about both papers keeps one notice, on the kept paper');
select is((select count(*)::int from public.notifications where id = 'e9000000-0000-0000-0000-0000000000d1'),
    0, 'the duplicate notice goes');
select is((select count(*)::int from public.merge_suggestions where id = 'e9000000-0000-0000-0000-0000000000e1'), 0,
    'the suggestion goes with the preprint');

select * from finish();
rollback;
