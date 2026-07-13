-- 20260713160000_paper_filters.sql — filter a lab's papers by venue and by your own
-- reading status.
--
-- From the UX review: "at 425 papers, a single tag filter isn't enough to find things."
--
-- Both filters go in the RPC rather than the client, because the list is paginated:
-- filtering a 30-row page in the browser would show 4 results and claim there were no
-- more, which is worse than not filtering at all.
--
-- Status is *per-user* (paper_status is keyed by user_id), so "unread" means unread by
-- YOU, not by the lab. The RPC is `stable` and called as the caller, so auth.uid() is
-- the right identity — no need to pass a user id in and no way to spoof one.

create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0,
    p_sort   text default 'shared',
    p_venue  text default null,
    p_status text default null   -- 'unread' | 'to_read' | 'reading' | 'read'
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
      and (p_tag is null or pp.tags ? p_tag)
      and (p_venue is null or p.venue = p_venue)
      and (
        p_status is null
        -- "unread" is the absence of progress: never opened, or only ever saved.
        -- A paper you saved but haven't read is still unread, which is the whole
        -- point of a reading list.
        or (p_status = 'unread' and (ps.status is null or ps.status = 'to_read'))
        or (p_status <> 'unread' and ps.status = p_status)
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

-- The count MUST apply the same filters, or the "N results" label contradicts the list
-- and infinite scroll stops at the wrong place.
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
      and (p_tag is null or pp.tags ? p_tag)
      and (p_venue is null or p.venue = p_venue)
      and (
        p_status is null
        or (p_status = 'unread' and (ps.status is null or ps.status = 'to_read'))
        or (p_status <> 'unread' and ps.status = p_status)
      )
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      );
$$;

-- Adding parameters OVERLOADS rather than replaces, and two candidate functions make a
-- named-argument call ambiguous. Drop the previous signatures.
drop function if exists public.search_papers(uuid, text, text, int, int, text);
drop function if exists public.search_papers_count(uuid, text, text);

-- The venues a lab actually has, for the filter's options. Same shape as team_tags.
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
    order by count(*) desc, p.venue
    -- The long tail of one-off venues is noise in a filter menu, so the list is
    -- capped. The UI says so rather than silently pretending these are all the
    -- venues a lab has — a filter that quietly omits options is a filter you
    -- can't trust.
    limit 30;
$$;

grant execute on function public.team_venues(uuid) to authenticated;
