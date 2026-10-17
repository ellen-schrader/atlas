-- paper_aliases_test.sql — merge_papers folds a preprint into its published
-- paper: collisions in a lab that held both are combined, everything else moves,
-- the kept paper gains only what it lacked, and the old row leaves an alias.
-- Isolated id space so it rolls back cleanly anywhere.

begin;
select plan(32);

-- Ada and Bo in lab B1, Cy alone in lab B2.
-- P1 = preprint (bioRxiv), P2 = published. B1 posted both, B2 only the preprint.
insert into auth.users (id, email) values
    ('e7000000-0000-0000-0000-0000000000a1', 'mrg.ada@lab.test'),
    ('e7000000-0000-0000-0000-0000000000a2', 'mrg.bo@lab.test'),
    ('e7000000-0000-0000-0000-0000000000a3', 'mrg.cy@lab.test');
insert into public.profiles (id, display_name) values
    ('e7000000-0000-0000-0000-0000000000a1', 'Ada'),
    ('e7000000-0000-0000-0000-0000000000a2', 'Bo'),
    ('e7000000-0000-0000-0000-0000000000a3', 'Cy') on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('e7000000-0000-0000-0000-0000000000b1', 'Mrg Lab', 'mrg-lab', 'e7000000-0000-0000-0000-0000000000a1'),
    ('e7000000-0000-0000-0000-0000000000b2', 'Mrg Two', 'mrg-two', 'e7000000-0000-0000-0000-0000000000a3');
insert into public.team_members (team_id, user_id, role) values
    ('e7000000-0000-0000-0000-0000000000b1', 'e7000000-0000-0000-0000-0000000000a1', 'owner'),
    ('e7000000-0000-0000-0000-0000000000b1', 'e7000000-0000-0000-0000-0000000000a2', 'member'),
    ('e7000000-0000-0000-0000-0000000000b2', 'e7000000-0000-0000-0000-0000000000a3', 'owner');

insert into public.papers (id, doi, url, url_norm, title, venue, abstract, code_url, data_url, keywords, tags, edited_fields) values
    ('e7000000-0000-0000-0000-0000000000c1', '10.1101/2025.01.01.000001',
     'https://www.biorxiv.org/content/10.1101/2025.01.01.000001v1', 'mrg/preprint',
     'Preprint title', 'bioRxiv', 'The preprint abstract.', 'https://github.com/x/y', 'https://zenodo.org/1',
     '["biology"]', '["spatial", "tumour"]', '[]'),
    ('e7000000-0000-0000-0000-0000000000c2', '10.1038/s00000-025-00001-x',
     'https://www.nature.com/articles/s00000-025-00001-x', 'mrg/published',
     'Published title', 'Nature', null, null, null,
     '[]', '["spatial", "immunology"]', '["data_url"]');

-- B1: preprint shared first by Bo from a Teams PDF with a note, published later
-- by Ada on the web.
insert into public.paper_posts (id, paper_id, team_id, posted_by, posted_at, source, source_pdf, page, note, tags) values
    ('e7000000-0000-0000-0000-0000000000d1', 'e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b1',
     'e7000000-0000-0000-0000-0000000000a2', '2025-01-05', 'teams_pdf', 'chat.pdf', 12, 'Read the methods', '["lab-a"]'),
    ('e7000000-0000-0000-0000-0000000000d2', 'e7000000-0000-0000-0000-0000000000c2', 'e7000000-0000-0000-0000-0000000000b1',
     'e7000000-0000-0000-0000-0000000000a1', '2025-09-01', 'web', null, null, null, '["lab-b"]'),
    ('e7000000-0000-0000-0000-0000000000d3', 'e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b2',
     'e7000000-0000-0000-0000-0000000000a3', '2025-02-01', 'web', null, null, null, '[]');

-- Ada reacted 👍 to both versions (collides) and 🔥 to the preprint only.
insert into public.reactions (paper_id, team_id, user_id, emoji) values
    ('e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b1', 'e7000000-0000-0000-0000-0000000000a1', '👍'),
    ('e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b1', 'e7000000-0000-0000-0000-0000000000a1', '🔥'),
    ('e7000000-0000-0000-0000-0000000000c2', 'e7000000-0000-0000-0000-0000000000b1', 'e7000000-0000-0000-0000-0000000000a1', '👍');

-- Ada read the preprint and saved neither... then saved the published one.
-- Bo saved the preprint only.
insert into public.paper_status (user_id, paper_id, team_id, saved, status) values
    ('e7000000-0000-0000-0000-0000000000a1', 'e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b1', false, 'read'),
    ('e7000000-0000-0000-0000-0000000000a1', 'e7000000-0000-0000-0000-0000000000c2', 'e7000000-0000-0000-0000-0000000000b1', true, 'unread'),
    ('e7000000-0000-0000-0000-0000000000a2', 'e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b1', true, 'unread');

