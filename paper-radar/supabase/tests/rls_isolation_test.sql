-- rls_isolation_test.sql — proves labs cannot see each other's data, and that
-- the mention → to-be-read trigger behaves. Run with `supabase test db`.
--
-- Self-contained: seeds auth.users directly and switches the auth context with
-- `set local role authenticated` + a `request.jwt.claims` JSON carrying `sub`
-- (exactly what auth.uid() reads). No external extensions beyond pgTAP.

begin;
select plan(10);

-- === seed (runs as the superuser test role, so RLS is bypassed here) =======

-- Two users with fixed ids so we can put them in the JWT claims below.
insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-00000000000a', 'ada@lab.test', '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-00000000000b', 'bob@lab.test', '{"display_name":"Bob"}'::jsonb);

-- The on_auth_user_created trigger creates profiles; insert defensively too.
insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-00000000000a', 'Ada'),
    ('00000000-0000-0000-0000-00000000000b', 'Bob')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('11111111-1111-1111-1111-111111111111', 'Lab A', 'lab-a', '00000000-0000-0000-0000-00000000000a'),
    ('22222222-2222-2222-2222-222222222222', 'Lab B', 'lab-b', '00000000-0000-0000-0000-00000000000b');

insert into public.team_members (team_id, user_id, role) values
    ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'owner'),
    ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-00000000000b', 'owner');

insert into public.papers (id, url, url_norm, title) values
    ('10000000-0000-0000-0000-000000000001', 'http://x/1', 'x/1', 'Paper 1'),
    ('20000000-0000-0000-0000-000000000002', 'http://x/2', 'x/2', 'Paper 2'),
    ('30000000-0000-0000-0000-000000000003', 'http://x/3', 'x/3', 'Paper 3');

-- Lab A posts papers 1 and 3; Lab B posts paper 2.
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('10000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('30000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'web'),
    ('20000000-0000-0000-0000-000000000002', '22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-00000000000b', 'web');

insert into public.comments (paper_id, team_id, author_id, body) values
    ('10000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'A note in Lab A');

-- === trigger: mention → auto-TBR (checked as superuser) ====================

-- Ada is mentioned on paper 1 → a 'to_read' status appears for her.
insert into public.mentions (paper_id, team_id, mentioned_user, mentioned_by) values
    ('10000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a');
select is(
    (select status from public.paper_status
     where user_id = '00000000-0000-0000-0000-00000000000a'
       and paper_id = '10000000-0000-0000-0000-000000000001'),
    'to_read',
    'mention auto-adds the paper to the mentioned user''s TBR');

-- Ada has already read paper 3; a later mention must NOT overwrite that.
insert into public.paper_status (user_id, paper_id, team_id, status) values
    ('00000000-0000-0000-0000-00000000000a', '30000000-0000-0000-0000-000000000003',
     '11111111-1111-1111-1111-111111111111', 'read');
insert into public.mentions (paper_id, team_id, mentioned_user, mentioned_by) values
    ('30000000-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000a', '00000000-0000-0000-0000-00000000000a');
select is(
    (select status from public.paper_status
     where user_id = '00000000-0000-0000-0000-00000000000a'
       and paper_id = '30000000-0000-0000-0000-000000000003'),
    'read',
    'mention does not overwrite an existing read status');

-- === isolation as Ada (Lab A) ==============================================

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000a"}';

select is((select count(*) from public.paper_posts)::int, 2,
    'Ada sees exactly her lab''s 2 posts');
select is((select count(*) from public.paper_posts
           where team_id = '22222222-2222-2222-2222-222222222222')::int, 0,
    'Ada sees zero of Lab B''s posts');
select is((select count(*) from public.papers)::int, 2,
    'Ada sees only papers posted in her lab');
select is((select count(*) from public.papers
           where id = '20000000-0000-0000-0000-000000000002')::int, 0,
    'Ada cannot see a paper only Lab B posted');
select is((select count(*) from public.comments)::int, 1,
    'Ada sees her lab''s comment');

-- === isolation as Bob (Lab B) ==============================================

set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000b"}';

select is((select count(*) from public.paper_posts)::int, 1,
    'Bob sees exactly his lab''s 1 post');
select is((select count(*) from public.comments)::int, 0,
    'Bob sees none of Lab A''s comments');
select is((select count(*) from public.papers
           where id = '10000000-0000-0000-0000-000000000001')::int, 0,
    'Bob cannot see Lab A''s paper 1');

reset role;
select * from finish();
rollback;
