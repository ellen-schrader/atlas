-- 20261019100000_recommend_exclude.sql — let the caller name papers to leave out.
--
-- Papers you posted now count as a recommendation signal (api/taste.py), and a
-- paper you posted shouldn't be recommended back to you. Both RPCs already drop
-- `posted_by = auth.uid()`, but a post that came in from Teams has no user id —
-- only the sender's name, which the app matches to you (taste.own_posts). The
-- app passes those papers here as p_exclude.
--
-- Filtering in the app instead would mean asking for more rows, and
-- recommend_papers re-ranks its p_limit * 5 nearest candidates by freshness, so
-- a bigger p_limit changes everyone's ranking. Here the exclusion happens before
-- the candidate pool is cut, so the pool and the re-rank are exactly as before.
--
-- The new parameter defaults to empty, so every existing caller (including the
-- Claude connector) behaves as before. Bodies otherwise copied verbatim from
-- 20261007130000_recommend_meaningful_status.sql and 20261008160000_follow_tags.sql.

drop function public.recommend_papers(uuid, extensions.vector, int);

create function public.recommend_papers(
    p_team    uuid,
    p_query   extensions.vector(1024),
    p_limit   int default 12,
    p_exclude uuid[] default '{}'
)
returns table(post_id uuid, paper_id uuid, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    with candidates as (
        select
            pp.id       as post_id,
            pp.paper_id as paper_id,
            pp.posted_at,
            (1 - (p.embedding <=> p_query))::real as similarity
        from public.paper_posts pp
        join public.papers p on p.id = pp.paper_id
        where pp.team_id = p_team
          and p.embedding is not null
          and pp.posted_by is distinct from auth.uid()  -- not one you posted
          and not (pp.paper_id = any (coalesce(p_exclude, '{}')))
          and not exists (
              select 1 from public.paper_status ps
              where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
                -- The row has to MEAN something. Saved is intent; any progress
                -- other than 'unread' is consumption. Neither is true of the
                -- all-default row left by un-saving.
                and (ps.saved or ps.status <> 'unread')
          )
          and not exists (
              select 1 from public.reactions r
              where r.paper_id = p.id and r.team_id = p_team and r.user_id = auth.uid()
          )
          and not exists (
              select 1 from public.comments c
              where c.paper_id = p.id and c.team_id = p_team and c.author_id = auth.uid()
          )
        order by p.embedding <=> p_query          -- HNSW index serves this
        limit greatest(coalesce(p_limit, 12), 0) * 5
    )
    select post_id, paper_id, similarity
    from candidates
    order by
        similarity
        + 0.06 * exp(- extract(epoch from (now() - posted_at)) / (86400.0 * 30)) desc
    limit greatest(coalesce(p_limit, 12), 0);
$$;

grant execute on function public.recommend_papers(uuid, extensions.vector, int, uuid[])
    to authenticated;


drop function public.recommend_tagged(uuid, text[], extensions.vector, int);

create function public.recommend_tagged(
    p_team    uuid,
    p_tags    text[],
    p_query   extensions.vector(1024) default null,
    p_limit   int default 12,
    p_exclude uuid[] default '{}'
)
returns table(post_id uuid, paper_id uuid, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    select pp.id,
           pp.paper_id,
           case when p_query is not null and p.embedding is not null
                then (1 - (p.embedding <=> p_query))::real end as similarity
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and cardinality(coalesce(p_tags, '{}')) > 0
      and public.post_tags(pp.tags, p.tags) ?| p_tags
      and pp.posted_by is distinct from auth.uid()
      and not (pp.paper_id = any (coalesce(p_exclude, '{}')))
      and not exists (
          select 1 from public.paper_status ps
          where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
            and (ps.saved or ps.status <> 'unread')
      )
      and not exists (
          select 1 from public.reactions r
          where r.paper_id = p.id and r.team_id = p_team and r.user_id = auth.uid()
      )
      and not exists (
          select 1 from public.comments c
          where c.paper_id = p.id and c.team_id = p_team and c.author_id = auth.uid()
      )
    order by
      -- Nearest first when there is a vector; papers without an embedding (or
      -- every paper, on cold start) follow, newest first.
      (case when p_query is not null and p.embedding is not null
            then p.embedding <=> p_query end) asc nulls last,
      pp.posted_at desc,
      pp.id desc
    limit greatest(coalesce(p_limit, 12), 0);
$$;

grant execute on function public.recommend_tagged(uuid, text[], extensions.vector, int, uuid[])
    to authenticated;