insert into public.comments (id, paper_id, team_id, author_id, body) values
    ('e7000000-0000-0000-0000-0000000000e1', 'e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000b1',
     'e7000000-0000-0000-0000-0000000000a2', 'Figure 3 is wild');

-- A map pins the preprint and already pins the published paper.
insert into public.maps (id, team_id, created_by, name, seed, config, ai_summary) values
    ('e7000000-0000-0000-0000-0000000000f1', 'e7000000-0000-0000-0000-0000000000b1', 'e7000000-0000-0000-0000-0000000000a1',
     'Spatial', 's',
     '{"pinned":["e7000000-0000-0000-0000-0000000000c1","e7000000-0000-0000-0000-0000000000c2"],"excluded":[]}',
     '{"text":"x","cited_ids":["e7000000-0000-0000-0000-0000000000c1"]}');

select lives_ok(
    $$ select public.merge_papers('e7000000-0000-0000-0000-0000000000c1', 'e7000000-0000-0000-0000-0000000000c2', 'crossref') $$,
    'merge_papers runs');

-- The old row is gone; the alias remembers it.
select is((select count(*)::int from public.papers where id = 'e7000000-0000-0000-0000-0000000000c1'), 0,
    'the preprint row is deleted');
select is((select paper_id from public.paper_aliases where old_paper_id = 'e7000000-0000-0000-0000-0000000000c1'),
    'e7000000-0000-0000-0000-0000000000c2'::uuid, 'the alias points at the published paper');
select is((select kind || '/' || reason || '/' || doi || '/' || venue from public.paper_aliases
            where old_paper_id = 'e7000000-0000-0000-0000-0000000000c1'),
    'preprint/crossref/10.1101/2025.01.01.000001/bioRxiv', 'the alias keeps the preprint DOI and server');
select is((select snapshot ->> 'title' from public.paper_aliases where old_paper_id = 'e7000000-0000-0000-0000-0000000000c1'),
    'Preprint title', 'the alias snapshot holds the old row');

-- Posts: B1 had both and keeps one; B2's post moved.
select is((select count(*)::int from public.paper_posts where team_id = 'e7000000-0000-0000-0000-0000000000b1'
            and paper_id = 'e7000000-0000-0000-0000-0000000000c2'), 1, 'a lab that held both keeps one post');
select is((select posted_by from public.paper_posts where id = 'e7000000-0000-0000-0000-0000000000d2'),
    'e7000000-0000-0000-0000-0000000000a2'::uuid, 'the earlier sharer is credited');
select is((select posted_at from public.paper_posts where id = 'e7000000-0000-0000-0000-0000000000d2'),
    '2025-01-05'::timestamptz, 'the earlier share date is kept');
select is((select source || '/' || source_pdf || '/' || page from public.paper_posts
            where id = 'e7000000-0000-0000-0000-0000000000d2'),
    'teams_pdf/chat.pdf/12', 'the earlier share keeps its own source, not the later one''s');
select is((select note from public.paper_posts where id = 'e7000000-0000-0000-0000-0000000000d2'),
    'Read the methods', 'the note survives');
select set_eq(
    $$ select jsonb_array_elements_text(tags) from public.paper_posts where id = 'e7000000-0000-0000-0000-0000000000d2' $$,
    $$ values ('lab-a'), ('lab-b') $$, 'lab tags are combined');
select is((select paper_id from public.paper_posts where id = 'e7000000-0000-0000-0000-0000000000d3'),
    'e7000000-0000-0000-0000-0000000000c2'::uuid, 'a lab that held only the preprint keeps its post, moved');
select is((select count(*)::int from public.removed_posts where id = 'e7000000-0000-0000-0000-0000000000d1'), 0,
    'the folded post leaves no undo tombstone');

-- Reactions, reading status, comments.
select set_eq(
    $$ select emoji from public.reactions where paper_id = 'e7000000-0000-0000-0000-0000000000c2'
         and user_id = 'e7000000-0000-0000-0000-0000000000a1' $$,
    $$ values ('👍'), ('🔥') $$, 'reactions move, the duplicate is dropped');
select is((select saved::text || '/' || status from public.paper_status
            where user_id = 'e7000000-0000-0000-0000-0000000000a1' and paper_id = 'e7000000-0000-0000-0000-0000000000c2'),
    'true/read', 'colliding status: saved if either, the further progress');
