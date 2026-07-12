-- figures_rls_test.sql — proves mood-board figures + engagement are lab-isolated
-- and owner-gated for writes. Mirrors rls_isolation_test.sql (same two users/labs,
-- same JWT-claims trick to switch auth context). Run with `supabase test db`.

begin;
select plan(11);

-- === seed (as superuser test role, RLS bypassed here) ======================

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-00000000000a', 'ada@lab.test', '{"display_name":"Ada"}'::jsonb),
    ('00000000-0000-0000-0000-00000000000b', 'bob@lab.test', '{"display_name":"Bob"}'::jsonb);

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

-- Ada's lab has one figure with a comment and a reaction.
insert into public.figures (id, team_id, uploaded_by, storage_path, title, category, width, height, mime_type) values
    ('f0000000-0000-0000-0000-000000000001',
     '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a',
     '11111111-1111-1111-1111-111111111111/f0000000-0000-0000-0000-000000000001.png',
     'A heatmap in Lab A', 'heatmap', 800, 600, 'image/png');

insert into public.figure_comments (figure_id, team_id, author_id, body) values
    ('f0000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000a', 'Love this palette');

insert into public.figure_reactions (figure_id, team_id, user_id, emoji) values
    ('f0000000-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111',
     '00000000-0000-0000-0000-00000000000a', '👍');

-- === category is free-text / lab-defined (no fixed taxonomy) ===============

select lives_ok(
    $$insert into public.figures (team_id, uploaded_by, storage_path, category, width, height, mime_type)
      values ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a',
              '11111111-1111-1111-1111-111111111111/custom.png', 'Kaplan–Meier', 10, 10, 'image/png')$$,
    'a figure with a lab-defined custom category is accepted');

-- === as Ada (Lab A) ========================================================

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000a"}';

-- Lab A now has two figures: the seeded one + the custom-category one above.
select is((select count(*) from public.figures)::int, 2,
    'Ada sees both of her lab''s figures');
select is((select count(*) from public.figure_comments)::int, 1,
    'Ada sees her lab''s figure comment');
select is((select count(*) from public.figure_reactions)::int, 1,
    'Ada sees her lab''s figure reaction');

-- Ada can re-caption and re-categorise her own figure.
select lives_ok(
    $$update public.figures set caption = 'edited', category = 'density'
      where id = 'f0000000-0000-0000-0000-000000000001'$$,
    'Ada can edit her own figure');

-- === as Bob (Lab B) ========================================================

set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000b"}';

select is((select count(*) from public.figures)::int, 0,
    'Bob sees none of Lab A''s figures');
select is((select count(*) from public.figure_comments)::int, 0,
    'Bob sees none of Lab A''s figure comments');
select is((select count(*) from public.figure_reactions)::int, 0,
    'Bob sees none of Lab A''s figure reactions');

-- Bob cannot post a figure into Lab A (not a member).
select throws_ok(
    $$insert into public.figures (team_id, uploaded_by, storage_path, category, width, height, mime_type)
      values ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000b',
              '11111111-1111-1111-1111-111111111111/x.png', 'heatmap', 10, 10, 'image/png')$$,
    '42501', NULL,  -- insufficient_privilege (RLS), any message
    'Bob cannot add a figure to Lab A');

-- Bob cannot edit or delete Ada's figure (update/delete match zero rows → no-op,
-- not an error, since RLS filters the row out before the write).
update public.figures set caption = 'hacked' where id = 'f0000000-0000-0000-0000-000000000001';
delete from public.figures where id = 'f0000000-0000-0000-0000-000000000001';

-- Re-check as Ada: her figure and its edited caption survive Bob's attempts.
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-00000000000a"}';
select is((select count(*) from public.figures)::int, 2,
    'Ada''s figures survive Bob''s delete attempt');
select is(
    (select caption from public.figures where id = 'f0000000-0000-0000-0000-000000000001'),
    'edited',
    'Bob''s update did not touch Ada''s figure caption');

reset role;
select * from finish();
rollback;
