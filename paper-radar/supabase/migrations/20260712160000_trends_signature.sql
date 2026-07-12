-- 20260712160000_trends_signature.sql — persist LLM theme names across restarts.
--
-- The overview computes UMAP + KMeans deterministically, but naming the clusters
-- costs a Claude call. Storing the names in `trends` keyed by a `signature` (a
-- hash of the embedded-paper set) lets the API reuse them instead of re-calling
-- the LLM every cold start — the clusters are stable for a given signature.
--
-- `cluster_index` records which KMeans cluster each stored name belongs to (the
-- assignment is deterministic for a signature, so index → name is stable).

alter table public.trends add column if not exists signature     text;
alter table public.trends add column if not exists cluster_index int;

create index if not exists trends_team_signature_idx
    on public.trends (team_id, signature);
