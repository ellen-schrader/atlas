-- trending_labs_groups_test.sql — trial groups aren't labs
-- (20261101120000_trending_labs_skip_groups.sql): the lab is the last author
-- who is a person, so "KEYNOTE-522 Investigators" and a bracketed group never
-- reach Home's Labs board. Same JWT-claims trick as home_trends_test.sql.

begin;
select plan(3);

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000c1', 'cy@lab.test', '{"display_name":"Cy"}'::jsonb);

insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-0000000000c1', 'Cy')
on conflict (id) do nothing;

insert into public.teams (id, name, slug, created_by) values
    ('55555555-5555-5555-5555-555555555555', 'Trials Lab', 'trends-trials-lab', '00000000-0000-0000-0000-0000000000c1');

insert into public.team_members (team_id, user_id, role) values
    ('55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000c1', 'owner');

insert into public.papers (id, url, url_norm, title, authors) values
    ('20000000-0000-0000-0000-000000000001', 'http://t/1', 't/1', 'KEYNOTE-522',
     '["Peter Schmid","Rebecca Dent","KEYNOTE-522 Investigators"]'),
    ('20000000-0000-0000-0000-000000000002', 'http://t/2', 't/2', 'monarchE',
     '["Joyce O''Shaughnessy","Priya Rastogi","(monarchE Committee Members","Investigators)"]'),
    ('20000000-0000-0000-0000-000000000003', 'http://t/3', 't/3', 'CLEOPATRA',
     '["Sandra Swain","CLEOPATRA Study Group"]'),
    ('20000000-0000-0000-0000-000000000004', 'http://t/4', 't/4', 'Only a group',
     '["TCGA Research Network"]'),
    ('20000000-0000-0000-0000-000000000005', 'http://t/5', 't/5', 'Plain',
     '["Wu","Rebecca Dent"]'),
    ('20000000-0000-0000-0000-000000000006', 'http://t/6', 't/6', 'Parenthetical',
     '["Wu","Wei Chen (陈伟)"]');

insert into public.paper_posts (paper_id, team_id, posted_by, posted_at, tags, source)
select id, '55555555-5555-5555-5555-555555555555', '00000000-0000-0000-0000-0000000000c1',
       now() - interval '1 day', '[]', 'web'
from public.papers where id::text like '20000000-%';

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000c1"}';

select results_eq(
    $$ select lab, n, sharers from public.trending_labs('55555555-5555-5555-5555-555555555555', 30, 5) $$,
    $$ values ('Rebecca Dent'::text, 2, 1), ('Priya Rastogi'::text, 1, 1),
              ('Sandra Swain'::text, 1, 1), ('Wei Chen (陈伟)'::text, 1, 1) $$,
    'trending_labs: the last person, never a trial group or consortium'
);

select is(
    (select count(*)::int from public.trending_labs('55555555-5555-5555-5555-555555555555', 30, 5)
     where lab ~* 'investigators|group|network'),
    0,
    'trending_labs: a paper with only a group author has no lab'
);

select is(
    (select array_agg(public.is_group_author(n) order by i)
     from unnest(array['KEYNOTE-522 Investigators', '(KEYNOTE-355 Investigators)',
                       '(monarchE Committee Members', 'Investigators)', 'Wei Chen (陈伟)',
                       'Raza Ali']) with ordinality as t(n, i)),
    array[true, true, true, true, false, false],
    'is_group_author: groups, bracketed names and split pieces; not a person with a parenthetical'
);

select * from finish();
rollback;
