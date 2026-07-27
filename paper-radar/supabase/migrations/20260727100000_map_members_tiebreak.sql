-- 20260727100000_map_members_tiebreak.sql — deterministic order at the cap.
--
-- map_members ordered by (pinned desc, similarity desc nulls last) with no
-- further tiebreaker, so among equal-similarity rows the order — and therefore
-- WHICH rows survive `limit p_limit` — was unspecified. That never mattered
-- for display, but the map layout job (api/layout_job.py) now re-fetches the
-- member set independently of the serving request and derives the layout's
-- signature from it: if the two calls truncate a tie at the cap differently,
-- the job persists a layout serving never asks for and the map dashboard polls
-- "computing" forever. paper_id as the final key makes every call return the
-- same set. Body otherwise identical to 20260713180000_maps_threshold.sql.

create or replace function public.map_members(p_map uuid, p_limit int default 100)
returns table(post_id uuid, paper_id uuid, similarity real, pinned boolean)
language sql
stable
set search_path = public, extensions
as $$
    with m as (
        select team_id, seed_embedding, config,
               coalesce((config ->> 'min_similarity')::real, 0.35) as min_sim
        from public.maps
        where id = p_map
    ),
    ex as (
        select jsonb_array_elements_text(
            coalesce((select config -> 'excluded' from m), '[]'::jsonb)
        )::uuid as pid
    ),
    pin as (
        select jsonb_array_elements_text(
            coalesce((select config -> 'pinned' from m), '[]'::jsonb)
        )::uuid as pid
    ),
    candidates as (
        select pp.id as post_id,
               pp.paper_id,
               case
                   when (select seed_embedding from m) is not null
                   then (1 - (p.embedding <=> (select seed_embedding from m)))::real
               end as similarity,
               (pp.paper_id in (select pid from pin)) as pinned
        from public.paper_posts pp
        join public.papers p on p.id = pp.paper_id
        where pp.team_id = (select team_id from m)
          and p.embedding is not null
          and pp.paper_id not in (select pid from ex)
    )
    select post_id, paper_id, similarity, pinned
    from candidates
    where pinned or (similarity is not null and similarity >= (select min_sim from m))
    order by pinned desc, similarity desc nulls last, paper_id
    limit greatest(coalesce(p_limit, 100), 0);
$$;
