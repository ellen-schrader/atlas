# Atlas

**Every lab has a taste. Atlas gives yours to Claude.**

The papers you save, the figures you admire, the ones you argue about — Atlas learns your lab's judgment from how you already work, then hands it to Claude Code and Claude for Life Sciences.

---

## The problem: taste gets lost twice

**Attrition.** A lab's judgment about what's worth reading lives in one postdoc's head. Five years of it walks out the door when she graduates. The next person inherits the Dropbox, not the mind.

**Averaging.** The standing critique of AI in science is that it homogenises it. Every lab asks the same model the same question, gets the same consensus answer, and plots it in the same default palette. The thing that actually drives science — a specific group's specific judgment about what matters — gets averaged away.

**Atlas is the bet against both.** It doesn't try to make Claude smarter. It makes Claude *yours* — grounded in what *this* lab reads, argues about, and admires.

| | The generic version | The Atlas version |
|---|---|---|
| **Recommendations** | what the field cites | what **this lab** judged worth its time |
| **"What's new" in a topic** | the consensus summary | **this lab's** view of what's moving |
| **Related work** | plausible citations, some invented | **this lab's** actual papers, links that resolve |
| **Figures** | the default palette | **this lab's** look |

These aren't four features. They're four instances of one move.

---

## What it does

Atlas has three surfaces.

### 1. Papers — the lab's corpus, with judgment attached

A deduped, enriched, shared corpus: full-text **and** semantic search, an interactive t-SNE map of the lab's reading by meaning, LLM-named clusters, reactions, comments, reading lists.

**Topic maps** are the part that matters. *A map is not a saved filter — it's a topic the lab watches, and Atlas keeps it current.* Each topic map scopes the corpus to a semantic seed ("ovarian cancer, HGSOC, platinum resistance"), clusters it into named sub-themes, ranks the labs driving it, and generates a **"What's new" summary in which every claim is grounded in a paper the lab actually posted** — with source chips that resolve to the paper.

### 2. Your lab's look — the figures, as an asset

A mood board of figures the lab admires. Atlas derives the lab's **palette** from them and emits a **real matplotlib style sheet**, so plots come out in the lab's colours rather than the field's default. It also holds **style cards**: synthetic figures rendered from a style spec, which capture *how a figure looks* without ever copying the figure itself.

### 3. Connect Claude — the corpus and the taste, over MCP

One config file, and Claude Code / Claude Desktop can read the lab. See below.

---

## How "taste" is actually computed

The claim "we learn your lab's taste" is cheap, so here is the mechanism, in full.

Atlas weights the lab's **existing behaviour** — there's no profile to fill in and no tuning:

| Signal | Weight |
|---|---|
| Save / bookmark | 1.5× |
| React | 1.0× |
| Comment | 0.75× |
| 🤔 (thinking-face) | 0.3× |
| Merely read | 0.25× |

**Not all engagement is endorsement** — an argument is not an endorsement, and a 🤔 is closer to a doubt than a vote. Signals **half-life every quarter**, so the model tracks where the lab is *going*, not where it's been.

Figures teach the **palette**, not the taste — the two are learned from different evidence and kept separate on purpose.

**Cold start:** a new lab or a new member has no history to learn from, so the free-text *research profile* in Settings seeds the model on day one and behavioural signal takes over as it accumulates. It's per-user, so recommendations get personal without fragmenting the lab's shared taste.

