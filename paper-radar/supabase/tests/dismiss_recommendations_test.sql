-- dismiss_recommendations_test.sql — 👍 / 👎 on recommendations (#182,
-- 20261101130000_dismiss_recommendations.sql): a dismissed paper leaves
-- recommend_papers, recommend_tagged, window_scores and the cold start's
-- recent_unseen; a merge keeps the newest answer; saving the paper clears a 👎,
-- so un-saving later puts it back. Ada writes
-- her own rows as `authenticated`, the way the app does.

begin;
select plan(13);

create function pg_temp.qv() returns extensions.vector
language sql immutable as $$
    select array_fill(0.1::real, array[1024])::extensions.vector(1024);
$$;

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000d1', 'ada@dismiss.test',  '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-0000000000d2', 'cara@dismiss.test', '{"display_name":"Cara"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-0000000000d1', 'Ada'),
    ('00000000-0000-0000-0000-0000000000d2', 'Cara')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('66666666-6666-6666-6666-666666666666', 'Dismiss Lab', 'dismiss-lab', '00000000-0000-0000-0000-0000000000d1');

insert into public.team_members (team_id, user_id, role) values
    ('66666666-6666-6666-6666-666666666666', '00000000-0000-0000-0000-0000000000d1', 'owner'),
    ('66666666-6666-6666-6666-666666666666', '00000000-0000-0000-0000-0000000000d2', 'member');

insert into public.papers (id, url, url_norm, title, embedding) values
    ('d0000000-0000-0000-0000-000000000001', 'http://d/1', 'd/1', 'Not for Ada', pg_temp.qv()),
    ('d0000000-0000-0000-0000-000000000002', 'http://d/2', 'd/2', 'Control',     pg_temp.qv()),
    -- A preprint of the control paper, never posted: merged into it below.
    ('d0000000-0000-0000-0000-000000000003', 'http://d/3', 'd/3', 'Preprint',    null);

-- Cara posts both, tagged, so all three functions can see them.
insert into public.paper_posts (paper_id, team_id, posted_by, source, tags) values
    ('d0000000-0000-0000-0000-000000000001', '66666666-6666-6666-6666-666666666666', '00000000-0000-0000-0000-0000000000d2', 'web', '["spatial"]'),
    ('d0000000-0000-0000-0000-000000000002', '66666666-6666-6666-6666-666666666666', '00000000-0000-0000-0000-0000000000d2', 'web', '["spatial"]');

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000d1"}';

-- Ada clicks "Not interested" on paper 1: an upsert of dismissed_at only.
insert into public.paper_status (user_id, paper_id, team_id, dismissed_at) values
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000001',
     '66666666-6666-6666-6666-666666666666', now())
on conflict (user_id, paper_id, team_id) do update set dismissed_at = excluded.dismissed_at;

select is(
    (select array_agg(paper_id) from public.recommend_papers(
        '66666666-6666-6666-6666-666666666666', pg_temp.qv(), 20)),
    array['d0000000-0000-0000-0000-000000000002']::uuid[],
    'recommend_papers: a dismissed paper is left out, the rest are not');

select is(
    (select array_agg(paper_id) from public.recommend_tagged(
        '66666666-6666-6666-6666-666666666666', array['spatial'], pg_temp.qv(), 20)),
    array['d0000000-0000-0000-0000-000000000002']::uuid[],
    'recommend_tagged: a dismissed paper is left out');

select is(
    (select array_agg(paper_id) from public.recent_unseen(
        '66666666-6666-6666-6666-666666666666', 20)),
    array['d0000000-0000-0000-0000-000000000002']::uuid[],
    'recent_unseen (the cold start): a dismissed paper is left out');

select is(
    (select array_agg(paper_id) from public.window_scores(
        '66666666-6666-6666-6666-666666666666', now() - interval '1 day', pg_temp.qv())),
    array['d0000000-0000-0000-0000-000000000002']::uuid[],
    'window_scores (the digest''s For you): a dismissed paper is left out');

-- Undo: dismissed_at back to null, and the paper is back.
update public.paper_status set dismissed_at = null
where user_id = '00000000-0000-0000-0000-0000000000d1'
  and paper_id = 'd0000000-0000-0000-0000-000000000001';

select is(
    (select count(*)::int from public.recommend_papers(
        '66666666-6666-6666-6666-666666666666', pg_temp.qv(), 20)),
    2,
    'undo puts the paper back');

-- 👎 again, then save: the save clears the 👎 (a saved paper is one you're
-- interested in), and Home's card clears its 👎 to match…
update public.paper_status set dismissed_at = now()
where user_id = '00000000-0000-0000-0000-0000000000d1'
  and paper_id = 'd0000000-0000-0000-0000-000000000001';
update public.paper_status set saved = true
where user_id = '00000000-0000-0000-0000-0000000000d1'
  and paper_id = 'd0000000-0000-0000-0000-000000000001';

select is(
    (select dismissed_at from public.paper_status
     where user_id = '00000000-0000-0000-0000-0000000000d1'
       and paper_id = 'd0000000-0000-0000-0000-000000000001'),
    null,
    'saving a paper clears its 👎');

