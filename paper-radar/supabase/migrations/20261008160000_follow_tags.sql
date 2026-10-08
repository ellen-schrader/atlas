-- 20261008160000_follow_tags.sql — followed tags feed Discover.
--
-- profiles.interests ("optional explicit interest tags", 20260711163826) finally
-- gets a job: the tags a researcher follows, from Home's Trending or Settings.
-- Following is cheaper than writing a profile description, and while most
-- engagement happens in Teams it is the most direct way to steer Discover.
--
-- recommend_papers gains p_tags:
--   * candidates are the taste vector's nearest papers AS BEFORE, plus the
--     newest papers carrying a followed tag — otherwise a followed tag could only
--     reorder papers that were already close to the taste, and a paper outside
--     that pool would never surface however it was tagged;
--   * a paper with a followed tag gets +0.05 on the same score that adds the
--     freshness bonus: enough to lift it past near-ties, not enough to outrank
--     a clearly closer paper.
-- Tags are matched with post_tags() (lab tags, else the paper's own), the rule
-- every tag surface uses since 20261008120000.
--
-- `eligible` is shared by both pools, so it is computed once per call and the
-- nearest-neighbour order runs over the lab's eligible papers rather than the
-- global vector index: at a lab's scale (hundreds to low thousands of papers)
-- that is milliseconds.
--
-- The 3-argument version is dropped rather than overloaded: PostgREST picks a
-- function by its named arguments, and two candidates for a 3-argument call
-- would be ambiguous. The new p_tags defaults to '{}', so an API still sending
-- three arguments during a deploy is served by the new function unchanged.

drop function if exists public.recommend_papers(uuid, extensions.vector, int);

create or replace function public.recommend_papers(
    p_team  uuid,
    p_query extensions.vector(1024),
    p_limit int default 12,
    p_tags  text[] default '{}'
)
returns table(post_id uuid, paper_id uuid, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    with eligible as (
        select pp.id as post_id, pp.paper_id, pp.posted_at, pp.tags as post_tags,
               p.tags as paper_tags, p.embedding
        from public.paper_posts pp
        join public.papers p on p.id = pp.paper_id
        where pp.team_id = p_team
          and p.embedding is not null
          and pp.posted_by is distinct from auth.uid()  -- not one you posted
          -- Unchanged from 20261007130000: engagement that MEANS something hides
          -- a paper; the all-default row left by un-saving does not.
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
    ),
    by_taste as (
        select post_id from eligible
        order by embedding <=> p_query
        limit greatest(coalesce(p_limit, 12), 0) * 5
    ),
    by_tags as (
        select post_id from eligible
        where cardinality(p_tags) > 0
          and public.post_tags(post_tags, paper_tags) ?| p_tags
        order by posted_at desc
        limit greatest(coalesce(p_limit, 12), 0) * 2
    ),
    candidates as (
        select e.post_id, e.paper_id, e.posted_at,
               (1 - (e.embedding <=> p_query))::real as similarity,
               (cardinality(p_tags) > 0
                and public.post_tags(e.post_tags, e.paper_tags) ?| p_tags) as followed
        from eligible e
        where e.post_id in (select post_id from by_taste union select post_id from by_tags)
    )
    select post_id, paper_id, similarity
    from candidates
    order by
        similarity
        + 0.06 * exp(- extract(epoch from (now() - posted_at)) / (86400.0 * 30))
        + case when followed then 0.05 else 0 end desc
    limit greatest(coalesce(p_limit, 12), 0);
$$;

grant execute on function public.recommend_papers(uuid, extensions.vector, int, text[]) to authenticated;
