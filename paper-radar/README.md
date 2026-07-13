# paper-radar 📡

Paper discovery + recommendation for a PhD lab studying the **spatial architecture of the breast tumor microenvironment** — turning a firehose of papers shared in a Microsoft Teams channel into a searchable, ranked, mappable radar.

## What it does

Papers arrive as PDFs exported from the lab's Teams channel. paper-radar:

1. **Ingests** — pulls the (untruncated) URLs out of those PDFs, records who shared each one, and resolves bibliographic metadata (title, authors, venue, year, DOI, **abstract**, keywords) from arXiv / Crossref / PubMed / Europe PMC / publisher citation tags.
2. **Enriches** — uses Claude (grounded on the resolved abstract) to write a short summary, assign domain tags, and find linked code/data repos. *(stub — you implement)*
3. **Embeds** — computes local sentence-transformer embeddings and builds a FAISS index for semantic search (the hosted app's 2-D map is a t-SNE layout computed API-side).
4. **Ranks** — a "taste model" scores papers by how interesting they are to the lab. *(stub — you implement)*
5. **Serves** — a Streamlit app (behind email/password sign-in) to search, filter, browse, comment on, and react to papers.

## Privacy & third-party data

Paper **metadata and abstracts** are sent to third parties for processing: Voyage
AI (embeddings) and Anthropic / Claude (summaries, tags, cluster names, map
digests), plus public metadata APIs (arXiv, Crossref, PubMed, Europe PMC) when
resolving a paper. Don't paste confidential or unpublished text you don't want
leaving your infrastructure. User identities and email addresses are **not** sent
to these services.

## Accounts & teams

The app requires signing in. Each user belongs to a **team**; signing up with a
new team name creates the team, and signing up with an existing name joins it.
The **papers database is shared across all teams**, but **comments and
reactions are team-scoped** — you only see the ones written by members of your
own team. Passwords are hashed with PBKDF2-SHA256 (stdlib only). See
`paper_radar/auth.py` (accounts/teams) and `paper_radar/social.py`
(comments/reactions).

## Architecture

```
PDFs (Teams export)
      │  ingest/pdf_extract.py   (PyMuPDF: link annotations + regex fallback)
      │  ingest/metadata.py      (arXiv, Nature→DOI, PubMed, Crossref, citation tags)
      ▼
   SQLite  ◀── models.py (Paper, Label, User, Team, Comment, Reaction)  ── db.py
      │        auth.py (signup/login + teams) · social.py (comments/reactions)
      │
      ├─ enrich/agent.py   Claude → PaperEnrichment            [STUB]
      ├─ embed/embed.py    sentence-transformers (bge-small)
      │  embed/index.py    FAISS (cosine) + t-SNE 2-D
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
uv sync --extra dev --extra legacy   # `legacy` = Streamlit app + local embeddings

# 2. Configure secrets
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=...   (only needed for the enrich stage)

# 3. Run the app — works immediately on the bundled fixture papers
uv run streamlit run app/streamlit_app.py

# --- full pipeline on real data ---
uv run paper-radar ingest /path/to/teams_pdfs   # extract URLs + metadata → SQLite
uv run paper-radar enrich                        # Claude summaries + tags (stub)
uv run paper-radar embed                         # embeddings + FAISS index
uv run paper-radar serve                         # launch Streamlit

# checks
uv run pytest
uv run ruff check
```

If `uv` is not available, fall back to a plain venv:

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,legacy]"
# Note: pip skips the [tool.uv] constraints in pyproject.toml; on linux/aarch64
# also `pip install "cryptography<47"` (newer wheels SIGILL under Docker Desktop).
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
