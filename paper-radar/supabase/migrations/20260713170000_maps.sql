-- 20260713170000_maps.sql — topic maps (a.k.a. map dashboards, v2).
--
-- A map is a *subject the lab tracks* ("Ovarian Cancer", "ECM remodeling"), not a
-- saved filter. Its membership is a live semantic query — papers near a seed
-- phrase — plus light curation (pin a must-have, exclude a false positive), so the
-- set stays current as new papers arrive. See docs/MAP_DASHBOARDS_V2_PROPOSAL.md.
--
-- This migration is the data foundation (Milestone 0): the table, its RLS, and the
-- membership RPC. The scatter / papers list / AI summary build on top of these.

create table public.maps (
    id             uuid primary key default gen_random_uuid(),
    team_id        uuid not null references public.teams (id) on delete cascade,
    created_by     uuid not null references public.profiles (id),
    name           text not null,
    seed           text not null,                     -- the phrase the user typed
    seed_embedding extensions.vector(1024),           -- embedded by the API (Voyage key is server-side)
    config         jsonb not null default '{}'::jsonb, -- { pinned: [uuid], excluded: [uuid] }
    visibility     text not null default 'lab' check (visibility in ('lab', 'private')),
    ai_summary     jsonb,                             -- { text, cited_ids, generated_at, n_papers } (Milestone 4)
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index maps_team_idx on public.maps (team_id);

alter table public.maps enable row level security;

-- A lab map is visible to every member; a private map only to its creator. Either
-- way the caller must be a member of the map's lab (never cross-lab).
create policy maps_select on public.maps for select
    to authenticated using (
        is_team_member(team_id) and (visibility = 'lab' or created_by = auth.uid())
    );

-- You create maps in your own labs, authored as yourself. `created_by = auth.uid()`
-- is what makes "the owner edits the definition" enforceable below.
create policy maps_insert on public.maps for insert
    to authenticated with check (is_team_member(team_id) and created_by = auth.uid());

-- Only the creator edits or deletes a map (rename, re-seed, pin/exclude, share).
-- WITH CHECK also re-asserts lab membership, symmetric with maps_insert, so a map
-- can never be moved into a lab its creator doesn't belong to.
create policy maps_update on public.maps for update
    to authenticated
    using (created_by = auth.uid())
    with check (created_by = auth.uid() and is_team_member(team_id));
create policy maps_delete on public.maps for delete
    to authenticated using (created_by = auth.uid());

grant select, insert, update, delete on public.maps to authenticated;
-- The API caches the AI summary (maps.ai_summary) via the service role after it has
-- RLS-checked the caller can see the map, so the backend role needs table privileges.
grant select, insert, update, delete on public.maps to service_role;

-- === membership =============================================================
-- The live member set: the map's team posts ranked by cosine similarity to the
-- seed embedding, with pinned papers forced to the top and excluded papers
-- removed. SECURITY INVOKER (default) so the caller's RLS applies — a caller who
-- can't see the map gets no rows, and paper_posts stay lab-scoped. `set search_path`
-- makes pgvector's `<=>` resolvable (extension lives in the `extensions` schema).
--
-- Embeddings are unit-norm (Voyage), so `1 - (a <=> b)` is cosine similarity in
-- [-1, 1] and the HNSW index (init migration) serves the ORDER BY. `nulls last`
-- keeps a not-yet-embedded seed from hiding the pinned papers.
--
-- NOTE (M0): membership is top-N by similarity with NO relevance floor yet, so on a
-- corpus smaller than p_limit every lab paper comes back regardless of the seed. A
-- similarity threshold is a planned refinement (see the implementation plan); until
-- then callers should treat the tail of the ranking as weakly-related, not "in".
create or replace function public.map_members(p_map uuid, p_limit int default 100)
returns table(post_id uuid, paper_id uuid, similarity real, pinned boolean)
language sql
stable
set search_path = public, extensions
as $$
    with m as (
        select team_id, seed_embedding, config
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
    order by pinned desc, similarity desc nulls last
    limit greatest(coalesce(p_limit, 100), 0);
$$;

grant execute on function public.map_members(uuid, int) to authenticated;
