-- 20260727090000_map_layouts.sql — persist the 2-D map layout across restarts.
--
-- The overview's t-SNE coordinates + KMeans assignment were only ever held in
-- the API's in-process cache, so every restart/deploy re-ran t-SNE in the
-- serving process — which is what forces the 1 GB VM (issue #103). This table
-- is the cold tier: one row per (team, signature), where `signature` is the
-- sha256 of the embedded-paper set already used by `trends` for cluster names.
-- Coordinates are deterministic for a signature (fixed seeds), so a stored row
-- never goes stale — it is simply superseded when the embedded set changes.
--
-- `coords` maps paper_id -> [x, y, cluster_index]; ~30 KB at 500 papers. The
-- API writes and reads it via the service role only (like the trends signature
-- rows) — clients always get layouts through /overview, never directly, so RLS
-- is enabled with no policies.

create table public.map_layouts (
    team_id    uuid not null references public.teams (id) on delete cascade,
    signature  text not null,
    coords     jsonb not null,
    created_at timestamptz not null default now(),
    primary key (team_id, signature)
);

alter table public.map_layouts enable row level security;

grant select, insert, update, delete on public.map_layouts to service_role;
