-- 20261008160000_follow_tags.sql — followed tags get their own Discover search.
--
-- profiles.interests ("optional explicit interest tags", 20260711163826) finally
-- gets a job: the tags a researcher follows, from Home's Trending or Settings.
-- Following is cheaper than writing a profile description, and while most
-- engagement happens in Teams it is the most direct way to steer Discover.
--
-- Discover searches each signal separately and interleaves the results
-- (api/app.py _discover_sources), so followed tags need a search of their own:
-- the lab's unseen papers that CARRY a followed tag, nearest to the given
-- vector first, or newest first when there is no vector (cold start). Ranking
-- only tagged papers is the point: a filter applied after a nearest-neighbour
-- search would drop exactly the followed-tag papers that are far from the
-- caller's other interests, which are the ones a follow exists to surface.
--
-- recommend_papers is untouched, and keeps its index-backed nearest-neighbour
-- path. Tags are matched with post_tags() (lab tags, else the paper's own), the
-- rule every tag surface uses since 20261008120000. Eligibility is the same as
-- recommend_papers' (20261007130000): not your own post, nothing you've saved,
-- started, reacted to or commented on.

create or replace function public.recommend_tagged(
    p_team  uuid,
    p_tags  text[],
    p_query extensions.vector(1024) default null,
    p_limit int default 12
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

grant execute on function public.recommend_tagged(uuid, text[], extensions.vector, int) to authenticated;
