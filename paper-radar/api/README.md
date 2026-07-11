# api/ — Atlas FastAPI service

A thin HTTP service over the Python `paper_radar` logic (ingest, metadata,
later embeddings/ranking). The React app calls Supabase directly for CRUD; it
calls this service for the Python-only work. See `../docs/MIGRATION_PLAN.md` §2.

## Run

```bash
# from paper-radar/
uv sync --extra api
uv run uvicorn api.app:app --reload      # http://127.0.0.1:8000  (docs at /docs)
```

## Endpoints (phase 4, first slice)

- `GET  /health` → `{"status": "ok"}`
- `POST /resolve` `{ "url": "..." }` → resolved metadata (title, authors,
  abstract, DOI, venue, year, keywords, source) + `url_norm`, the dedup key.
  Reuses `ingest/metadata.py` and `ingest/pdf_extract.py` unchanged.

Next: persist into Supabase (upsert `papers`, create `paper_post`) using the
service-role key, and run enrichment/embedding in a worker.
