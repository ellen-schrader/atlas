# Maps serving plan — persist the layout, move t-SNE off the serving process (issue #103)

Goal: the always-on API serves maps by *reading* persisted coordinates; the
sklearn/scipy import (~250–350 MB resident, forever) and the t-SNE spike move
into a short-lived process. Serving RSS drops to numpy-light → `fly.toml`
memory can drop from 1 GB toward 512 MB, which is what makes an always-on
machine (#104, Teams webhook) cheap.

## What exists today (verified in code)

- `api/app.py` `_build_overview` → `overview.cached_layout(team_id, papers)`
  for both `GET /overview` (lab) and `GET /maps/{id}/overview` (subset).
- `cached_layout` memoises in-process (`_LayoutCache`) — **one entry per
  team**, so switching lab ↔ map evicts and re-runs t-SNE every time.
- On miss, `compute_layout` imports sklearn **in the serving process**
  (t-SNE + KMeans), names clusters via Claude, and persists only the *names*
  to `trends` keyed by `signature` (sha256 of the sorted `(id, embedded_at)`
  set). Coordinates are never persisted.
- Embeds (the only thing that changes a signature) happen in three places:
  `_embed_and_store` (post, BackgroundTask), `_embed_batch` (bibtex import,
  BackgroundTask), `api/backfill_embeddings.py` (CLI).
- sklearn is imported lazily inside `compute_layout_2d` / `cluster_embeddings`
  only — nothing else in the API touches it. So if the serving process never
  calls `compute_layout`, it never imports sklearn. No dependency surgery
  needed; the win is pure process isolation.

## Design

### 1. Persist layouts: new `map_layouts` table (one JSONB row per signature)

```sql
create table public.map_layouts (
  team_id    uuid not null references public.teams(id) on delete cascade,
  signature  text not null,
  coords     jsonb not null,          -- {paper_id: [x, y, cluster_index]}
  created_at timestamptz not null default now(),
  primary key (team_id, signature)
);
alter table public.map_layouts enable row level security;
-- no policies: service-role only, same posture as trends signature writes
```

One row per layout = atomic upsert, no partial layouts, one read to hydrate.
~30 KB per row at 500 papers — negligible. Cluster *names* stay in `trends`
(unchanged, already signature-keyed); `map_layouts` adds the missing coords +
per-paper cluster assignment.

GC: on write, delete the team's rows older than 60 days. A long-stable map
whose row ages out just recomputes once. (Touch-on-read `last_used_at` is a
refinement we can add if that ever annoys.)

### 2. Recompute runs in an ephemeral subprocess — `api/layout_job.py`

New module, runnable two ways:

- `python -m api.layout_job lab <team_id>` — the whole-lab embedded set
- `python -m api.layout_job map <map_id>` — the map's member set (via the
  `map_members` RPC, service role)

The job (service role throughout): fetch the paper set fresh → compute
signature → skip if `map_layouts` already has it → t-SNE + KMeans (the only
place sklearn is ever imported) → name clusters via the existing
`_load_names`/`name_clusters`/`_store_names` path → upsert `map_layouts`.
Idempotent and deterministic (fixed seeds), so concurrent duplicate runs are
harmless.

