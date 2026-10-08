-- follow_tags_test.sql — recommend_tagged (20261008160000_follow_tags.sql):
-- only papers carrying a followed tag, however far from the caller's vector;
-- nearest first with a vector, newest first without one; tags by post_tags()
-- (lab tags replace paper tags); the same eligibility as recommend_papers.

begin;
select plan(6);

-- Unit vector with cosine `a` to the query e1.
create function pg_temp.v(a real) returns extensions.vector
language sql immutable as $$
    select (array[a, sqrt(1 - a * a)::real] || array_fill(0::real, array[1022]))::extensions.vector(1024);
$$;

insert into auth.users (id, email, raw_user_meta_data) values
    ('00000000-0000-0000-0000-0000000000f1', 'fay@follow.test', '{"display_name":"Fay"}'::jsonb),
    ('00000000-0000-0000-0000-0000000000f2', 'gus@follow.test', '{"display_name":"Gus"}'::jsonb);
insert into public.profiles (id, display_name) values
    ('00000000-0000-0000-0000-0000000000f1', 'Fay'),
    ('00000000-0000-0000-0000-0000000000f2', 'Gus')
on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('99999999-9999-9999-9999-999999999999', 'Follow Lab', 'follow-lab', '00000000-0000-0000-0000-0000000000f1');
insert into public.team_members (team_id, user_id, role) values
    ('99999999-9999-9999-9999-999999999999', '00000000-0000-0000-0000-0000000000f1', 'owner'),
    ('99999999-9999-9999-9999-999999999999', '00000000-0000-0000-0000-0000000000f2', 'member');

insert into public.papers (id, url, url_norm, title, tags, embedding) values
    ('f1000000-0000-0000-0000-000000000001', 'http://f/1', 'f/1', 'Close untagged', '[]',          pg_temp.v(0.95)),
    ('f1000000-0000-0000-0000-000000000002', 'http://f/2', 'f/2', 'Far tagged',     '["spatial"]', pg_temp.v(0.10)),
    ('f1000000-0000-0000-0000-000000000003', 'http://f/3', 'f/3', 'Near tagged',    '["spatial"]', pg_temp.v(0.80)),
    ('f1000000-0000-0000-0000-000000000004', 'http://f/4', 'f/4', 'Overridden',     '["spatial"]', pg_temp.v(0.90)),
    ('f1000000-0000-0000-0000-000000000005', 'http://f/5', 'f/5', 'Saved tagged',   '["spatial"]', pg_temp.v(0.85)),
    ('f1000000-0000-0000-0000-000000000006', 'http://f/6', 'f/6', 'Own tagged',     '["spatial"]', pg_temp.v(0.85));

-- Gus posts all but "Own tagged" (Fay's). "Far tagged" is the newest.
insert into public.paper_posts (paper_id, team_id, posted_by, posted_at, tags, source)
select p.id, '99999999-9999-9999-9999-999999999999',
       case when p.title = 'Own tagged' then '00000000-0000-0000-0000-0000000000f1'::uuid
            else '00000000-0000-0000-0000-0000000000f2'::uuid end,
       case when p.title = 'Far tagged' then now() else now() - interval '1 day' end,
       case when p.title = 'Overridden' then '["imaging"]'::jsonb else '[]'::jsonb end,
       'web'
from public.papers p where p.url like 'http://f/%';

insert into public.paper_status (user_id, paper_id, team_id, saved) values
    ('00000000-0000-0000-0000-0000000000f1', 'f1000000-0000-0000-0000-000000000005', '99999999-9999-9999-9999-999999999999', true);

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000f1"}';

select results_eq(
    $$ select p.title
         from public.recommend_tagged('99999999-9999-9999-9999-999999999999', array['spatial'], pg_temp.v(1), 10)
              with ordinality as r(post_id, paper_id, similarity, n)
         join public.papers p on p.id = r.paper_id
        order by r.n $$,
    $$ values ('Near tagged'::text), ('Far tagged'::text) $$,
    'only tagged papers, nearest first — however far; untagged, overridden, saved and own posts excluded'
);

select results_eq(
    $$ select p.title
         from public.recommend_tagged('99999999-9999-9999-9999-999999999999', array['spatial'], null, 10)
              with ordinality as r(post_id, paper_id, similarity, n)
         join public.papers p on p.id = r.paper_id
        order by r.n $$,
    $$ values ('Far tagged'::text), ('Near tagged'::text) $$,
    'without a vector (cold start): newest first'
);

select is(
    (select count(*)::int
       from public.recommend_tagged('99999999-9999-9999-9999-999999999999', array['imaging'], pg_temp.v(1), 10)
       join public.papers p on p.id = paper_id where p.title = 'Overridden'),
    1,
    'a post''s lab tags are what it is matched on'
);

select is(
    (select count(*)::int
       from public.recommend_tagged('99999999-9999-9999-9999-999999999999', '{}', pg_temp.v(1), 10)),
    0,
    'no followed tags → nothing'
);

select is(
    (select count(*)::int
       from public.recommend_tagged('99999999-9999-9999-9999-999999999999', array['spatial'], pg_temp.v(1), 1)),
    1,
    'p_limit caps the rows'
);

-- Someone outside Follow Lab sees nothing of it.
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000ff"}';
select is(
    (select count(*)::int
       from public.recommend_tagged('99999999-9999-9999-9999-999999999999', array['spatial'], null, 10)),
    0,
    'RLS: a non-member gets nothing'
);

select * from finish();
rollback;
