-- 20260712170000_recommendations.sql — personalized paper recommendations.
--
-- `recommend_papers` ranks a lab's posts against a per-user "taste" vector
-- (computed by the API from the user's profile + engagement, `GET /recommendations`),
-- EXCLUDING papers the caller has already seen — so we never recommend a paper
-- they've read, saved, reacted to, or commented on. This is the discover feed.
--
-- SECURITY INVOKER (default) + `set search_path = public, extensions` — mirrors
-- match_papers: the caller's RLS scopes rows to their labs, and pgvector's `<=>`
-- (cosine distance) resolves regardless of the caller's search_path. Embeddings
-- are unit-norm, so `1 - (a <=> b)` is cosine similarity and the HNSW index
-- (papers_embedding_idx) serves the ORDER BY.
--
-- The "seen" exclusions filter on auth.uid() explicitly: paper_status RLS is
-- already per-user, but reactions/comments RLS is TEAM-WIDE (a member sees all of
-- the lab's), so without the user_id/author_id filter we'd exclude papers the
-- whole team engaged with, not just this user.

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
    select pp.id, pp.paper_id, (1 - (p.embedding <=> p_query))::real
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and p.embedding is not null
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
    order by p.embedding <=> p_query
    limit greatest(coalesce(p_limit, 12), 0);
$$;

grant execute on function public.recommend_papers(uuid, extensions.vector, int) to authenticated;
