-- cross_lab_leaks_test.sql — a lab holding a shared paper sees its correction
-- history and preprint link, but not who in another lab corrected or merged it
-- (issue #133, 20261018200000_cross_lab_leaks.sql). Run with `supabase test db`.

begin;
select plan(11);

-- Ada in lab L1 corrected the preprint and merged it into the published paper.
-- Bo in lab L2 holds only the published paper.
insert into auth.users (id, email) values
    ('e8000000-0000-0000-0000-0000000000a1', 'leak.ada@lab.test'),
    ('e8000000-0000-0000-0000-0000000000a2', 'leak.bo@lab.test');
insert into public.profiles (id, display_name) values
    ('e8000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('e8000000-0000-0000-0000-0000000000a2', 'Bo') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('e8000000-0000-0000-0000-0000000000b1', 'Leak One', 'leak-one', 'e8000000-0000-0000-0000-0000000000a1'),
    ('e8000000-0000-0000-0000-0000000000b2', 'Leak Two', 'leak-two', 'e8000000-0000-0000-0000-0000000000a2');
insert into public.team_members (team_id, user_id, role) values
    ('e8000000-0000-0000-0000-0000000000b1', 'e8000000-0000-0000-0000-0000000000a1', 'owner'),
    ('e8000000-0000-0000-0000-0000000000b2', 'e8000000-0000-0000-0000-0000000000a2', 'owner');

insert into public.papers (id, doi, url, url_norm, title, venue) values
    ('e8000000-0000-0000-0000-0000000000c1', '10.1101/2025.02.02.000001',
     'https://www.biorxiv.org/content/10.1101/2025.02.02.000001v1', 'leak/preprint', 'Preprint', 'bioRxiv'),
    ('e8000000-0000-0000-0000-0000000000c2', '10.1038/s00000-025-00002-x',
     'https://www.nature.com/articles/s00000-025-00002-x', 'leak/published', 'Published', 'Nature');
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('e8000000-0000-0000-0000-0000000000c1', 'e8000000-0000-0000-0000-0000000000b1', 'e8000000-0000-0000-0000-0000000000a1', 'web'),
    ('e8000000-0000-0000-0000-0000000000c2', 'e8000000-0000-0000-0000-0000000000b2', 'e8000000-0000-0000-0000-0000000000a2', 'web');

select public.apply_paper_edit('e8000000-0000-0000-0000-0000000000c1', 'e8000000-0000-0000-0000-0000000000a1',
    'edit', null, '{"title": "Preprint, fixed"}', '["title"]');
select public.merge_papers('e8000000-0000-0000-0000-0000000000c1', 'e8000000-0000-0000-0000-0000000000c2', 'manual');
update public.paper_aliases set merged_by = 'e8000000-0000-0000-0000-0000000000a1'
 where old_paper_id = 'e8000000-0000-0000-0000-0000000000c1';

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

-- The history travelled with the merge, and its content is readable.
select is((select after ->> 'title' from public.paper_edits where paper_id = 'e8000000-0000-0000-0000-0000000000c2'),
    'Preprint, fixed', 'the correction history is visible to every lab holding the paper');
select throws_ok($$ select edited_by from public.paper_edits $$, '42501', null,
    'who corrected it is not readable');
select throws_ok($$ select * from public.paper_edits $$, '42501', null,
    'select * on the history is refused');

-- === the service role (repairing a merge by hand) ============================

reset role;
set local role service_role;

select is((select snapshot ->> 'edited_by' from public.paper_aliases
            where old_paper_id = 'e8000000-0000-0000-0000-0000000000c1'),
    'e8000000-0000-0000-0000-0000000000a1', 'the service role still reads the snapshot');
select is((select edited_by from public.paper_edits where paper_id = 'e8000000-0000-0000-0000-0000000000c2'),
    'e8000000-0000-0000-0000-0000000000a1'::uuid, 'the service role still reads who edited');

select * from finish();
rollback;
