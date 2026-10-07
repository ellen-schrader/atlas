-- 20261008120000_home_trends.sql — the data behind Home's Trending and Tag volume
-- (docs/dashboard.md §3.6–3.7, §6).
--
-- Which tags? A post's lab tags (paper_posts.tags) when it has any, else the
-- paper's own enrichment tags (papers.tags). That is what every list row already
-- shows (PaperListRow, Home's feed, cards), and in practice most posts carry no
-- lab tags, so counting lab tags alone would leave Trending empty. post_tags()
-- states that rule once, and search_papers / search_papers_count are reissued
-- so that the ?tag= filter Trending links to matches the same set; otherwise
-- clicking a trending tag could open an empty list.
--
-- All three RPCs are security invoker: they aggregate over paper_posts and
-- papers, whose RLS already limits a caller to their own labs.

create or replace function public.post_tags(p_post_tags jsonb, p_paper_tags jsonb)
returns jsonb
language sql
immutable
as $$
    select coalesce(nullif(p_post_tags, '[]'::jsonb), p_paper_tags, '[]'::jsonb);
$$;

-- Top tags by papers posted in the last p_days, with the count for the p_days
-- before that. Ties go to the faster riser, then alphabetically, so the order
-- is stable between refreshes.
create or replace function public.trending_tags(
    p_team  uuid,
    p_days  int default 30,
    p_limit int default 6
)
returns table(tag text, n int, prev int)
language sql
stable
set search_path = public
as $$
    with t as (
        select x.tag, pp.posted_at >= now() - make_interval(days => p_days) as current
        from public.paper_posts pp
        join public.papers p on p.id = pp.paper_id
        cross join lateral jsonb_array_elements_text(public.post_tags(pp.tags, p.tags)) as x(tag)
        where pp.team_id = p_team
          and pp.posted_at >= now() - make_interval(days => 2 * p_days)
    )
    select tag,
           count(*) filter (where current)::int     as n,
           count(*) filter (where not current)::int as prev
    from t
    group by tag
    having count(*) filter (where current) > 0
    order by n desc, (count(*) filter (where current) - count(*) filter (where not current)) desc, tag
    limit greatest(coalesce(p_limit, 6), 0);
$$;

-- Top authors of papers posted in the last p_days, with how many distinct people
-- shared them ("shared by 3 people"). A Teams post has no posted_by, only a
-- label, so the label stands in for the person.
create or replace function public.trending_authors(
    p_team  uuid,
    p_days  int default 30,
    p_limit int default 5
)
returns table(author text, n int, sharers int)
language sql
stable
set search_path = public
as $$
    select a.author,
           count(distinct pp.paper_id)::int as n,
           count(distinct coalesce(pp.posted_by::text, pp.posted_by_label))::int as sharers
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    cross join lateral jsonb_array_elements_text(coalesce(p.authors, '[]'::jsonb)) as a(author)
    where pp.team_id = p_team
      and pp.posted_at >= now() - make_interval(days => p_days)
      and btrim(a.author) <> ''
    group by a.author
    order by n desc, sharers desc, a.author
    limit greatest(coalesce(p_limit, 5), 0);
$$;

-- Weekly counts for the given tags over the last p_weeks (current week last),
-- zero-filled so every tag has every week and the stacked chart needs no gaps
-- handled client-side.
create or replace function public.tag_volume(
    p_team  uuid,
    p_weeks int default 12,
    p_tags  text[] default '{}'
)
returns table(tag text, week date, n int)
language sql
stable
set search_path = public
as $$
    with weeks as (
        select generate_series(
                   date_trunc('week', now()) - make_interval(weeks => greatest(p_weeks, 1) - 1),
                   date_trunc('week', now()),
                   interval '1 week'
               )::date as week
    ),
    tags as (
        select distinct unnest(p_tags) as tag
    ),
    counts as (
        select x.tag, date_trunc('week', pp.posted_at)::date as week, count(*)::int as n
        from public.paper_posts pp
        join public.papers p on p.id = pp.paper_id
        cross join lateral jsonb_array_elements_text(public.post_tags(pp.tags, p.tags)) as x(tag)
        where pp.team_id = p_team
          and x.tag = any(p_tags)
          and pp.posted_at >= (select min(week) from weeks)
        group by 1, 2
    )
    select tags.tag, weeks.week, coalesce(counts.n, 0)
    from tags
    cross join weeks
    left join counts on counts.tag = tags.tag and counts.week = weeks.week
    order by tags.tag, weeks.week;
$$;

grant execute on function public.post_tags(jsonb, jsonb)           to authenticated;
grant execute on function public.trending_tags(uuid, int, int)     to authenticated;
grant execute on function public.trending_authors(uuid, int, int)  to authenticated;
grant execute on function public.tag_volume(uuid, int, text[])     to authenticated;

-- === the tag filter matches what rows display =============================
-- Reissued from 20261006120000_reading_status_two_axes.sql verbatim except
-- for the p_tag line. Both functions must agree exactly, or the "N results"
-- label contradicts the list.
create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0,
    p_sort   text default 'shared',
    p_venue  text default null,
    p_status text default null   -- 'unread' | 'reading' | 'read' | 'saved'
)
returns setof public.paper_posts
language sql
stable
as $$
    select pp.*
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    left join public.paper_status ps
           on ps.paper_id = pp.paper_id
          and ps.team_id  = pp.team_id
          and ps.user_id  = auth.uid()
    where pp.team_id = p_team
      and (p_tag is null or public.post_tags(pp.tags, p.tags) ? p_tag)
      and (p_venue is null or p.venue = p_venue)
      and (
        p_status is null
        -- "saved" asks the membership axis, independently of progress: a paper
        -- central to your project stays saved after you have read it.
        or (p_status = 'saved' and coalesce(ps.saved, false))
        -- No row at all is unread: never opened, never saved.
        or (p_status = 'unread' and (ps.status is null or ps.status = 'unread'))
        or (p_status in ('reading', 'read') and ps.status = p_status)
      )
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      )
    -- Identical to 20261006120000's ordering; only the tag predicate changes.
    order by
      (case
         when public.prefix_tsquery(p_q) is null then 0
         else ts_rank(
                to_tsvector('english',
                  coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, '')),
                public.prefix_tsquery(p_q)
              )
       end) desc,
      (case when p_sort = 'published' then p.published_at end) desc nulls last,
      pp.posted_at desc,
      pp.id desc
    limit  greatest(coalesce(p_limit, 30), 0)
    offset greatest(coalesce(p_offset, 0), 0);
$$;

create or replace function public.search_papers_count(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_venue  text default null,
    p_status text default null
)
returns integer
language sql
stable
as $$
    select count(*)::int
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    left join public.paper_status ps
           on ps.paper_id = pp.paper_id
          and ps.team_id  = pp.team_id
          and ps.user_id  = auth.uid()
    where pp.team_id = p_team
      and (p_tag is null or public.post_tags(pp.tags, p.tags) ? p_tag)
      and (p_venue is null or p.venue = p_venue)
      and (
        p_status is null
        or (p_status = 'saved' and coalesce(ps.saved, false))
        or (p_status = 'unread' and (ps.status is null or ps.status = 'unread'))
        or (p_status in ('reading', 'read') and ps.status = p_status)
      )
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      );
$$;
