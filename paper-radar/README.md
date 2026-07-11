# paper-radar 📡

Paper discovery + recommendation for a PhD lab studying the **spatial architecture of the breast tumor microenvironment** — turning a firehose of papers shared in a Microsoft Teams channel into a searchable, ranked, mappable radar.

## What it does

Papers arrive as PDFs exported from the lab's Teams channel. paper-radar:

1. **Ingests** — pulls the (untruncated) URLs out of those PDFs and records who shared each one.
2. **Enriches** — uses Claude to write a short summary, assign domain tags, and find linked code/data repos. *(stub — you implement)*
3. **Embeds** — computes local sentence-transformer embeddings, builds a FAISS index for semantic search, and a UMAP 2-D map of the collection.
4. **Ranks** — a "taste model" scores papers by how interesting they are to the lab. *(stub — you implement)*
5. **Serves** — a Streamlit app to search, filter, and browse.

## Architecture

```
PDFs (Teams export)
      │  ingest/pdf_extract.py   (PyMuPDF: link annotations + regex fallback)
      │  ingest/metadata.py      (arXiv, Nature→DOI, PubMed, Crossref, citation tags)
      ▼
   SQLite  ◀── models.py (SQLModel: Paper, Label, User)  ── db.py
      │
      ├─ enrich/agent.py   Claude → PaperEnrichment            [STUB]
      ├─ embed/embed.py    sentence-transformers (bge-small)
      │  embed/index.py    FAISS (cosine) + UMAP 2-D
      └─ taste/score.py    in-context + pairwise ranking       [STUB]
         taste/eval.py     rank-correlation vs held-out labels [STUB]
      ▼
  app/streamlit_app.py     search + tag filter over the store
```

Everything is wired together by the `paper-radar` Typer CLI (`ingest`, `enrich`, `embed`, `serve`).

## Quickstart

```bash
# 1. Install (uv creates the venv and resolves everything)
cd paper-radar
uv sync --extra dev

# 2. Configure secrets
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=...   (only needed for the enrich stage)

# 3. Run the app — works immediately on the bundled fixture papers
uv run streamlit run app/streamlit_app.py

# --- full pipeline on real data ---
uv run paper-radar ingest /path/to/teams_pdfs   # extract URLs + metadata → SQLite
uv run paper-radar enrich                        # Claude summaries + tags (stub)
uv run paper-radar embed                         # embeddings + FAISS + UMAP
uv run paper-radar serve                         # launch Streamlit

# checks
uv run pytest
uv run ruff check
```

If `uv` is not available, fall back to a plain venv:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Project layout

```
paper_radar/
  config.py            pydantic-settings (ANTHROPIC_API_KEY, model + path config)
  models.py            SQLModel tables + PaperEnrichment (LLM output schema)
  db.py                engine, init_db(), get_session()
  store.py             list_papers() / fixtures fallback used by the app
  cli.py               typer app: ingest | enrich | embed | serve
  ingest/              pdf_extract.py (implemented), metadata.py (implemented)
  enrich/agent.py      STUB — Claude enrichment
  embed/               embed.py, index.py (implemented)
  taste/               score.py, eval.py (STUBS)
app/streamlit_app.py   the UI shell
data/fixtures/         seed papers so the app runs with no real data
tests/                 pdf extraction + db smoke tests
```

## Learning notes

_(Running log of what worked, what didn't, and why — fill in as the hackathon goes.)_