> **Honesty note.** Those weights are a hand-chosen prior, not a fitted model. See [Roadmap](#roadmap).

---

## Claude over MCP

`atlas_mcp/` is a local stdio MCP server exposing **18 tools**:

**Find & cite** — `search_lab_papers` (keyword | semantic), `list_recent_papers`, `get_paper`, `similar_papers`, `list_labs`
**Decide what to read** — `recommend_reading`, `lab_digest`
**Write & get unstuck** — `novelty_check` (*is this idea new **to us**?*), `draft_related_work` (sourced **only** from the lab's own papers), `post_paper` ⚠️
**Plot in the lab's style** — `get_moodboard_style` (palette + matplotlib style sheet), `list_moodboard`, `moodboard_categories`, `get_figure_image`, `get_figure_palette`, `check_colorblind_safety`, `preview_plot_spec`, `add_plot_to_moodboard` ⚠️

The two ⚠️ tools write to the shared lab. Everything else is read-only.

### The security model

This is a tool-using model reading third-party text on behalf of a whole lab, so the boundaries are explicit:

- **Owner-gated.** Claude access is a **lab-wide** setting an *owner* must switch on. Until then every tool call is refused — it isn't one member's call to make, because the server can read the lab's papers and post into it.
- **Read-only by default.** The only two writes (`post_paper`, `add_plot_to_moodboard`) preview by default and require explicit confirmation.
- **Scoped to you.** Your own login scopes access. Claude sees exactly what you see, nothing more.
- **Audited.** Every tool call is logged to an activity log the lab can read.
- **Prompt-injection hardened.** All paper text, abstracts and figure captions are wrapped and labelled as *untrusted data*, so an abstract cannot instruct the agent.
- **Credentials never leave the server.** Lab credentials live in `api/.env` (gitignored), never in a Claude config. `list_labs` deliberately omits the lab join code.

### Connecting

The in-app **Connect Claude** page generates the config and walks the four steps. In short: an owner enables Claude access → copy the generated MCP block into `.mcp.json` (Claude Code) or `claude_desktop_config.json` (Desktop) → put `ATLAS_EMAIL` / `ATLAS_PASSWORD` (or `ATLAS_TOKEN`), `ATLAS_TEAM_ID` and `ATLAS_WEB_URL` in `api/.env` → restart Claude and run `/mcp`.

Then ask it things like:

> *"What has our lab posted on immunosuppressive myeloid cells?"*
> *"Is this novel for us — TREM2+ TAMs drive anti-PD1 resistance?"*
> *"Draft the related-work paragraph, citing only our papers."*
> *"Plot these phenotypes as a forest plot in our lab's style."*

---

## Architecture

```
web/          Vite + React + TypeScript          → localhost:5173
              Landing · Dashboard · Papers · ReadingList · MoodBoard
              MapsLibrary · Map · MapDashboard · Connect · Settings
                    │  REST
                    ▼
api/          FastAPI (uvicorn)                  → localhost:8010
              app.py · maps.py · overview.py · map_summary.py
              embeddings.py (Voyage) · enrichment.py (Claude)
                    │
                    ▼
supabase/     Postgres + Auth + Storage (RLS)    → localhost:54321
                    ▲
                    │  same DB, same auth, user-scoped
atlas_mcp/    stdio MCP server (18 tools)  ──────┘
              server.py · lab.py · moodboard.py
              spec.py / composite.py / render.py  (style-card renderer)
```

**Embeddings** are Voyage; **enrichment, cluster names and topic summaries** are Claude. The 2-D map is a t-SNE computed API-side.

<details>
<summary><b>Prototype history</b> — <code>paper_radar/</code> and <code>app/</code></summary>

Atlas began as `paper-radar 📡`: a Typer CLI + Streamlit app that ingested PDFs exported from the lab's Teams channel into SQLite, with local sentence-transformer embeddings and a FAISS index. That code still lives in `paper_radar/` and `app/` behind the `legacy` extra and is **not** installed in the API container. The Teams-PDF importer survives as `api/import_teams_pdfs.py`. Everything else — Postgres, Voyage, the React app, the MCP server — replaced it.

</details>

---

## Quickstart (local)

Three processes. Docker required (Supabase).

```bash
cd paper-radar

# 1. Database
supabase start                    # Postgres 54322 · API 54321 · Studio 54323

# 2. Secrets — see .env.example
#    api/.env         ANTHROPIC_API_KEY, VOYAGE_API_KEY, SUPABASE keys,
#                     ATLAS_EMAIL / ATLAS_PASSWORD / ATLAS_TEAM_ID / ATLAS_WEB_URL
#    web/.env.local   VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_URL

# 3. API  — note :8010, not :8000
uv run --extra api uvicorn api.app:app --reload --port 8010

# 4. Web
cd web && npm install && npm run dev     # http://localhost:5173

# 5. MCP server (Claude connects to this over stdio)
uv run --extra mcp python -m atlas_mcp
```

**Demo data.** `.claude/skills/run-atlas/` seeds a lab ("TME Lab") with papers, posts and reactions, and creates a signed-in user.

> ⚠️ **The seed has no embeddings.** Without a `VOYAGE_API_KEY` and an embedding backfill, semantic search is off, the map is empty, and recommendations return `cold_start`. Backfill with `api/backfill_embeddings.py` before demoing Maps.

```bash
uv run pytest
uv run ruff check
```

---

## Roadmap

Atlas is already accumulating something rare: **a labelled preference dataset, produced as a by-product of a lab working normally.** Every save, react, comment, 🤔 and read is a graded human judgment about whether a paper was worth the lab's time. That's the expensive part of any preference model, and here it's free.

1. **Learn the weights** instead of hand-setting them. The table above is a prior; different labs will differ (a 🤔 in a rigorous methods lab may outrank a 👍 elsewhere).
2. **Close the RL loop.** Recommendations are shown, acted on, or ignored — and that outcome is itself signal. Recommend → observe → update.
3. **Discovery, not just ranking.** Today Atlas ranks papers the lab already posted. The end state is going *out* into the literature for papers nobody in the lab has seen, because it has a model of what this lab would want. From "our library, searchable" to "a scout who knows our taste."

**Status: we are collecting the data. We have not trained on it yet.**

### Isn't a lab-specific model just an echo chamber?

It's the fair objection to the whole premise, and it's designed against in three places. `novelty_check` exists to tell you when your lab has **already** covered something — a redundancy alarm is the opposite of an echo. Signals half-life quarterly, so the model follows where the lab is *going*. And the discovery step (3) points **outward**, at papers nobody in the lab has seen.

Homogenisation across the field and an echo chamber inside one lab are both failure modes. We'd rather have a thousand labs with a thousand tastes than a thousand labs with one.

---

## Privacy & third-party data

Paper **metadata and abstracts** are sent to third parties for processing: **Voyage AI** (embeddings) and **Anthropic / Claude** (summaries, tags, cluster names, topic digests), plus public metadata APIs (arXiv, Crossref, PubMed, Europe PMC) when resolving a paper. Mood-board images are stored in Supabase Storage and are **not** sent to third parties except when *you* ask Claude to look at one (`get_figure_image`).

Don't paste confidential or unpublished text you don't want leaving your infrastructure. User identities and email addresses are **not** sent to these services.

---

*Atlas — a lab's reading, mapped.*
