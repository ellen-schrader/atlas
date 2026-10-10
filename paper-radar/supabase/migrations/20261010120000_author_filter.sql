-- Filter a lab's papers by author (issue #119), and give the filter its options.
--
--   1. team_authors: every author on a lab's papers with a paper count, the
--      author counterpart of team_tags. Uncapped — the menu is searchable.
--   2. team_venues: the 30-row cap is lifted for the same reason. It existed
--      because a long plain <select> was noise; a searchable menu shows the top
--      entries and finds the rest.
--   3. search_papers / search_papers_count gain p_author: an exact match on any
--      author of the paper. Reissued from 20261008120000_home_trends.sql
--      verbatim except for the p_author parameter and predicate. The old
--      signatures are dropped first: an added defaulted parameter would make a
--      second overload, and PostgREST can't choose between them.

drop function if exists public.search_papers(uuid, text, text, int, int, text, text, text);
drop function if exists public.search_papers_count(uuid, text, text, text, text);

create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0,
    p_sort   text default 'shared',
    p_venue  text default null,
    p_status text default null,  -- 'unread' | 'reading' | 'read' | 'saved'
    p_author text default null
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
      and (p_author is null or p.authors ? p_author)
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
    p_status text default null,
    p_author text default null
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
      and (p_author is null or p.authors ? p_author)
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

-- Distinct authors on a lab's papers, most papers first. Security invoker:
-- paper_posts / papers RLS already limits a caller to their own labs.
create or replace function public.team_authors(p_team uuid)
returns table(author text, n int)
language sql
stable
as $$
    select a.author, count(distinct pp.paper_id)::int as n
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    cross join lateral jsonb_array_elements_text(coalesce(p.authors, '[]'::jsonb)) as a(author)
    where pp.team_id = p_team
      and btrim(a.author) <> ''
    group by a.author
    order by n desc, a.author;
$$;

create or replace function public.team_venues(p_team uuid)
returns table (venue text, count bigint)
language sql
stable
as $$
    select p.venue, count(*) as count
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and p.venue is not null
      and p.venue <> ''
    group by p.venue
    order by count(*) desc, p.venue;
$$;

grant execute on function public.search_papers(uuid, text, text, int, int, text, text, text, text) to authenticated;
grant execute on function public.search_papers_count(uuid, text, text, text, text, text)            to authenticated;
grant execute on function public.team_authors(uuid)                                                 to authenticated;