-- …so un-saving it later puts it back into circulation, as un-saving always has.
update public.paper_status set saved = false
where user_id = '00000000-0000-0000-0000-0000000000d1'
  and paper_id = 'd0000000-0000-0000-0000-000000000001';

select is(
    (select count(*)::int from public.recommend_papers(
        '66666666-6666-6666-6666-666666666666', pg_temp.qv(), 20)),
    2,
    'un-saving after a save brings the paper back');

-- Cara's view is her own: Ada's dismissal never hid anything from her.
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000d2"}';
update public.paper_status set dismissed_at = now()  -- RLS: matches none of Ada's rows
where paper_id = 'd0000000-0000-0000-0000-000000000001';
reset role;
select is(
    (select dismissed_at from public.paper_status
     where user_id = '00000000-0000-0000-0000-0000000000d1'
       and paper_id = 'd0000000-0000-0000-0000-000000000001'),
    null,
    'another member cannot dismiss a paper for Ada');

-- Merging a preprint Ada dismissed into a paper where she has an all-default row
-- (left by un-saving): the kept paper stays dismissed.
insert into public.paper_status (user_id, paper_id, team_id, saved, status, dismissed_at) values
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000003',
     '66666666-6666-6666-6666-666666666666', false, 'unread', now()),
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000002',
     '66666666-6666-6666-6666-666666666666', false, 'unread', null);
select public.merge_papers('d0000000-0000-0000-0000-000000000003',
                           'd0000000-0000-0000-0000-000000000002', 'manual');
select isnt(
    (select dismissed_at from public.paper_status
     where user_id = '00000000-0000-0000-0000-0000000000d1'
       and paper_id = 'd0000000-0000-0000-0000-000000000002'),
    null,
    'merge_papers keeps a dismissal from the merged paper');

-- 👍 (liked_at) answers the recommendation too: not offered again.
insert into public.papers (id, url, url_norm, title, embedding) values
    ('d0000000-0000-0000-0000-000000000004', 'http://d/4', 'd/4', 'Liked', pg_temp.qv());
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('d0000000-0000-0000-0000-000000000004', '66666666-6666-6666-6666-666666666666',
     '00000000-0000-0000-0000-0000000000d2', 'web');
set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000d1"}';
insert into public.paper_status (user_id, paper_id, team_id, liked_at) values
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000004',
     '66666666-6666-6666-6666-666666666666', now());
select is(
    (select count(*)::int from public.recommend_papers(
        '66666666-6666-6666-6666-666666666666', pg_temp.qv(), 20)
     where paper_id = 'd0000000-0000-0000-0000-000000000004'),
    0,
    'a paper given a thumbs up is not recommended again');

-- At most one answer per row: setting both fails, rather than one being dropped.
select throws_ok(
    $$ update public.paper_status set dismissed_at = now()
       where user_id = '00000000-0000-0000-0000-0000000000d1'
         and paper_id = 'd0000000-0000-0000-0000-000000000004' $$,
    '23514', null,
    'a row cannot be both 👍 and 👎');
reset role;

-- Merges keep the newest answer of the two copies. p5 (👍 a day ago) merged
-- into p6 (👎 now): the 👎. p7 (👍 now) into p8 (👍 a year ago): today's 👍.
insert into public.papers (id, url, url_norm, title) values
    ('d0000000-0000-0000-0000-000000000005', 'http://d/5', 'd/5', 'Liked copy'),
    ('d0000000-0000-0000-0000-000000000006', 'http://d/6', 'd/6', 'Disliked copy'),
    ('d0000000-0000-0000-0000-000000000007', 'http://d/7', 'd/7', 'Liked today'),
    ('d0000000-0000-0000-0000-000000000008', 'http://d/8', 'd/8', 'Liked last year');
insert into public.paper_status (user_id, paper_id, team_id, liked_at, dismissed_at) values
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000005',
     '66666666-6666-6666-6666-666666666666', now() - interval '1 day', null),
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000006',
     '66666666-6666-6666-6666-666666666666', null, now()),
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000007',
     '66666666-6666-6666-6666-666666666666', now(), null),
    ('00000000-0000-0000-0000-0000000000d1', 'd0000000-0000-0000-0000-000000000008',
     '66666666-6666-6666-6666-666666666666', now() - interval '1 year', null);
select public.merge_papers('d0000000-0000-0000-0000-000000000005',
                           'd0000000-0000-0000-0000-000000000006', 'manual');
select public.merge_papers('d0000000-0000-0000-0000-000000000007',
                           'd0000000-0000-0000-0000-000000000008', 'manual');

select is(
    (select row(liked_at is null, dismissed_at is null) from public.paper_status
     where user_id = '00000000-0000-0000-0000-0000000000d1'
       and paper_id = 'd0000000-0000-0000-0000-000000000006')::text,
    '(t,f)',
    'merge_papers: an older 👍 and a newer 👎 merge to the 👎');

select ok(
    (select liked_at > now() - interval '1 hour' from public.paper_status
     where user_id = '00000000-0000-0000-0000-0000000000d1'
       and paper_id = 'd0000000-0000-0000-0000-000000000008'),
    'merge_papers: two 👍 merge to the newer one');

select * from finish();
rollback;
