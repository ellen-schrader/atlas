# Map → Insights overview: implementation plan

Turn the `/map` route from a bare UMAP scatter into an **insights page**: the
interactive map (with color/size/filter controls and LLM-named clusters)
alongside stats-and-trends plots. Branch: `improve-map-overview`.

Status: **building**. Decisions (§4): (1a) last/corresponding author as the lab
proxy; (2) implement enrichment + backfill tags; (3) dependency-free inline SVG
charts; (4) MVP first (clusters, color/size/semantic-filter, core stats), then
labs + enrichment-tags as follow-ups.

---

## 1. What the data supports today

Measured on the live Ali-Lab corpus (425 papers, 395 embedded):

| Signal | Coverage | Usable for |
|---|---|---|
| `embedding` | 395/425 | UMAP, clustering, semantic filter |
| `venue` | 381/425 | color-by, top-venues stat |
| `year` | 389/425 | color-by, year-distribution stat |
| `posted_at` | 425/425 (filename-window dates) | posts-over-time stat |
| reactions / comments | present, ~0 on imports | size-by-engagement (flat until it accrues) |
| `keywords` (metadata) | 106/425 | weak color-by/facet |
| `tags` (LLM) | **0/425** — enrich stub never run | nothing yet |
| author **affiliation / lab** | **not extracted** — authors are names only | nothing yet |

Two ideas are blocked on missing data and need a decision (§4): **color-by-tags**
(no tags) and **filter/rank by lab** (no affiliations).

---

## 2. Architecture

Extend the Python API (it already computes UMAP server-side and holds the
Voyage + Anthropic keys); the React page gets controls + charts.

### Server — replace `/map` with `/overview?team_id=` (JWT, RLS-scoped)

Returns, in one call:

```jsonc
{
  "points": [{ "paper_id", "x", "y", "year", "venue", "keywords",
               "reactions", "comments", "cluster": 3 }],
  "clusters": [{ "id": 3, "label": "Spatial TME profiling",
                 "description": "...", "size": 41 }],
  "stats": {
    "over_time":  [{ "month": "2026-03", "count": 22 }],
    "by_venue":   [{ "venue": "bioRxiv", "count": 58 }],
    "by_year":    [{ "year": 2025, "count": 71 }],
    "totals":     { "papers": 425, "embedded": 395 }
  },
  "embedded": 395, "total": 425
}
```

- **UMAP** as today (cached per team by embedded set).
- **Clusters** — KMeans over the embeddings (k auto ≈ `clamp(round(n/25), 4, 12)`;
  deterministic seed). Cheap, stable, and enough for a themed map.
- **LLM names** — for each cluster, send its papers' **titles** (delimited,
  untrusted *data*, no tools) to Claude → `{label ≤ 4 words, description}`.
  **Cached in the existing `trends` table** keyed by a hash of
  `(cluster member set)` so we only pay Claude when the clustering changes.
  Prompt-injection note (plan §14): titles/abstracts are untrusted; they go in
  a clearly-delimited data block, never as instructions, no tool access.
- **Stats** computed in SQL/Python over the lab's posts.
- **Semantic filter** reuses the existing `/search/semantic` + `match_papers`
  (returns `paper_id`+similarity); the map highlights/dims by that set — no new
  server work.

### Client — the `/map` page (rename nav to "Overview"?)

- **Interactive UMAP** (evolve the current SVG scatter):
  - **Color-by** selector: `cluster` (default) · `year` · `venue`. Sequential
    ramp for year; categorical (validated palette) for cluster/venue, folding a
    long venue tail into "Other".
  - **Size-by** selector: `uniform` (default) · `engagement` (reactions+comments).
  - **Semantic filter**: a query box → non-matching points dim, matches keep
    color; shows "N match".
  - **Cluster legend** with the LLM names; hovering/clicking a cluster
    highlights its points. Hover tooltip + click-to-open unchanged.
- **Stats & trends panels** below the map (dataviz skill for palette/marks):
  - **Posts over time** (area/line by month).
  - **Top venues** (horizontal bar).
  - **Papers by year** (bar).
  - **Themes** (the clusters, as a labeled bar/list with sizes).
- Layout: map on top (full width), a responsive grid of stat cards beneath.

---

## 3. Feature-by-feature

| # | Idea | Plan | Data |
|---|---|---|---|
| 1 | Color dots by variable | color-by `cluster`/`year`/`venue` now; `tags`/`keywords` once populated | ⚠ tags empty |
| 2 | Filter by semantic search | query → highlight/dim via `match_papers` | ✓ |
| 3 | Themes/clusters, LLM-named | KMeans + Claude labels, cached in `trends` | ✓ |
| 4 | Size dots by engagement | size-by reactions+comments | ✓ (flat until engagement grows) |
| 5 | Filter by labs | **needs affiliations — see §4** | ✗ |
| 6 | Other stats/trend plots | over-time, by-venue, by-year, themes | ✓ |
| 7 | Most common labs we post from | **needs affiliations — see §4** | ✗ |
| 8 | One page: UMAP + stats | the layout above | ✓ |

---

## 4. Open questions (decide before building)

1. **"Labs" (#5, #7).** We store author *names* only — no institution/lab. To
   do "filter by lab" / "top labs we post from" we'd need to derive a lab/group
   per paper. Options, in effort order:
   - **(a) Last/corresponding author** as a proxy for "the lab" — free, already
     have names, but noisy (people move labs; name collisions).
   - **(b) Extract affiliations** — Crossref exposes author affiliations for
     ~some DOIs; fill gaps with an LLM read of the abstract/first page. A real
     ingest addition (new column, backfill), but the only way to get true labs.
   - **(c) Defer** these two ideas to a follow-up.
   Which do you want?
2. **Tags (#1).** LLM tags are empty because the enrichment agent
   (`enrich/agent.py`) was never implemented. Do you want me to **implement
   enrichment** (Claude → summary + tags, backfill 425 papers) so color-by-tags
   works — or rely on **clusters** as the "theme" grouping for now (my
   recommendation; clusters are richer than tags for a map)?
3. **Chart approach.** Keep it **dependency-free inline SVG** (matches the
   redesign's scatter, per the dataviz method) rather than adding a chart lib?
4. **Scope / first cut.** Proposed MVP: color-by (cluster/year/venue) +
   size-by-engagement + semantic filter + LLM-named clusters + the three core
   stat plots. Follow-ups: affiliations/labs (#5,#7) and enrichment tags.
   Good, or reprioritize?

---

## 5. Rough steps (after §4)

1. `/overview` endpoint: UMAP + KMeans + stats (no LLM yet) → wire the page.
2. Cluster naming via Claude, cached in `trends`.
3. Page controls: color-by, size-by, semantic filter, cluster legend.
4. Stat panels (over-time, venues, years, themes).
5. (If chosen) affiliations extraction + labs facet; enrichment + tags.
6. Tests (endpoint shape, clustering determinism, cache keying) + verify.
