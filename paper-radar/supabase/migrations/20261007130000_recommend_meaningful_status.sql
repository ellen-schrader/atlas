-- 20261007130000_recommend_meaningful_status.sql — exclude engagement, not rows.
--
-- recommend_papers treats the mere existence of a paper_status row as "you have
-- seen this". That was true when the only way to get a row was to mark a paper
-- to-read or read. Since 20261006120000 split the field into two axes it is not:
-- a row can also be saved=false, status='unread', which carries no engagement at
-- all and is exactly what un-saving a paper, or un-marking it read, leaves
-- behind.
--
-- The consequence ran the wrong way round. Un-saving a paper means "put this
-- back in circulation", and it buried the paper in Discover permanently instead.
--
-- The app has been papering over this from the client: every writer that could
-- leave an all-default row followed up with a scoped DELETE (web/src/lib/
-- paperStatus.ts). That is a cleanup that has to be remembered at four call
-- sites, cannot be transactional with the write it follows, and fails silently —
-- one dropped request and the paper is gone from Discover with nothing in the UI
-- to say so and no way for the user to get it back. Asking the question properly
-- here removes the need for it, so this migration lands with those call sites
-- deleted.
--
-- Retroactive by construction: rows already stranded in production stop
-- excluding the moment this runs, so no backfill is needed and none is done.
-- Deleting them would be hygiene at the cost of racing a write in flight.
--
-- Body copied verbatim from 20260712180000_recommend_v2.sql. Only the
-- paper_status predicate changes; the candidate limit and the freshness re-rank
-- must not drift because this function was reissued.

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
