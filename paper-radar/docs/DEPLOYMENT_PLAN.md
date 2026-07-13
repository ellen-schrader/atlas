# Deployment plan

Getting the hosted stack (React web + FastAPI + Supabase) onto the internet.
This is the concrete follow-through on MIGRATION_PLAN.md §12 ("Environments &
deployment"). Status: **proposal — agree on this before building.**

## Where we are

The three tiers already exist, and one of them is already deployed:

| Tier | What | Today |
|---|---|---|
| Database + auth + storage | Supabase (Postgres, RLS, mood-board bucket) | **Already hosted** — managed project `eegjxioiidymmiizflkh.supabase.co`; both `api/.env` and `web/.env.local` point at it |
| API | FastAPI (`api.app:app`), Voyage embeddings over HTTP, `/health` endpoint | Runs locally via uvicorn only — no Dockerfile, no host |
| Web | Vite + React SPA (react-router), static build via `vite build` | Dev server only; talks to the API through `VITE_API_URL` (defaults to `127.0.0.1:8000`) |

So "deploying" means: containerize + host the API, build + host the SPA, and
wire the three tiers together with env vars. No data migration is needed.

## Recommended targets

- **Web → Vercel** (or Cloudflare Pages — either works; both are free-tier
  fine for a lab). Static output, SPA rewrite to `index.html`.
- **API → Fly.io** (or Railway/Render). A container host, per MIGRATION_PLAN
  §12. The API is light — it never touches sentence-transformers/torch or
  faiss (embeddings are Voyage API calls; the heavy deps are legacy
  Streamlit-era code), and umap/sklearn load lazily only for `/map` — so a
  small instance (512 MB–1 GB) should do.
- **DB stays on Supabase** as-is.

## Phases

### Phase 1 — environment & build prep (this branch)

1. ~~Copy `.env` files from the main worktree~~ ✓ (`paper-radar/.env`,
   `api/.env`, `web/.env.local` — all gitignored).
2. ✓ **Slim the Python install for the API image.** `pip install .[api]` today
   drags in sentence-transformers/torch and streamlit via the base
   dependencies (~2–3 GB image, slow cold builds). Move those two to a
   `legacy` extra in `pyproject.toml` (faiss-cpu too — `embed/index.py` now
   imports it lazily, so only the local-index CLI path needs it).
   umap/scikit-learn stay in the base — the API's `/map` endpoint uses them
   (`api/overview.py` → `paper_radar.embed.index`). The Streamlit app keeps
   working via `uv sync --extra dev --extra legacy`.
3. ✓ **Add `api/Dockerfile`** — `python:3.12-slim`, install with `uv` from the
   lockfile (`uv sync --frozen --extra api --no-dev`), run
   `uvicorn api.app:app --host 0.0.0.0 --port 8080`. `/health` already exists
   for the host's health checks. Note: cryptography>=47 is pinned back to
   46.x on linux/aarch64 only (`[tool.uv] constraint-dependencies`, marker-
   scoped) — its aarch64 wheels SIGILL in the Docker Desktop VM; amd64 prod
   builds and dev machines stay current. Retest the pin on a version bump.
4. ✓ **Verify prod builds locally**: `docker build` (2 GB image, no torch) +
   container smoke test against hosted Supabase (`/health`, `/resolve`);
   `npm run build` in `web/` (tsc + vite) passes.

### Phase 2 — database hygiene (small, before first deploy)

5. ✓ Confirmed the hosted project is fully migrated:
   `supabase link --project-ref eegjxioiidymmiizflkh` + `supabase db push` →
   "Remote database is up to date"; `supabase migration list` shows all 16
   local migrations applied remotely.
6. ✓ **Backups (stopgap).** The org is on the **free plan** (no automated
   backups, no PITR), so `.github/workflows/db-backup.yml` dumps schema +
   data nightly (03:00 UTC) to private workflow artifacts, 30-day retention.
   Not covered: the mood-board storage bucket. Upgrade to Pro (daily
   backups + PITR option) once the lab depends on the data. The
   `service_role` key is server-side only (API env, never the web).

### Phase 3 — first manual deploy (done 2026-07-12)

7. ✓ **API on Fly.io**: app `paper-radar-api`, region lhr, 1× shared-cpu
   1 GB machine, auto-stop when idle (`fly.toml` in this directory). Live at
   **https://paper-radar-api.fly.dev**. Secrets set via `fly secrets import`:
   `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
   `VOYAGE_API_KEY`, `ANTHROPIC_API_KEY`, `CORS_ORIGINS` (both web domains +
   localhost dev ports).
8. ✓ **Web on Vercel**: project `paper-radar` (linked from `web/`,
   `.vercel/project.json`), Vite preset, SPA fallback via `web/vercel.json`.
   Production domain **https://atlas-papers.vercel.app** (added as a project
   domain — `paper-radar.vercel.app` was taken by a stranger's project).
   Note: the default `paper-radar-ellen-schrader1.vercel.app` and per-deploy
   URLs sit behind Vercel SSO deployment protection; the added production
   domain is public. Build-time env on Vercel: `VITE_SUPABASE_URL`,
   `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL=https://paper-radar-api.fly.dev`.
9. ✓ **Supabase auth config**: Site URL → https://atlas-papers.vercel.app;
   allow-list covers both web domains + localhost (management API,
   `/config/auth`).
10. ✓ **Smoke test the real flows** (browser, 2026-07-12): sign up, post a
    paper by URL, comment, semantic search, mood board upload, map view all
    work in production. Untested: @mention notify (needs a second lab
    member — retest when one joins, or sign up a second account into the
    same lab).

### Phase 4 — CI/CD

11. ✓ `.github/workflows/deploy.yml`: on push to `main` (paths-filtered to
    `paper-radar/**`), `supabase link` + `db push`, then `fly deploy
    --remote-only` — migrations land before the API, per MIGRATION_PLAN §12.
    If `db push` needs the database password in headless CI, add a
    `SUPABASE_DB_PASSWORD` repo secret and pass it to the link step.
12. ✓ **Repo secrets**: `FLY_API_TOKEN` and `SUPABASE_ACCESS_TOKEN` are set.
    If the first CI `db push` fails to authenticate headless, also set
    `SUPABASE_DB_PASSWORD` — the workflow already passes it through when
    present.
13. ✓ **Web via Vercel git integration**: GitHub App installed and the repo
    connected (production branch `main`, `rootDirectory` `paper-radar/web`,
    preview + production env vars set) — PR previews and production web
    deploys are automatic. Manual CLI deploys still work:
    `vercel deploy --prod` from `paper-radar/web` (the CLI ignores
    `rootDirectory` for uploads from that directory).

### Known issue — Fly trial plan (needs a card)

The Fly account is on the trial plan: **machines are force-stopped after 5
minutes** ("Trial machine stopping. To run for longer than 5m0s, add a credit
card" in the logs). Consequences until a card is added at fly.io: the
in-process layout cache never survives, numba's JIT for the map rarely gets 5
uninterrupted minutes on the shared vCPU (map appears to never load), and
users hitting the ~35 s cold boot window see 502s (which Fly Doctor
misreports as "app not listening on the expected port"). The startup warmup
(api/app.py) and baked numba cache (api/Dockerfile) shrink the pain; the
5-minute kill itself only goes away with a card.

### Phase 5 — later / as needed

- Custom domain + TLS on both hosts (defaults `*.vercel.app` / `*.fly.dev`
  work day one).
- Uptime check against `/health`; Fly log drain or just `fly logs` initially.
- Background enrichment worker (summary/tags via Claude) — currently
  in-process `BackgroundTasks`; fine at lab scale, revisit if posts spike.
- The stdio MCP server (`atlas_mcp`) stays local — it's a desktop-side tool,
  nothing to deploy.

## Env var wiring (prod)

```
web (build-time)                api (runtime secrets)
  VITE_SUPABASE_URL      ──┐      SUPABASE_URL            ──┐
  VITE_SUPABASE_ANON_KEY ──┼──►   SUPABASE_ANON_KEY       ──┼──► Supabase (hosted)
  VITE_API_URL ──► api           SUPABASE_SERVICE_ROLE_KEY ─┘
                                 VOYAGE_API_KEY  ──► Voyage
                                 ANTHROPIC_API_KEY ──► Claude (enrichment)
                                 CORS_ORIGINS = web origin
```

## Open decisions

1. **Hosts** — decided: Vercel for the web. Fly.io for the API (the API can't
   go on Vercel serverless — `POST /posts` embeds in-process via
   `BackgroundTasks` after the response, which serverless kills).
2. **Custom domain now or later?** Later is fine; changing it only touches
   `CORS_ORIGINS`, `VITE_API_URL`, and Supabase auth URLs.
3. **Dep split (phase 1, step 2)** — touching `pyproject.toml` affects the
   Streamlit legacy app's install command. Cheap now, annoying later; I'd do
   it in this branch.
