# Maps — next steps: relevance threshold, curation, and follow-ups

The M0–M4 dashboard shipped with a deliberate simplification: **membership is top-N
by seed similarity with no relevance floor**, and there's **no way to correct it**
(pin a missed paper, drop a false positive). These next steps close that, then pick
up the smaller deferred items. Sequenced so each lands on its own; the first two are
coupled (both need a way to edit a map's `config`), so they come first together.

## 1. `PATCH /maps/{id}` — edit a map (unblocks 2 & 3)

One endpoint to change a map's `name`, `seed` (re-embed), `visibility`, and the
`config` knobs (`min_similarity`, `pinned[]`, `excluded[]`). RLS already makes this
creator-only (`maps_update`). Editing the seed re-embeds it server-side (Voyage).

- `PATCH /maps/{id}` body: any subset of `{name, seed, visibility, min_similarity,
  pin, unpin, exclude, uninclude}`. `pin`/`exclude` take a `paper_id` and do a
  set-add/remove on the jsonb arrays (so the client sends one action, not the whole
  array — no lost-update races).
- Web `lib/api.ts`: `updateMap`, `pinPaper`, `dismissPaper`, `setMapThreshold`.

## 2. Relevance threshold on membership

Stop a small corpus from making every paper a "member".

- **Migration** (`create or replace map_members`): add `min_similarity` from
  `config` (default **0.35** — a sane Voyage-cosine floor for "related", tunable per
  map). Keep only `similarity >= min_similarity`, **except pinned papers, which are
  always in**. Return a `below` count is not possible from a `returns table` RPC, so:
- Add a sibling `map_member_stats(p_map)` (or extend the endpoints) returning
  `{in_scope, below_threshold}` so the dashboard can say *"12 more papers are
  loosely related — broaden?"* and offer a one-click lower-threshold.
- Endpoints (`map_overview`, `map_papers`, summary) already call `map_members`, so
  they inherit the floor with no change beyond surfacing the `below` count.
- **Honesty**: if the floor leaves < 3 papers, the dashboard nudges "broaden the
  seed or lower the match threshold" rather than showing a near-empty map.

## 3. Curation UI (pin / dismiss)

Make the correction affordances real, per the seed+pin decision (dismiss is the
escape valve; pin guards the missing-seminal-paper downside).

- **Papers list**: each row gets a hover ⋯ menu — **Pin to this map** (forces it in
  above the threshold) and **Not relevant** (adds to `excluded`, removes it live).
  Pinned rows show a small pin glyph. Both call the PATCH actions and invalidate the
  map queries.
- **Threshold control**: a small "match: ≥ NN%" stepper in the papers header (or the
  "broaden" nudge from step 2), writing `min_similarity`.
- Creator-only affordances (viewers of a shared map don't see edit controls) — gate
  on `map.created_by === userId`, same rule as the library's delete.

## 4. MCP `list_maps` / `get_map` tools

Surface topic maps to Claude over MCP (read-only, RLS-scoped), a clean follow-on to
the existing 16 tools:
- `list_maps(team_id?)` → the lab's maps (name, seed, counts).
- `get_map(map_id)` → the map's top papers + sub-themes + (cached) summary as a
  citation block. Reuses `map_members` / the summary cache; no new write surface.

## 5. Full-corpus context overlay (scatter)

The "show in full-corpus context" toggle from the mockup: dim the whole lab's points
behind the highlighted members, so a PI sees *where the topic sits*. Needs the
Scatter to accept a background point set (a small, additive prop) + a second
`/overview` fetch enabled only when toggled.

## 6. Cross-filter symmetry (small)

Today a lab click filters the papers list but a sub-theme click only highlights the
scatter. To let a sub-theme also filter the list, `map_papers` must return each
paper's `cluster` (the layout already computes it in `map_overview`; either share it
or add cluster to the papers response). Then sub-theme click filters both.

## Sequencing & PRs

- **PR A** — steps 1 + 2 (PATCH endpoint + threshold + stats), backend-heavy, with
  pgTAP for the threshold/pin interaction and API tests for PATCH. Self-contained.
- **PR B** — step 3 (curation UI) on top of PR A.
- **PR C** — steps 4–6 as independent smaller PRs (MCP tools; overlay; cross-filter),
  any order.

## Open decisions for you

1. **Default threshold** — 0.35 cosine is my starting point; it's empirical and I'd
   tune it once there's a real (non-synthetic) corpus. OK to ship 0.35 + a per-map
   override?
2. **Auto-update vs. review** — membership already auto-updates as papers are posted
   (live query). Do you want a "3 new candidates — review" gate before they join, or
   is silent-join-with-a-"+N this week"-badge enough? (Simpler = the badge, which we
   already have.)
3. **Threshold control placement** — a visible "match ≥ NN%" stepper, or keep it
   implicit behind the "broaden" nudge only when the map looks thin?
