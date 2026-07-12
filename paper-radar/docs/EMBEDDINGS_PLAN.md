# Embeddings: semantic search + map overview — implementation plan

Phase 6 of `MIGRATION_PLAN.md` (§10): compute paper embeddings, store them in
pgvector, and build the two features they unlock — **semantic search** (plus
"find similar" on a paper) and a **2-D map overview** of the lab's collection.

Status: implemented on branch `llm-paper-embeddings-implementation-plan`.

Ongoing-work check: `redesign/foundations` (other worktree) only touches
`web/src/index.css` and adds new presentational components (Chip, Cover,
EngagementSummary, SourceLabel) — no schema, API, or route changes. This work
adds new files plus small edits to `Layout.tsx` / `App.tsx` / `Papers.tsx` /
`PaperModal.tsx`, so conflict risk is low.

---

## 1. Decisions

### 1.1 Embedding provider: Voyage AI `voyage-4`, 1024 dimensions

Per plan §13.1 ("hosted API for MVP, behind a swappable interface"):

- **Anthropic does not offer an embeddings endpoint**; its docs recommend
  Voyage AI. `voyage-4` is the current balanced general-purpose model
  (32K context, 1024-dim default).
- **1024 dims matches the schema exactly** — `papers.embedding` and
  `profiles.profile_vec` are already `vector(1024)`, and
  `papers_embedding_idx` is already an HNSW index with
  `vector_cosine_ops`. No `ALTER` needed.
- Voyage embeddings are **L2-normalized**, so cosine distance (`<=>`) is the
  right operator and the existing index applies as-is.
- The client lives behind a small module (`api/embeddings.py`) with a
  `embed_texts(texts, input_type=...)` surface — swapping to SPECTER2/SciNCL
  later (the §13.1 benchmark) is a config change plus a re-embed run.
- Implemented with **stdlib `urllib`** (same style as `ingest/metadata.py`) —
  no new dependency; retries on 429/5xx.

Config (env, via `api/config.py`): `VOYAGE_API_KEY`, `EMBEDDING_MODEL`
(default `voyage-4`), `EMBEDDING_DIM` (default `1024`).

### 1.2 What gets embedded

