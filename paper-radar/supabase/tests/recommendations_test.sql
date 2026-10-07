-- recommendations_test.sql — proves recommend_papers ranks a lab's UNSEEN papers
-- and excludes ones the caller has read / saved / reacted to / commented on,
-- without excluding papers other users engaged with, and respecting lab scoping.
-- Since 20261007130000 it also pins down which paper_status rows count as
-- engagement: saved, or progress past 'unread'. An all-default row must not
-- hide a paper, because that is what un-saving one leaves behind.
-- Mirrors rls_isolation_test.sql (same JWT-claims trick to switch auth context).

begin;
select plan(9);

-- A constant 1024-dim unit-ish vector for both the stored embeddings and the
-- query, so every embedded paper ties on similarity and the test isolates the
-- exclusion/scoping logic (not ranking).
create function pg_temp.qv() returns extensions.vector
language sql immutable as $$
    select array_fill(0.1::real, array[1024])::extensions.vector(1024);
$$;

-- === seed (superuser role, RLS bypassed) ===================================

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-00000000000a', 'ada@lab.test',  '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-00000000000b', 'bob@lab.test',  '{"display_name":"Bob"}'::jsonb),
    ('00000000-0000-0000-0000-00000000000c', 'cara@lab.test', '{"display_name":"Cara"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-00000000000a', 'Ada'),
    ('00000000-0000-0000-0000-00000000000b', 'Bob'),
    ('00000000-0000-0000-0000-00000000000c', 'Cara')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('11111111-1111-1111-1111-111111111111', 'Lab A', 'lab-a', '00000000-0000-0000-0000-00000000000a'),
    ('22222222-2222-2222-2222-222222222222', 'Lab B', 'lab-b', '00000000-0000-0000-0000-00000000000b');

insert into public.team_members (team_id, user_id, role) values
    ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'owner'),
    ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000c', 'member'),
    ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-00000000000b', 'owner');

-- p1..p4 + p6 embedded; p5 has no embedding.
insert into public.papers (id, url, url_norm, title, embedding) values
    ('10000000-0000-0000-0000-000000000001', 'http://x/1', 'x/1', 'Read paper',      pg_temp.qv()),
    ('20000000-0000-0000-0000-000000000002', 'http://x/2', 'x/2', 'Reacted paper',   pg_temp.qv()),
    ('30000000-0000-0000-0000-000000000003', 'http://x/3', 'x/3', 'Commented paper', pg_temp.qv()),
    ('40000000-0000-0000-0000-000000000004', 'http://x/4', 'x/4', 'Unseen paper',    pg_temp.qv()),
    ('50000000-0000-0000-0000-000000000005', 'http://x/5', 'x/5', 'No-embedding',    null),
    ('60000000-0000-0000-0000-000000000006', 'http://x/6', 'x/6', 'Ada-posted paper',pg_temp.qv()),
    -- The two axes, one paper each: a row that means nothing, a row that means
    -- "mine", a row that means "started".
    ('70000000-0000-0000-0000-000000000007', 'http://x/7', 'x/7', 'Stranded paper',  pg_temp.qv()),
    ('80000000-0000-0000-0000-000000000008', 'http://x/8', 'x/8', 'Saved paper',     pg_temp.qv()),
    ('90000000-0000-0000-0000-000000000009', 'http://x/9', 'x/9', 'In-progress',     pg_temp.qv());

