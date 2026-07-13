-- 20260713180000_maps_threshold.sql — a relevance floor on map membership.
--
-- M0 membership was top-N by seed similarity with NO floor, so on a small corpus
-- every paper was a "member". Add a per-map `config.min_similarity` (default 0.35
-- cosine — an empirical "related" floor, tunable via PATCH /maps): keep a paper
-- only if it clears the floor, EXCEPT pinned papers, which are always in. A sibling
-- stats function reports how many papers fall just below, so the dashboard can
-- offer "N more are loosely related — broaden?".

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
    order by pinned desc, similarity desc nulls last
    limit greatest(coalesce(p_limit, 100), 0);
$$;

-- Counts either side of the floor, so the UI can nudge "broaden" without pulling
-- the below-floor papers themselves. Same candidate set as map_members.
create or replace function public.map_member_stats(p_map uuid)
returns table(in_scope int, below int)
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
        select case
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
    select
        count(*) filter (
            where pinned or (similarity is not null and similarity >= (select min_sim from m))
        )::int as in_scope,
        count(*) filter (
            where not pinned and (similarity is null or similarity < (select min_sim from m))
        )::int as below
    from candidates;
$$;

grant execute on function public.map_member_stats(uuid) to authenticated;
