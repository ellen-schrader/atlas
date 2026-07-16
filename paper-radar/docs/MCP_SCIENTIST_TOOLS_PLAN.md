# MCP scientist tools — implementation plan

Six new tools for `atlas_mcp`, in the order requested. `export_bibtex` is deferred.
All are **read-only** except where noted; each acts as the signed-in user, so RLS
scopes everything to their lab (same model as the existing 9 tools). Every tool
catches `lab.LabError`, returns human-readable text (never raises into JSON-RPC),
and wraps user-authored free-text with `_untrusted(...)`.

## Cross-cutting constraints

- **No numpy.** The `mcp` extra ships only `mcp`, `supabase`, `pillow`. Any vector
  math (centroids, cosine) is pure Python over `list[float]`. We do **not** reuse
  the API's numpy `_taste_vector`; we recompute a light centroid in `lab.py`.
- **Reuse, don't fork.** Search → `lab.search(mode=…)`; nearest-neighbour →
  `match_papers` / `recommend_papers` RPCs; embeddings → `api.embeddings`.
- **No new migrations.** Every tool runs against RPCs/tables that already exist.
- Heavy results set `_meta["anthropic/maxResultSizeChars"]` where they can be long.

---

## 1. `check_colorblind_safety(figure_id? , palette?, team_id?)` — read-only

**Purpose.** Tell a scientist whether a figure's (or an explicit palette's) colours
survive colour-vision deficiency (CVD), and if not, which pairs collide and what to
swap in. Extends the palette code just shipped.

- **Input.** Either a `figure_id` (extract via `moodboard.palette`) or an explicit
  `palette` (list/CSV of hexes). One is required.
- **Method (pure Python, in `moodboard.py`).** Simulate deuteranopia, protanopia,
  tritanopia with the Machado/Brettel-style linear-RGB transform (a fixed 3×3 per
  type — no numpy, just dot products). For every colour pair compute CIE76 ΔE in Lab
  after simulation; flag pairs with ΔE < ~11 as "hard to tell apart" under that CVD.
- **Output.** Per-CVD verdict (safe / N risky pairs), the specific colliding hex
  pairs, and — when unsafe — the nearest CVD-safe Paul Tol substitutes.
- **Tests.** A known-bad pair (red/green matplotlib defaults) flags under deut/prot;
  a Paul Tol bright subset passes all three; explicit-palette and figure_id paths.

## 2. `recommend_reading(limit=8, team_id?)` — read-only

**Purpose.** "What should I read next?" — the dashboard recommender, over MCP.

- **Taste vector without numpy.** New `lab.taste_vector(team)`: fetch embeddings of
  the papers the user has engaged (status `read`/`reading` + reacted), element-wise
  average in pure Python, return `list[float]` (or `None` when cold). Fetch is
  RLS-scoped; embeddings already stored on `papers.embedding`.
- **Ranking.** Pass the centroid to the existing `recommend_papers` RPC (already
  excludes self-posted / already-engaged and applies the freshness re-rank).
- **Cold start.** No taste signal → fall back to `lab.recent(team)` and say so.
- **Output.** Ranked citation blocks (title, authors, venue/year, DOI, `?paper=`
  deep link) + one-line "why" (similarity / recency).
- **Tests.** `taste_vector` averages correctly and returns `None` when no engagement;
  cold-start path returns recents with the cold flag.

## 3. `lab_digest(days=7, team_id?)` — read-only

**Purpose.** A standup-style summary of recent lab activity.

- **Method.** RLS-scoped counts/lists over a `now()-days` window: new `paper_posts`
  (with posters), new `comments`, new `mentions` of *me*, most-reacted papers. Reuse
  `lab.recent` + direct `.gte("created_at", cutoff)` selects.
- **Output.** Sectioned text — "N new papers", top posters, "papers you were tagged
  in", trending — every title/comment wrapped with `_untrusted`.
- **Tests.** Window filter (a paper outside the window is excluded); mention section
  only surfaces the caller's mentions.

## 4. `similar_papers(paper_id, limit=8, team_id?)` — read-only

**Purpose.** "More like this" from a specific paper.

- **Method.** Read the anchor paper's stored `embedding` (no re-embed needed); pass
  it straight to `match_papers`; drop the anchor itself from the results.
- **Fallback.** Anchor has no embedding → keyword `search` on its title, noted.
- **Output.** Ranked citation blocks + similarity.
- **Tests.** Anchor excluded from its own results; no-embedding fallback path.

## 5. `novelty_check(text|paper_id, team_id?)` — read-only

**Purpose.** "Has our lab already covered this?" — the inverse framing of similar.

- **Method.** Embed the supplied idea/abstract (`embeddings.embed_query`) — or reuse
  a paper's stored embedding — then `match_papers`. Bucket by similarity: high
  (≳0.75) "closely related / likely not novel here", mid "adjacent", else "novel to
  this lab". Corpus scope is the lab (RLS); state that explicitly.
- **Output.** A novelty verdict + the closest existing papers as evidence.
- **Tests.** High-similarity input buckets as "closely related"; empty corpus →
  "nothing to compare against".

## 6. `draft_related_work(topic|paper_id, limit=8, team_id?)` — read-only

**Purpose.** Draft a cited "Related Work" paragraph from the lab's own papers.

- **Method.** Compose existing tools: semantic `search` (or `similar_papers`) to
  gather the top relevant lab papers, then emit a **grounded prose scaffold** that
  cites each as `[Author, Year]` with the `?paper=` link and a one-line contribution
  note drawn from each abstract. The tool assembles *sourced material with citations*
  and instructs the model to synthesise prose only from it — never invent references.
- **Output.** A related-work draft + a numbered source list (title, authors, venue,
  DOI, deep link), all abstract text `_untrusted`-wrapped.
- **Tests.** Every citation in the draft maps to a real gathered paper; empty result
  → "no lab papers matched, nothing to cite".

---

## Files

- `atlas_mcp/moodboard.py` — CVD simulation + ΔE helpers (tool 1).
- `atlas_mcp/lab.py` — `taste_vector`, `paper_embedding`, digest queries, `similar_by_embedding`.
- `atlas_mcp/server.py` — the 6 `@mcp.tool()` entry points.
- `paper-radar/tests/test_atlas_mcp.py` — offline unit tests per tool (pure helpers).
- `docs/CLAUDE_INTEGRATION_PLAN.md` — list the new tools under the tool surface.

## Verification

- Unit (pytest, offline): pure helpers per tool as above; keep the suite green.
- Integration (local stack): drive each tool over stdio against the seeded lab —
  spot-check citations resolve, RLS refuses a foreign `team_id`, cold-start paths.
- Ship in small commits (one tool or a tight pair per commit) for reviewable diffs.