-- Lab A: Ada posts p1/p2/p3/p5 and p6; CARA posts the unseen p4 (so it's eligible
-- for Ada — own-posted papers are excluded). Lab B posts the read paper (scoping).
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('10000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('20000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('30000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('40000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000c', 'web'),
    ('50000000-0000-0000-0000-000000000005', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('60000000-0000-0000-0000-000000000006', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('10000000-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-00000000000b', 'web'),
    -- Posted by Cara, so own-posting is not what excludes (or spares) them.
    ('70000000-0000-0000-0000-000000000007', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000c', 'web'),
    ('80000000-0000-0000-0000-000000000008', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000c', 'web'),
    ('90000000-0000-0000-0000-000000000009', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000c', 'web');

-- Ada's "seen" signals: read p1, reacted p2, commented p3.
insert into public.paper_status (user_id, paper_id, team_id, status) values
    ('00000000-0000-0000-0000-00000000000a', '10000000-0000-0000-0000-000000000001',
     '11111111-1111-1111-1111-111111111111', 'read');

-- p7 carries the row un-saving leaves behind: present, but saying nothing. Written
-- with both columns explicit rather than relying on the defaults, so the test
-- still describes the case if the defaults ever change.
insert into public.paper_status (user_id, paper_id, team_id, saved, status) values
    ('00000000-0000-0000-0000-00000000000a', '70000000-0000-0000-0000-000000000007',
     '11111111-1111-1111-1111-111111111111', false, 'unread'),
    -- Saved but not started: the axis that is NOT progress still counts.
    ('00000000-0000-0000-0000-00000000000a', '80000000-0000-0000-0000-000000000008',
     '11111111-1111-1111-1111-111111111111', true, 'unread'),
    -- Started but never saved: so does the axis that is NOT membership.
    ('00000000-0000-0000-0000-00000000000a', '90000000-0000-0000-0000-000000000009',
     '11111111-1111-1111-1111-111111111111', false, 'reading');
insert into public.reactions (paper_id, team_id, user_id, emoji) values
    ('20000000-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000a', '👍');
insert into public.comments (paper_id, team_id, author_id, body) values
    ('30000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000a', 'nice');

-- Cara (same lab) reacted to the UNSEEN paper — must NOT exclude it for Ada.
insert into public.reactions (paper_id, team_id, user_id, emoji) values
    ('40000000-0000-0000-0000-000000000004', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000c', '🎉');

-- === as Ada (Lab A) ========================================================

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000a"}';

-- Only the unseen, embedded paper (p4) is recommended.
-- The whole result set, so an extra recommendation can never slip in unnoticed:
-- the paper nobody has touched, and the one whose status row means nothing.
select is(
    (select array_agg(paper_id order by paper_id) from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)),
    array['40000000-0000-0000-0000-000000000004',
          '70000000-0000-0000-0000-000000000007']::uuid[],
    'Ada is recommended exactly the unseen paper and the stranded one');

select is(
    (select count(*)::int from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
     where paper_id = '10000000-0000-0000-0000-000000000001'),
    0,
    'a paper Ada has read is never recommended');

select is(
    (select count(*)::int from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
     where paper_id = '50000000-0000-0000-0000-000000000005'),
    0,
    'a paper with no embedding is never recommended');

-- A paper Ada posted herself is never recommended back to her.
select is(
    (select count(*)::int from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
     where paper_id = '60000000-0000-0000-0000-000000000006'),
    0,
    'a paper Ada posted herself is never recommended');

-- Cara's reaction on p4 didn't exclude it for Ada (still returned above).
select ok(
    exists (select 1 from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
        where paper_id = '40000000-0000-0000-0000-000000000004'),
    'another member''s engagement does not hide a paper from Ada');

-- === which paper_status rows count as engagement (20261007130000) ==========
-- The regression this guards: un-saving a paper means "put it back in
-- circulation", and while any row at all excluded, it buried the paper instead.
select ok(
    exists (select 1 from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
        where paper_id = '70000000-0000-0000-0000-000000000007'),
    'an all-default paper_status row does not hide a paper from Discover');

select is(
    (select count(*)::int from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
     where paper_id = '80000000-0000-0000-0000-000000000008'),
    0,
    'a saved paper is still excluded, even with no reading progress');

select is(
    (select count(*)::int from public.recommend_papers(
        '11111111-1111-1111-1111-111111111111', pg_temp.qv(), 20)
     where paper_id = '90000000-0000-0000-0000-000000000009'),
    0,
    'a paper in progress is still excluded, even when it was never saved');

-- === lab scoping ===========================================================
-- Ada is not in Lab B → RLS returns none of Lab B's posts.
select is(
    (select count(*)::int from public.recommend_papers(
        '22222222-2222-2222-2222-222222222222', pg_temp.qv(), 20)),
    0,
    'Ada gets no recommendations from a lab she is not a member of');

reset role;
select * from finish();
rollback;
