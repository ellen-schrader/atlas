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
- `POST /resolve` `{ "url": "..." }` → resolved metadata (title, authors,
  abstract, DOI, venue, year, keywords, source) + `url_norm`, the dedup key.
  Reuses `ingest/metadata.py` and `ingest/pdf_extract.py` unchanged.
- `POST /posts` `{ "url", "team_id", "note?" }`, `Authorization: Bearer <jwt>` →
  verifies the caller's Supabase token, upserts the global `papers` row
  (service role, dedup on DOI/`url_norm`), and inserts the `paper_post` **as the
  user** so RLS enforces lab membership. Returns `{ post_id, paper_id,
  already_posted, paper }`.

Next: enrichment (summary/tags) and embedding in a worker.
