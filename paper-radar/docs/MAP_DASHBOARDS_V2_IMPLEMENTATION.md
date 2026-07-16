# Maps v2 — implementation plan

Sequenced build for the [maps-as-topic-dashboards proposal](MAP_DASHBOARDS_V2_PROPOSAL.md).
Five milestones, each shippable on its own and de-risking the next. The AI summary — the
highest-cost, highest-trust-risk piece — lands **last**, on top of real data.

## Decisions baked in

- **Membership** = semantic seed + **pin** as the only v1 curation primitive (guards the
  asymmetric downside: a missing seminal paper reads as broken; a few false positives don't).
  Exclude / tag-lab rules are a fast-follow; a per-row *dismiss* ships in v1 as the escape valve
  and the signal for what curation to build next.
- **Sharing** = **lab-shared by default**, owner edits the definition; **read-state stays
  per-person** (so "unread" is unread *for me*); a per-map `visibility` flag allows the rare
  private scratch map.
- **Layout** = scatter-hero + summary side-by-side on desktop; **stack summary-first on mobile**;
  a one-line freshness note in the identity header answers "did anything happen?" instantly.

---

## Milestone 0 — Data foundation

The schema + membership query everything else stands on. No UI.

**Migration** `supabase/migrations/<ts>_maps.sql`:

```sql
create table public.maps (
  id            uuid primary key default gen_random_uuid(),
  team_id       uuid not null references public.teams(id) on delete cascade,
  created_by    uuid not null references public.profiles(id),
  name          text not null,
  seed          text not null,                       -- the phrase the user typed
  seed_embedding extensions.vector(1024),            -- embedded server-side on create/update
  config        jsonb not null default '{}',         -- { topN|threshold, pinned:[uuid], excluded:[uuid] }
  visibility    text not null default 'lab' check (visibility in ('lab','private')),
  ai_summary    jsonb,                               -- { text, cited_ids, generated_at, n_papers }
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index maps_team_idx on public.maps(team_id);
```

**RLS** (`<ts>_maps_rls.sql`): team members `select` where `visibility='lab' OR created_by=auth.uid()`;
`insert/update/delete` only by `created_by` (owner). Mirrors the `mcp_access` / `paper_posts`
policy style already in the repo.

**Membership RPC** `map_members(p_map uuid, p_limit int)` — returns `post_id, paper_id, similarity`
ranked by cosine to the map's `seed_embedding`, **unioned with `config.pinned`**, **minus
`config.excluded`**, team-scoped, over papers with an embedding. This is `match_papers` with the
query vector read from the row instead of passed in, plus the pin/exclude set-ops.

**Seed embedding** is computed in the API (Voyage key is server-side only), so map create/update
flows through the API, never the browser.

*Ships:* nothing visible, but membership is queryable end-to-end (verify via psql + a pgTAP RLS
test that a non-member and another lab can't read a `lab` map).

## Milestone 1 — Maps CRUD, library, and create flow

Maps become real objects a user can make, name, and open (dashboard still a stub).

**API** (`api/app.py`, new `api/maps.py`):
- `POST /maps` `{name, seed}` → embed seed (`embeddings.embed_query`), insert, return the map.
- `GET /maps?team_id=` → the team's maps (RLS-scoped) + the pinned Overview pseudo-entry.
- `PATCH /maps/{id}` → rename, edit seed (re-embed), pin/exclude a paper, set visibility.
- `DELETE /maps/{id}` (owner).

**Web** (`web/src/routes/`, `lib/api.ts`, a `useMaps` hook):
- Nav **Map → Maps**; `/maps` library: pinned **Overview** card + map cards (name · mini-scatter
  thumbnail · `N papers` · `+N new` · summary snippet) + **New map**.
- `/maps/new` create: one inline input ("What's this map about?") → POST → route to `/maps/:id`.
- **"Save as map"** promotion on the Overview topic lens (seeds `name`/`seed` from the current
  query) — the cheap, high-intent entry point.

*Ships:* a working maps library and creation. Reuses `lib/api.ts` fetch + the paper-modal route
pattern for `/maps/new`.

## Milestone 2 — The scoped scatter (dashboard hero)

The differentiated, validated thing: a t-SNE of *this topic's* papers.

**API**: `GET /maps/{id}/overview` — the existing `/overview` layout + clustering (`api/overview.py`)
run on the **member subset** (from `map_members`); clusters here are the map's **sub-themes**
(reuse `name_clusters`). Cache per map like the team overview is cached.

**Web** `/maps/:id`:
- Identity header — name, plain-language definition, meta line, **one-line freshness note**
  ("+7 this week, mostly platinum-resistance"), Edit-definition / Share / ⋯.
- Hero **Scatter** (reuse `Map.tsx`'s `Scatter`, scoped), coloured by sub-theme, "show in
  full-corpus context" toggle (dims the rest of the corpus behind the highlighted members).
- Responsive: side-by-side with the (stubbed) summary on desktop; summary-first stack on mobile.

*Ships:* a real, explorable topic map. Validates the concept before any synthesis cost.

## Milestone 3 — Important papers, unread filter, labs & sub-themes

The action layer — likely the highest day-to-day value.

**API** `GET /maps/{id}/papers`:
- ranked members, default **Importance** = relevance × engagement × recency (reuse the
  `recommend_papers` scoring shape), with `recency` / `most-discussed` sorts;
- **read-state joined per caller** from `paper_status` — the new data join that powers *Unread*;
- `by_lab` / `by_tag` aggregations over the subset (reuse the `OverviewStats` shapes);
- `?q=` semantic search *within* the member set.

**Web**:
- Important-papers card: search box, sort control, filter chips (**Unread**, sub-theme, lab, year,
  code/data), rows with read-state dot · title · authors · venue·year · engagement · relevance;
  a per-row **dismiss** ("not relevant" → adds to `config.excluded`).
- Right rail: **Labs driving this topic** and **Sub-themes**, both cross-filtering list + scatter.

*Ships:* the reading queue — "what haven't I read in Ovarian Cancer?" — the retention hook.
*New work:* surfacing `paper_status` per viewer through these endpoints.

## Milestone 4 — AI summary of recent developments (last)

Highest cost + trust risk, so it lands on top of everything real.

**API** `POST /maps/{id}/summary` (and lazy read on GET):
- gather the most recent + most relevant members' abstracts, prompt the **Anthropic client already
  used by `overview.name_clusters`** (`settings.anthropic_api_key`, graceful fallback with no key);
- **grounded + cited only** — synthesize strictly from the supplied papers, return `{text,
  cited_ids}` mapping each claim to a real member (the `draft_related_work` discipline);
- **cache** in `maps.ai_summary`; regenerate on demand or when *N* new members since `generated_at`
  — never on every open (cost + trust).

**Web**: the "What's new" card — cited synthesis, honest freshness line, Regenerate, the "grounded
in N lab papers / nothing invented" footnote.

*Ships:* the weekly-habit hook. This is `draft_related_work` scoped to a map — the same synthesis
Claude does over MCP, now in-app for non-Claude users.

---

## Cross-cutting

- **Honesty states** (every milestone): no embeddings yet → explain + link to Papers; thin topic
  (< ~15 members) → show the scatter/list but suppress the summary ("too little to summarize");
  membership drift → surface "+N new" and a review affordance, never silent mutation.
- **Tests**: pgTAP RLS for `maps` (cross-lab + private isolation) and `map_members` correctness
  (pin included, exclude removed); API tests for each endpoint incl. the `paper_status` join;
  membership-precision spot-check on a seeded lab. The `atlas_mcp` suite stays green (no MCP change,
  but a future MCP `list_maps` / `get_map` is a clean follow-on).
- **Success metrics** (from the proposal): ≥1 saved map per active lab within 2 weeks; return
  visits to `/maps/:id`; **Unread-filter usage** (the action signal); regenerate-summary rate.

## Out of scope (deliberate follow-ups)

Exclude / tag-lab membership rules; MCP `list_maps`/`get_map` tools; map snapshots & "+N since last
visit" deltas; embedding a map in Home / comments; scheduled digests ("email me this map weekly").

## Suggested first PR

Milestone 0 + the `POST`/`GET /maps` half of Milestone 1 — the migration, RLS, `map_members`, seed
embedding, and create/list. It's self-contained, testable behind pgTAP + API tests, and unblocks
everything visual without touching `Map.tsx` yet.
