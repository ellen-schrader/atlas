-- 20261008150000_trending_labs.sql — Home's Trending "Labs" tab.
--
-- Which labs' papers the lab has been sharing, rather than every author: in the
-- life sciences the last author is usually the PI, so the last author stands in
-- for "the lab that produced the paper" (the same proxy the Maps lab list uses,
-- api/app.py _last_author_lab). Counting every author let one 40-author
-- consortium paper put 40 names on the board.
--
-- Known gaps, accepted for now: co-senior authors aren't counted, a consortium
-- name can be the last author, and name variants ("R. Ali" / "Raza Ali") count
-- as different labs until authors carry stable ids.
--
-- trending_authors (20261008120000) has no caller after this; it is left in
-- place so a client still on the previous build keeps working during a deploy.

create or replace function public.trending_labs(
    p_team  uuid,
    p_days  int default 30,
    p_limit int default 5
)
returns table(lab text, n int, sharers int)
language sql
stable
set search_path = public
as $$
    select btrim(p.authors ->> -1) as lab,
           count(distinct pp.paper_id)::int as n,
           count(distinct coalesce(pp.posted_by::text, pp.posted_by_label))::int as sharers
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and pp.posted_at >= now() - make_interval(days => p_days)
      and jsonb_typeof(p.authors) = 'array'
      and btrim(coalesce(p.authors ->> -1, '')) <> ''
    group by 1
    order by n desc, sharers desc, lab
    limit greatest(coalesce(p_limit, 5), 0);
$$;

grant execute on function public.trending_labs(uuid, int, int) to authenticated;
