-- 20260712101500_search_rpcs.sql — server-side paper search, count, and tag facets.
--
-- Replaces the web app's "fetch every post for the team and filter in JS" with
-- paginated, full-text search on the server. Full-text runs against the existing
-- `papers_fts_idx` GIN index (init migration) by matching its tsvector expression
-- exactly, so no schema change to the tables is needed.
--
-- All three functions are SECURITY INVOKER (the default): they read `paper_posts`
-- and `papers`, so the caller's RLS — lab membership via is_team_member() — applies
-- unchanged. `p_team` scopes to the caller's *active* lab; RLS still guarantees they
-- can only ever see labs they belong to.

-- Full-text search over a lab's posts, ranked by relevance then recency.
-- Returns `setof paper_posts` so the client can embed the paper:
--   supabase.rpc('search_papers', {...}).select('*, papers(*)')
create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0
)
returns setof public.paper_posts
language sql
stable
as $$
    select pp.*
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and (p_tag is null or pp.tags ? p_tag)
      and (
        coalesce(p_q, '') = ''
        or to_tsvector('english', coalesce(p.title, '') || ' ' || coalesce(p.abstract, ''))
           @@ websearch_to_tsquery('english', p_q)
      )
    order by
      (case
         when coalesce(p_q, '') = '' then 0
         else ts_rank(
                to_tsvector('english', coalesce(p.title, '') || ' ' || coalesce(p.abstract, '')),
                websearch_to_tsquery('english', p_q)
              )
       end) desc,
      pp.posted_at desc
    limit  greatest(coalesce(p_limit, 30), 0)
    offset greatest(coalesce(p_offset, 0), 0);
$$;

-- Total matches for the same filters (for the "N results" label + paging end).
create or replace function public.search_papers_count(
    p_team uuid,
    p_q    text default '',
    p_tag  text default null
)
returns integer
language sql
stable
as $$
    select count(*)::int
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and (p_tag is null or pp.tags ? p_tag)
      and (
        coalesce(p_q, '') = ''
        or to_tsvector('english', coalesce(p.title, '') || ' ' || coalesce(p.abstract, ''))
           @@ websearch_to_tsquery('english', p_q)
      );
$$;

-- Distinct lab-applied tags with counts, for the filter chips. Needed server-side
-- because with pagination the client no longer holds the whole collection.
create or replace function public.team_tags(p_team uuid)
returns table(tag text, n int)
language sql
stable
as $$
    select t.tag, count(*)::int as n
    from public.paper_posts pp
    cross join lateral jsonb_array_elements_text(coalesce(pp.tags, '[]'::jsonb)) as t(tag)
    where pp.team_id = p_team
    group by t.tag
    order by n desc, t.tag;
$$;

grant execute on function public.search_papers(uuid, text, text, int, int) to authenticated;
grant execute on function public.search_papers_count(uuid, text, text)      to authenticated;
grant execute on function public.team_tags(uuid)                            to authenticated;
