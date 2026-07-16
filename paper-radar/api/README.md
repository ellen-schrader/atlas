# api/ — Atlas FastAPI service

A thin HTTP service over the Python `paper_radar` logic (ingest, metadata,
later embeddings/ranking). The React app calls Supabase directly for CRUD; it
calls this service for the Python-only work. See `../docs/MIGRATION_PLAN.md` §2.

## Run

```bash
# from paper-radar/
cp api/.env.example api/.env      # fill in SUPABASE_URL / ANON / SERVICE_ROLE keys
uv sync --extra api
uv run uvicorn api.app:app --reload      # http://127.0.0.1:8000  (docs at /docs)
```

The **service-role key is server-side only** — it bypasses RLS. Never put it in
`web/`.

## Endpoints (phase 4)

- `GET  /health` → `{"status": "ok"}`
- `POST /resolve` `{ "url": "..." }`, `Authorization: Bearer <jwt>` → resolved
  metadata (title, authors, abstract, DOI, venue, year, keywords, source) +
  `url_norm`, the dedup key. Reuses `ingest/metadata.py` and `ingest/pdf_extract.py`.
  Makes the server fetch the URL, so it's authenticated, rate-limited, and
  SSRF-guarded (`ingest/url_guard.py`); a non-public target is a `400`.
- `POST /posts` `{ "url", "team_id", "note?" }`, `Authorization: Bearer <jwt>` →
  verifies the caller's Supabase token, upserts the global `papers` row
  (service role, dedup on DOI/`url_norm`), and inserts the `paper_post` **as the
  user** so RLS enforces lab membership. Returns `{ post_id, paper_id,
  already_posted, paper }`. Schedules a background embed of the paper.

## Embeddings (phase 6 — see `../docs/EMBEDDINGS_PLAN.md`)

Vectors come from Voyage AI (`voyage-4`, 1024-dim; set `VOYAGE_API_KEY`) and
live in `papers.embedding` (pgvector). New posts embed in the background;
backfill everything older with:

```bash
uv run python -m api.backfill_embeddings          # papers missing embedded_at
uv run python -m api.backfill_embeddings --all    # re-embed (model change)
```

- `POST /search/semantic` `{ "query", "team_id", "limit?" }`, Bearer JWT →
  embeds the query and ranks the lab's posts by cosine similarity via the
  `match_papers` RPC **as the user** (RLS scopes results). Returns
  `{ results: [{ similarity, post }] }`.
- `GET /overview?team_id=...`, Bearer JWT → 2-D t-SNE layout of the lab's
  embedded papers: `{ points: [{ paper_id, x, y, title, venue, year, tags }],
  total, embedded }`. Layouts are cached per team until the embedded set
  changes.
- "Find similar" needs no server round-trip through this service — the web app
  calls the `similar_papers` RPC directly on Supabase.

## Teams integration (see `../../docs/teams-integration-plan.md`)

Outbound mirror: connected labs get an Adaptive Card in their Teams channel
whenever a paper is posted from the web app.

Lab owners connect it themselves in **Settings → Post to Teams**: create a flow
in Teams from the **"Send webhook alerts to a channel"** template (trigger:
"When a Teams webhook request is received"), pick the channel, and paste the
generated webhook URL. The row lives in `team_integrations` (owner-only RLS);
`TEAMS_WEBHOOK_URLS={"<team uuid>": "<url>"}` in the env remains as an
operator-level fallback for unmapped teams.

Security: the webhook URL is a URL the *server* POSTs to, i.e. an SSRF sink.
It is validated on save and re-validated on send (`url_guard` screen + https +
default port + no credentials + `*.logic.azure.com` / `*.api.powerplatform.com`
allowlist), a DB CHECK enforces the same shape against direct writes, and the
POST never follows redirects.

Posting is fire-and-forget from `create_post` background tasks — an unreachable
webhook is logged and never fails the in-app post.

Next: enrichment (summary/tags) and a real worker.
