-- 20260712140000_semantic_search.sql — vector-search RPCs over paper embeddings.
--
-- Both functions are SECURITY INVOKER (the default): they read `paper_posts`
-- and `papers`, so the caller's RLS — lab membership via is_team_member() —
-- applies unchanged. `set search_path = public, extensions` makes pgvector's
-- `<=>` (cosine distance) operator resolvable regardless of the caller's
-- search_path (the extension lives in the `extensions` schema).
--
-- Embeddings are unit-norm (Voyage), so `1 - (a <=> b)` is cosine similarity
-- in [-1, 1] and the existing HNSW index (init migration) serves the ORDER BY.

-- Rank a lab's posts against a query embedding. The query vector is computed
-- by the API service (`POST /search/semantic`) — the embedding key is
-- server-side only, so the browser never calls this directly.
create or replace function public.match_papers(
    p_team  uuid,
    p_query extensions.vector(1024),
    p_limit int default 20
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
    order by p.embedding <=> p_query
    limit greatest(coalesce(p_limit, 20), 0);
$$;

-- Lab papers most similar to one of the lab's papers ("find similar" in the
-- paper modal). Needs no query embedding, so the client calls it directly:
--   supabase.rpc('similar_papers', { p_team, p_paper })
-- RLS on `papers` means a caller whose lab never posted p_paper gets no rows.
create or replace function public.similar_papers(
    p_team  uuid,
    p_paper uuid,
    p_limit int default 6
)
returns table(post_id uuid, paper_id uuid, title text, venue text, year int, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    select pp.id, pp.paper_id, p.title, p.venue, p.year,
           (1 - (p.embedding <=> src.embedding))::real
    from public.papers src
    join public.paper_posts pp on pp.team_id = p_team and pp.paper_id <> src.id
    join public.papers p on p.id = pp.paper_id and p.embedding is not null
    where src.id = p_paper
      and src.embedding is not null
    order by p.embedding <=> src.embedding
    limit greatest(coalesce(p_limit, 6), 0);
$$;

grant execute on function public.match_papers(uuid, extensions.vector, int) to authenticated;
grant execute on function public.similar_papers(uuid, uuid, int)            to authenticated;