The API spawns it with `subprocess.Popen([sys.executable, "-m", ...])`. The
child imports sklearn, works for a few seconds, exits — the serving RSS never
grows. A small in-process supervisor (one record per lab/map target) provides:
dedupe (never two children per target), a rerun flag (data changed mid-job →
the next poll respawns once over the final set), a 30 s failure cooldown (a
crashing job can't become a t-SNE-per-poll loop), a concurrency cap (2
children, so parallel misses can't stack sklearn spikes and OOM the VM), and
reaping (finished handles are poll()ed and dropped — no zombies).

Why subprocess and not a separate Fly worker/scheduled job: smallest change,
no new infra or tokens, triggers stay in-process, and it fully achieves the
RSS-floor goal. The transient spike still lands on the same VM — handled by
sizing + swap (below). A truly off-box worker (Fly Machines API) stays
available as a follow-up if 256 MB ever matters.

### 3. Serving path: read-only, with a "computing" state

`cached_layout` becomes a three-tier read:

1. **Hot** — `_LayoutCache`, rekeyed to `(team_id, signature)` with a small
   LRU (~8 entries) so lab ↔ map switches stop evicting each other.
2. **Warm** — `map_layouts` row + `trends` names by signature → hydrate cache.
3. **Miss** — spawn the layout job, return `status: "computing"`.

`OverviewResponse` gains `status: "ready" | "computing"`. A computing response
still carries `stats`/`total`/`embedded` (none of those need the layout) with
empty `points`/`clusters`. The web client (`lib/api.ts`, `types.ts`,
`Map.tsx` / `MapDashboard.tsx` / `App.tsx` insights view) shows a lightweight
"computing the map…" state and polls every ~3 s until ready. Recompute takes
a few seconds, so this state is rare and brief — only a brand-new signature's
first viewer sees it.

### 4. Proactive trigger on embed

After `_embed_and_store` and `_embed_batch` finish, enqueue the **lab** layout
job for the team (same running-set dedupe). In the common case the layout is
already persisted before anyone opens Insights, so nobody ever sees
"computing". Per-map layouts stay lazy (maps are unbounded; each recomputes on
first view after its member set changes). `backfill_embeddings.py` gets a
note to run the job manually after a backfill (or we add a `--relayout` flag).

### 5. Shrink the VM (follow-up commit, after measuring)

With serving sklearn-free, measure on Fly: serving RSS under concurrent map
reads (expect ~150–220 MB) and job peak (expect ~350–450 MB, dominated by the
sklearn import). Then in `fly.toml`:

```toml
[[vm]]
  memory = "512mb"
  swap_size_mb = 512   # absorbs the transient job spike, never steady-state
```

512 MB (~$3.30/mo always-on) is the realistic target; 256 MB would require
off-box compute and isn't worth it now. Flip `min_machines_running` in #104's
PR, not here — this branch just makes it affordable.

## What does NOT change

- The t-SNE algorithm, seeds, cluster count (`auto_k`), and the rendered map
  are identical — this is a serving-path change only (issue's proposals 1–2).
- `trends` naming/persistence semantics (per-signature replace) unchanged.
- sklearn stays in `pyproject.toml` / the image — the job needs it there.

## Tests

- Round-trip: store → load a layout by signature; GC of old rows.
- `cached_layout` tiers: hot hit, warm hit (no job spawned), miss (job
  spawned once, deduped, `computing` returned).
- Regression: after serving a warm `/overview`, `"sklearn"` ∉ `sys.modules`
  in the serving process.
- Job: lab + map modes against seeded data; idempotent re-run skips.
- Update `test_api.py` overview assertions for the `status` field; existing
  `test_overview.py` (pure compute fns) unchanged.

## Sequencing (single PR, reviewable commits)

1. Migration + `map_layouts` store/load module.
2. `api/layout_job.py` (compute + name + persist, CLI entry).
3. `cached_layout` rewrite: three tiers, `status` field, spawn-on-miss,
   embed-time triggers.
4. Web: computing state + polling.
5. (Separate, after prod measurement) `fly.toml` memory drop.

Migration workflow per project rules: write the file under
`supabase/migrations/`, apply locally with `supabase migration up` (never
`db push`); prod applies on merge to main.

## Watch-outs

- Suspend-on-idle can freeze a mid-flight job (same as background embeds
  today) — harmless: the layout simply isn't persisted, and the next viewer's
  miss re-spawns it. Idempotent by construction.
- Shared 1 vCPU: the job competes with serving for a few seconds. Acceptable;
  can `nice` the child if it ever shows.
- Old web clients ignore `status` and briefly render an empty map on a fresh
  signature — cosmetic, self-heals on reload.
