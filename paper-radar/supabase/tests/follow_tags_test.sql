-- follow_tags_test.sql — recommend_papers' p_tags (20261008160000_follow_tags.sql):
-- a followed-tag paper OUTSIDE the taste's nearest pool still becomes a
-- candidate, its +0.05 lifts it past near-ties, tags follow post_tags() (lab
-- tags win over paper tags), and an empty p_tags changes nothing.

begin;
select plan(4);

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

-- Eleven near-ties at cosine 0.90, untagged.
insert into public.papers (id, url, url_norm, title, tags, embedding)
select ('f0000000-0000-0000-0000-0000000000' || lpad(i::text, 2, '0'))::uuid,
       'http://f/' || i, 'f/' || i, 'Close ' || i, '[]'::jsonb, pg_temp.v(0.90)
from generate_series(1, 11) as i;

insert into public.papers (id, url, url_norm, title, tags, embedding) values
    -- Slightly further (0.88) but tagged: 12th nearest, so outside a 2×5 pool.
    ('f1000000-0000-0000-0000-000000000001', 'http://f/t', 'f/t', 'Tagged', '["spatial"]', pg_temp.v(0.88)),
    -- Paper tag says spatial, but its post's lab tags replace that.
    ('f1000000-0000-0000-0000-000000000002', 'http://f/o', 'f/o', 'Overridden', '["spatial"]', pg_temp.v(0.88));

-- Gus posts everything, so all of it is eligible for Fay.
insert into public.paper_posts (paper_id, team_id, posted_by, tags, source)
select id, '99999999-9999-9999-9999-999999999999', '00000000-0000-0000-0000-0000000000f2',
       case when title = 'Overridden' then '["imaging"]'::jsonb else '[]'::jsonb end, 'web'
from public.papers where url like 'http://f/%';

set local role authenticated;
set local request.jwt.claims to '{"sub":"00000000-0000-0000-0000-0000000000f1"}';

select is(
    (select count(*)::int
       from public.recommend_papers('99999999-9999-9999-9999-999999999999', pg_temp.v(1), 2)
       join public.papers p on p.id = paper_id where p.title = 'Tagged'),
    0,
    'without followed tags the tagged paper is not recommended (outside the pool)'
);

select is(
    (select p.title
       from public.recommend_papers('99999999-9999-9999-9999-999999999999', pg_temp.v(1), 2, array['spatial'])
            with ordinality as r(post_id, paper_id, similarity, n)
       join public.papers p on p.id = r.paper_id
      order by r.n limit 1),
    'Tagged',
    'a followed tag pulls the paper into the pool and its +0.05 puts it first'
);

select is(
    (select p.title
       from public.recommend_papers('99999999-9999-9999-9999-999999999999', pg_temp.v(1), 13, array['spatial'])
            with ordinality as r(post_id, paper_id, similarity, n)
       join public.papers p on p.id = r.paper_id
      order by r.n desc limit 1),
    'Overridden',
    'a post whose lab tags replace the paper''s gets no boost: last, behind the 0.90 ties'
);

select results_eq(
    $$ select paper_id from public.recommend_papers('99999999-9999-9999-9999-999999999999', pg_temp.v(1), 5, '{}') $$,
    $$ select paper_id from public.recommend_papers('99999999-9999-9999-9999-999999999999', pg_temp.v(1), 5) $$,
    'an empty p_tags behaves exactly like the old 3-argument call'
);

select * from finish();
rollback;