`title + "\n\n" + abstract` (falling back to title alone), embedded with
`input_type="document"`. Search queries use `input_type="query"` — Voyage
prepends retrieval-tuned prompts per side (the same idea as the bge
`query_prefix` in the Streamlit prototype's `embed/embed.py`).

`profiles.profile_vec` (taste ranking) is **out of scope** — that's phase 7.

### 1.3 Where embedding happens

All embedding runs in the **FastAPI service** (it holds the Voyage key and the
service-role key; RLS makes `papers` writes service-role-only):

- **On post** — `POST /posts` schedules a FastAPI `BackgroundTask` after the
  response is sent: embed the paper and
  `update papers set embedding, embedded_at where id = ... and embedded_at is null`.
  Posting stays fast; a failed embed is logged and picked up by backfill.
  (A real worker/queue is phase 8; BackgroundTasks is enough at this scale.)
- **Backfill / re-embed** — `python -m api.backfill_embeddings` embeds every
  paper with `embedded_at is null` (or `--all` to re-embed after a model
  change), batching requests.

### 1.4 Semantic search

- New migration `..._semantic_search.sql` with two `security invoker` SQL
  functions (caller's RLS applies, same pattern as `search_rpcs.sql`):
  - `match_papers(p_team uuid, p_query vector(1024), p_limit int)` →
    `(post_id, paper_id, similarity)` ordered by cosine distance.
  - `similar_papers(p_team uuid, p_paper uuid, p_limit int)` →
    same shape, seeded by an existing paper's embedding (no query embedding
    needed, so the **frontend calls this RPC directly**).
- **`POST /search/semantic`** (FastAPI, JWT required): embeds the query
  (`input_type="query"`), calls `match_papers` **as the user** via
  `user_client(token)` so RLS scopes results to the lab, hydrates the matching
  posts (`paper_posts` + joined `papers`), and returns them with similarity
  scores.
- UI: `Papers.tsx` gets a *Text / Semantic* search-mode toggle. Semantic mode
  submits the query to `/search/semantic` and renders ranked results with
  scores; text mode keeps the existing client-side filter.
- "Find similar": `PaperModal` shows the top similar lab papers via
  `supabase.rpc("similar_papers", ...)`, each clickable.

### 1.5 Map overview

- **`GET /map?team_id=...`** (FastAPI, JWT required): fetches the lab's
  embedded papers **as the user** (RLS-scoped), projects the embeddings to 2-D
  with the existing `paper_radar.embed.index.compute_umap` (umap-learn is
  already a dependency; fixed `random_state` for stable layouts), and returns
  `{points: [{paper_id, x, y, title, venue, year, tags}]}`.
- Coordinates are cached **in-memory per team**, keyed by the set of
  `(paper_id, embedded_at)` pairs — any newly embedded paper invalidates the
  cache. UMAP on a few hundred papers takes seconds (first call pays the
  numba JIT), so cache hits matter; no DB table needed yet.
- UI: new **`/map` route** ("Map" in the sidebar) rendering an SVG scatter —
  no chart library added. Hover shows title/venue/year; click opens the
  existing `PaperModal`. Points colored by publication year (quantized), with
  a small legend and an "n of m papers embedded" note while backfill is
  incomplete.

### 1.6 Security notes

- Query/user traffic always goes through `user_client(token)` (anon key +
  JWT), so lab isolation stays in RLS — the service never hand-filters by
  team, matching §7 of the migration plan.
- The Voyage key and service-role key remain server-side only.
- Paper text sent to Voyage is title+abstract of papers the lab posted —
  same trust level as the existing metadata pipeline.

---

## 2. Changes by file

| File | Change |
|---|---|
| `api/embeddings.py` | **new** — Voyage client (stdlib urllib, batching, retries), `embed_texts` / `embed_query` / `paper_text` |
| `api/config.py` | add `voyage_api_key`, `embedding_model`, `embedding_dim` |
| `api/app.py` | embed-on-post background task; `POST /search/semantic`; `GET /map` (+ in-memory map cache) |
| `api/backfill_embeddings.py` | **new** — batch backfill script (service role) |
| `api/.env.example` | add `VOYAGE_API_KEY` |
| `supabase/migrations/20260712140000_semantic_search.sql` | **new** — `match_papers`, `similar_papers` RPCs + grants |
| `tests/test_embeddings.py` | **new** — client batching/retry/parsing with stubbed HTTP; map-cache invalidation |
| `tests/test_api.py` | auth guards for `/search/semantic` and `/map` |
| `web/src/lib/api.ts` | `semanticSearch()`, `fetchMap()` |
| `web/src/lib/types.ts` | `SemanticHit`, `MapPoint` |
| `web/src/routes/Papers.tsx` | Text/Semantic search-mode toggle + ranked results |
| `web/src/components/PaperModal.tsx` | "Similar papers" section (`similar_papers` RPC) |
| `web/src/routes/Map.tsx` | **new** — SVG scatter of the lab's papers |
| `web/src/App.tsx`, `web/src/routes/Layout.tsx` | `/map` route + sidebar entry |
| `api/README.md` | document the new endpoints + backfill |

## 3. Verification

- `uv run pytest` (existing + new tests, offline).
- `uv run ruff check .`
- `npm run typecheck` in `web/`.
- Migrations apply cleanly on a fresh `supabase db reset` (SQL is
  self-contained and mirrors the reviewed `search_rpcs.sql` pattern).

## 4. Out of scope (later phases)

- Profile embedding + per-user relevance ranking (phase 7).
- Trend clusters table population (phase 7).
- A real worker/queue and scheduled re-embeds (phase 8).
- Embedding-model benchmark (SPECTER2/SciNCL vs voyage-4) — the swappable
  interface is the enabler; run it before building phase-7 relevance.
