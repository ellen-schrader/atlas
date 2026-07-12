-- 20260712180000_recommend_v2.sql — recommendation quick wins.
--
-- Two improvements over the v1 recommend_papers:
--   1. Exclude papers the caller POSTED themselves — you've obviously seen a paper
--      you added to the lab, so it shouldn't come back as a recommendation.
--   2. A mild freshness re-rank — for a "what to read next" feed, a slightly
--      less-similar but recently-posted paper should be able to edge out a stale
--      one. We keep the HNSW index doing the expensive nearest-neighbor step
--      (order by distance, take 5×limit as candidates), then re-rank that small
--      set by `similarity + w · recency`, where recency decays with a ~30-day
--      scale from when the paper was posted to the lab. `w` is small so
--      similarity still dominates; it only breaks near-ties toward fresh papers.

create or replace function public.recommend_papers(
    p_team  uuid,
    p_query extensions.vector(1024),
    p_limit int default 12
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
          and not exists (
              select 1 from public.paper_status ps
              where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
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
