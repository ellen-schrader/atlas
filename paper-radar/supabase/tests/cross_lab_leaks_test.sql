-- cross_lab_leaks_test.sql — a lab holding a shared paper sees its correction
-- history and preprint link, but not who in another lab corrected or merged it
-- (issue #133, 20261018200000_cross_lab_leaks.sql). Run with `supabase test db`.

begin;
select plan(24);

-- Ada in lab L1 corrected the preprint, merged it into the published paper and
-- corrected that too. Cy is in her lab. Bo in lab L2 holds only the published
-- paper. P3 is held by L1 alone.
insert into auth.users (id, email) values
    ('e8000000-0000-0000-0000-0000000000a1', 'leak.ada@lab.test'),
    ('e8000000-0000-0000-0000-0000000000a2', 'leak.bo@lab.test'),
    ('e8000000-0000-0000-0000-0000000000a3', 'leak.cy@lab.test');
insert into public.profiles (id, display_name) values
    ('e8000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('e8000000-0000-0000-0000-0000000000a2', 'Bo'),
    ('e8000000-0000-0000-0000-0000000000a3', 'Cy')
    on conflict (id) do update set display_name = excluded.display_name;
insert into public.teams (id, name, slug, created_by) values
    ('e8000000-0000-0000-0000-0000000000b1', 'Leak One', 'leak-one', 'e8000000-0000-0000-0000-0000000000a1'),
    ('e8000000-0000-0000-0000-0000000000b2', 'Leak Two', 'leak-two', 'e8000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('e8000000-0000-0000-0000-0000000000b1', 'e8000000-0000-0000-0000-0000000000a1', 'owner'),
    ('e8000000-0000-0000-0000-0000000000b2', 'e8000000-0000-0000-0000-0000000000a2', 'owner'),
    ('e8000000-0000-0000-0000-0000000000b1', 'e8000000-0000-0000-0000-0000000000a3', 'member');

insert into public.papers (id, doi, url, url_norm, title, venue) values
    ('e8000000-0000-0000-0000-0000000000c1', '10.1101/2025.02.02.000001',
     'https://www.biorxiv.org/content/10.1101/2025.02.02.000001v1', 'leak/preprint', 'Preprint', 'bioRxiv'),
    ('e8000000-0000-0000-0000-0000000000c2', '10.1038/s00000-025-00002-x',
     'https://www.nature.com/articles/s00000-025-00002-x', 'leak/published', 'Published', 'Nature'),
    ('e8000000-0000-0000-0000-0000000000c3', null, 'https://example.org/p3', 'leak/p3', 'Only L1', null);
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('e8000000-0000-0000-0000-0000000000c1', 'e8000000-0000-0000-0000-0000000000b1', 'e8000000-0000-0000-0000-0000000000a1', 'web'),
    ('e8000000-0000-0000-0000-0000000000c2', 'e8000000-0000-0000-0000-0000000000b2', 'e8000000-0000-0000-0000-0000000000a2', 'web'),
    ('e8000000-0000-0000-0000-0000000000c3', 'e8000000-0000-0000-0000-0000000000b1', 'e8000000-0000-0000-0000-0000000000a1', 'web');

select public.apply_paper_edit('e8000000-0000-0000-0000-0000000000c1', 'e8000000-0000-0000-0000-0000000000a1',
    'edit', null, '{"title": "Preprint, fixed"}', '["title"]');
insert into public.merge_suggestions (id, team_id, preprint_id, published_id, score) values
    ('e8000000-0000-0000-0000-0000000000e1', 'e8000000-0000-0000-0000-0000000000b1',
     'e8000000-0000-0000-0000-0000000000c1', 'e8000000-0000-0000-0000-0000000000c2', 0.95);

-- Ada confirms the merge the way the app does, which records her as merged_by.
set local role authenticated;
set local request.jwt.claims to '{"sub":"e8000000-0000-0000-0000-0000000000a1"}';
select public.decide_merge_suggestion('e8000000-0000-0000-0000-0000000000e1', true);
reset role;

select public.apply_paper_edit('e8000000-0000-0000-0000-0000000000c2', 'e8000000-0000-0000-0000-0000000000a1',
    'edit', null, '{"venue": "Nature Methods"}', '["venue"]');
select public.apply_paper_edit('e8000000-0000-0000-0000-0000000000c3', 'e8000000-0000-0000-0000-0000000000a1',
    'edit', null, '{"title": "Only L1, fixed"}', '["title"]');

-- === nothing else is hidden by accident ======================================

-- A column added to paper_edits or paper_aliases later starts hidden from
-- members. If one of these fails after your migration, grant the new column to
-- authenticated — or, if it really says who in another lab did something, add
-- it here and in 20261018200000_cross_lab_leaks.sql.
select is((select string_agg(attname, ', ' order by attname) from pg_attribute
            where attrelid = 'public.papers'::regclass and attnum > 0 and not attisdropped
              and not has_column_privilege('authenticated', attrelid, attname, 'SELECT')),
    null, 'members can read every papers column');
select is((select string_agg(attname, ', ' order by attname) from pg_attribute
            where attrelid = 'public.paper_edits'::regclass and attnum > 0 and not attisdropped
              and not has_column_privilege('authenticated', attrelid, attname, 'SELECT')),
    'edited_by', 'members can read every paper_edits column except edited_by');
select is((select string_agg(attname, ', ' order by attname) from pg_attribute
            where attrelid = 'public.paper_aliases'::regclass and attnum > 0 and not attisdropped
              and not has_column_privilege('authenticated', attrelid, attname, 'SELECT')),
    'merged_by, reason, snapshot', 'members can read every paper_aliases column except these');

-- === Bo, in the other lab ====================================================

set local role authenticated;
set local request.jwt.claims to '{"sub":"e8000000-0000-0000-0000-0000000000a2"}';

-- What the card and the old-link redirect read still works.
select is((select venue || ' ' || url from public.paper_aliases where paper_id = 'e8000000-0000-0000-0000-0000000000c2'),
    'bioRxiv https://www.biorxiv.org/content/10.1101/2025.02.02.000001v1',
    'the preprint link is visible to every lab holding the paper');
select is((select paper_id from public.paper_aliases where old_paper_id = 'e8000000-0000-0000-0000-0000000000c1'),
    'e8000000-0000-0000-0000-0000000000c2'::uuid, 'an old link still finds the kept paper');

select throws_ok($$ select snapshot from public.paper_aliases $$, '42501', null,
    'the merged-away row is not readable');
select throws_ok($$ select merged_by from public.paper_aliases $$, '42501', null,
    'who merged is not readable');
select throws_ok($$ select reason from public.paper_aliases $$, '42501', null,
    'why it was merged is not readable');
select throws_ok($$ select * from public.paper_aliases $$, '42501', null,
    'select * is refused, not quietly narrowed');

-- The paper itself: everything but who last edited it.
select is((select venue || ' ' || (edited_at is not null)::text from public.papers
            where id = 'e8000000-0000-0000-0000-0000000000c2'),
    'Nature Methods true', 'the paper and when it was edited are readable');
select is((select edited_by from public.papers where id = 'e8000000-0000-0000-0000-0000000000c2'), null,
    'papers.edited_by is no longer written');
select lives_ok($$ select * from public.papers $$, 'select * on papers still works');
select throws_ok($$ select * from public.paper_editors $$, '42501', null,
    'who edited each paper is not readable');

-- The card's "Edited … outside your lab".
select is((select row(is_you, in_your_lab, display_name)::text
             from public.paper_editor('e8000000-0000-0000-0000-0000000000c2')),
    '(f,f,)', 'an editor in another lab is neither you nor named');
select is((select count(*)::int from public.paper_editor('e8000000-0000-0000-0000-0000000000c3')), 0,
    'nothing about a paper the caller cannot see');

-- The history travelled with the merge, and its content is readable.
select is((select after ->> 'title' from public.paper_edits
            where paper_id = 'e8000000-0000-0000-0000-0000000000c2' and after ? 'title'),
    'Preprint, fixed', 'the correction history is visible to every lab holding the paper');
select throws_ok($$ select edited_by from public.paper_edits $$, '42501', null,
    'who corrected it is not readable');
select throws_ok($$ select * from public.paper_edits $$, '42501', null,
    'select * on the history is refused');

-- === Ada and Cy, in the editor's lab =========================================

set local request.jwt.claims to '{"sub":"e8000000-0000-0000-0000-0000000000a3"}';
select is((select row(is_you, in_your_lab, display_name)::text
             from public.paper_editor('e8000000-0000-0000-0000-0000000000c2')),
    '(f,t,Ada)', 'an editor in your own lab is named');
set local request.jwt.claims to '{"sub":"e8000000-0000-0000-0000-0000000000a1"}';
select is((select row(is_you, in_your_lab, display_name)::text
             from public.paper_editor('e8000000-0000-0000-0000-0000000000c2')),
    '(t,f,)', 'your own edit is yours');

-- === the service role (repairing a merge by hand) ============================

reset role;
set local role service_role;

select is((select edited_by from public.paper_editors where paper_id = 'e8000000-0000-0000-0000-0000000000c2'),
    'e8000000-0000-0000-0000-0000000000a1'::uuid, 'the edit recorded who made it');
select is((select merged_by from public.paper_aliases
            where old_paper_id = 'e8000000-0000-0000-0000-0000000000c1'),
    'e8000000-0000-0000-0000-0000000000a1'::uuid, 'the merge recorded who confirmed it');
select is((select snapshot ->> 'title' from public.paper_aliases
            where old_paper_id = 'e8000000-0000-0000-0000-0000000000c1'),
    'Preprint, fixed', 'the service role still reads the snapshot');
select is((select edited_by from public.paper_edits
            where paper_id = 'e8000000-0000-0000-0000-0000000000c2' and after ? 'title'),
    'e8000000-0000-0000-0000-0000000000a1'::uuid, 'the service role still reads who edited');

select * from finish();
rollback;