select is((select saved from public.paper_status
            where user_id = 'e7000000-0000-0000-0000-0000000000a2' and paper_id = 'e7000000-0000-0000-0000-0000000000c2'),
    true, 'a status on the preprint only moves');
select is((select paper_id from public.comments where id = 'e7000000-0000-0000-0000-0000000000e1'),
    'e7000000-0000-0000-0000-0000000000c2'::uuid, 'comments move');

-- Maps hold paper ids in jsonb.
select is((select config -> 'pinned' from public.maps where id = 'e7000000-0000-0000-0000-0000000000f1'),
    '["e7000000-0000-0000-0000-0000000000c2"]'::jsonb, 'a pinned preprint becomes the published paper, once');
select is((select ai_summary -> 'cited_ids' from public.maps where id = 'e7000000-0000-0000-0000-0000000000f1'),
    '["e7000000-0000-0000-0000-0000000000c2"]'::jsonb, 'summary citations follow');

-- The kept paper keeps its record and gains only what it lacked.
select is((select title || '/' || venue || '/' || doi from public.papers where id = 'e7000000-0000-0000-0000-0000000000c2'),
    'Published title/Nature/10.1038/s00000-025-00001-x', 'the published record is kept');
select is((select abstract from public.papers where id = 'e7000000-0000-0000-0000-0000000000c2'),
    'The preprint abstract.', 'a missing abstract is filled from the preprint');
select is((select data_url from public.papers where id = 'e7000000-0000-0000-0000-0000000000c2'),
    null, 'a field a person edited is never filled');
select set_eq(
    $$ select jsonb_array_elements_text(tags) from public.papers where id = 'e7000000-0000-0000-0000-0000000000c2' $$,
    $$ values ('spatial'), ('tumour'), ('immunology') $$, 'AI tags are combined');

-- One DOI held twice, one after the other: a row merged away, then the same
-- paper posted again (before ingest read aliases) and merged a second time. The
-- second merge would write the alias DOI the first already holds. The kept row
-- failed to resolve, so the first merge also fills it.
insert into public.papers (id, doi, url, url_norm, title, authors, year, venue) values
    ('e7000000-0000-0000-0000-000000000011', '10.9999/mrg-abc', 'https://x/1', 'mrg/case-1', 'Case title', '["Ada Lovelace"]', 2024, 'Cell'),
    ('e7000000-0000-0000-0000-000000000013', null, 'https://x/3', 'mrg/case-3', null, '[]', null, null);

select lives_ok(
    $$ select public.merge_papers('e7000000-0000-0000-0000-000000000011', 'e7000000-0000-0000-0000-000000000013', 'doi_case') $$,
    'first DOI-case merge');
insert into public.papers (id, doi, url, url_norm, title, authors, year, venue) values
    ('e7000000-0000-0000-0000-000000000012', '10.9999/mrg-abc', 'https://x/2', 'mrg/case-2', 'Other title', '["Bo"]', 2023, 'Cell');
select lives_ok(
    $$ select public.merge_papers('e7000000-0000-0000-0000-000000000012', 'e7000000-0000-0000-0000-000000000013', 'doi_case') $$,
    'a second merge with the same alias DOI does not fail');
select is((select count(*)::int from public.paper_aliases where paper_id = 'e7000000-0000-0000-0000-000000000013'), 2,
    'both merges leave an alias');
select is((select count(*)::int from public.paper_aliases
            where paper_id = 'e7000000-0000-0000-0000-000000000013' and doi = '10.9999/mrg-abc'), 1,
    'the DOI is held by one alias only');
select is((select kind from public.paper_aliases where old_paper_id = 'e7000000-0000-0000-0000-000000000011'),
    'duplicate', 'a DOI-case merge is a duplicate, not a preprint');
select is((select title || '/' || (authors ->> 0) || '/' || year from public.papers where id = 'e7000000-0000-0000-0000-000000000013'),
    'Case title/Ada Lovelace/2024', 'an empty title, authors and year are filled from the first merge');
select is((select venue from public.papers where id = 'e7000000-0000-0000-0000-000000000013'),
    null, 'the venue is never taken from the old row');

-- Guards.
select throws_ok(
    $$ select public.merge_papers('e7000000-0000-0000-0000-0000000000c2', 'e7000000-0000-0000-0000-0000000000c2', 'manual') $$,
    '22023', null, 'a paper cannot be merged into itself');

set local role authenticated;
set local request.jwt.claims to '{"sub":"e7000000-0000-0000-0000-0000000000a1"}';
select throws_ok(
    $$ select public.merge_papers('e7000000-0000-0000-0000-0000000000c2', 'e7000000-0000-0000-0000-0000000000c2', 'manual') $$,
    '42501', null, 'members cannot call merge_papers');

select * from finish();
rollback;
