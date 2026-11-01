-- dismiss_recommendations_test.sql — "Not interested" (#182,
-- 20261101130000_dismiss_recommendations.sql): a dismissed paper leaves
-- recommend_papers, recommend_tagged and window_scores; saving it or starting it
-- clears the dismissal, so un-saving later puts it back as before. Ada writes
-- her own rows as `authenticated`, the way the app does.

begin;
select plan(7);

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
    ('d0000000-0000-0000-0000-000000000002', 'http://d/2', 'd/2', 'Control',     pg_temp.qv());

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

-- Dismiss again, then save: the save clears the dismissal…
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
    'saving a dismissed paper clears the dismissal');

-- …so un-saving it puts it back into circulation, as un-saving always has.
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

select * from finish();
rollback;
