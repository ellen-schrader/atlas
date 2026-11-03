# Projects (replaces topic maps, absorbs #181)

Status: proposal, 2 Nov 2026. Mock-ups: the "Projects" row on the maps canvas
(https://claude.ai/artifact/83QiULmTWyWg8R3f8d1GVp).

## Why

Topic maps were built to watch a field. Few people use them, and the v2 drafts
drifted into a second Home page (tag growth, who's publishing, recommendations,
outside search), all of which Atlas already has. The job researchers actually
have is narrower: **"I'm working on X. Show me my papers for it and what I'm
missing."** One person already uses maps that way, to find papers near a topic.

#181 asks for the same thing from the reading list side (group papers into
projects). Building both would give two ways to group papers that don't know
about each other, so they become one feature: a **project**, seen as a list on
the reading list and as a closeness chart on its own page.

Users: postdocs and students, desktop only.

## What a project is

- A name, an optional one-line description, and a set of papers.
- Any library paper can go in a project because it's relevant. Adding it does
  **not** save it to the reading list. Marking it to read stays one click (the
  existing bookmark), separate from membership.
- Visibility: **Only you**, **Whole lab**, or **Chosen people** (lab members).
  Everyone who can see a project can add and remove papers; only the owner
  renames, changes visibility or deletes.
- Papers dismissed from "Close, not in it" stay dismissed for that project.

## Screens

**Projects index (`/projects`, nav "Projects", replaces "Topic maps").**
One card per project: a small closeness × year chart, name, description, top tags,
members, paper and unread counts, visibility, and an "N new suggested" badge when
papers above the project's line arrived since you last opened it. Beside the
cards, a "New suggestions" list across all your projects with + / ✕. No library map.

**Project page (`/projects/:id`).**
- **Closeness × year chart** (replaces the t-SNE scatter). x = publication year,
  y = cosine similarity to the closest paper already in the project. Project papers
  filled, suggested ones ringed (new ones bolder), the rest of the library faint. A
  dashed line marks "suggested above this"; Fewer / Balanced / More moves it (the
  old maps `min_similarity`). The shaded top-right corner is "recent and close".
  Low dots inside the project are outliers. Click a dot for the paper card
  (+ Add / Not relevant / Save to read, similarity, "Closest to …"); "Add all N".
- Side list, tabs **In project** / **Suggested**, sorted closest first by default,
  each row with a small similarity bar and "closest to …".
- **Around this project**: two cards under the chart and list, Tags (with the range
  control: **All time** default / 12 months / 30 days) and Labs (last author). Each
  row: follow star, name, a sparkline of related papers over the range, "in /
  related" (same meaning in every range) and the gap ("22 not in it"), which opens
  Suggested showing those papers. Sorted followed first, then most missed. Counts
  run over the related pool: the library papers closest to the project (same
  pgvector query, larger limit). Hover lights papers on the chart; click filters.
- **Three groups, named once:** In project, **Suggested** (above the line, plus
  papers from followed tags or labs below it, labelled "from followed tag …"), and
  Related (the pool behind the counts). "Nearby" is renamed Suggested everywhere.
- Header: "Following: … · Edit" under the description; "Updated 3 days ago" opens
  the activity as a popover. Needs `project_follows` (project_id, kind tag|lab, value).
- Header actions: Export .bib, Share, Add papers, More.

**Elsewhere.**
- Reading list: project chips filter the list (#181 PR 3).
- Paper rows, paper page and paper card: "Add to project" picker, next to the
  bookmark but independent of it.

**Cut** from the v2 drafts and the current dashboards: AI "What's new" summary,
Claude-named sub-themes, tag growth, who's publishing, KPI tiles, outside-library
search, Follow, the lab focus chips, the t-SNE library map.

## Data model (one migration)

- `projects`: id, team_id, owner_id, name, description, description_embedding
  (nullable), visibility (`private` | `lab` | `people`), created_at, updated_at.
- `project_people`: project_id, user_id. Used only when visibility = `people`.
- `project_papers`: project_id, paper_id, state (`in` | `dismissed`), added_by,
  added_at. Primary key (project_id, paper_id).
- `project_views`: project_id, user_id, last_viewed_at. Drives "N new suggested".
- RLS: read if owner, or `lab` and same team, or listed in `project_people`.
  Paper writes for anyone who can read; settings for the owner only.
- RPC `project_closeness(p_project, p_limit)`: for each library paper, its
  highest cosine similarity to any project paper (and which one), plus the same
  leave-one-out value for project papers. Falls back to the description embedding
  while the project has fewer than 3 papers. Nearest-paper rather than centroid,
  so projects with two strands don't get suggestions from the empty middle.
- Existing `maps` rows migrate: seed → description, pins → `in`, excludes →
  `dismissed`, visibility kept. `/maps/:id` redirects to `/projects/:id`.

## Cost

No new monthly cost, and less than today. Every paper already has an embedding;
similarities and candidates are one pgvector query (nearest project paper per
library paper, computed in Postgres); tag and lab bars are counts. There is no
2-D layout any more, so t-SNE, KMeans, scikit-learn and scipy leave the API. The only new external call
is one Voyage embedding when a description is saved (a fraction of a penny).
Removing the map summary and the Claude-named clusters removes the only per-use
Claude calls the maps pages make today.

## PRs

0. Retire topic maps and the figure gallery first (done): their pages, API
   (`maps.py`, `overview.py`, `map_summary.py`, `/similarity`), the mood-board MCP
   tools, scikit-learn/scipy and Pillow/matplotlib; a locked "Projects" page in the
   nav; the Fly machine down to 512 MB. Tables (`maps`, `trends`, `figures`, the
   `figures` bucket) stay, so step 1 can migrate maps and nothing is lost.
1. Data model, RLS, RPC, API, maps → projects migration, behind a `projects`
   feature (public.my_features), on for one person first. Replaces #181 PR 2.
2. Project page and index (closeness chart, tabs, tags and labs, sharing dialog).
3. Reading list chips and the "Add to project" picker (#181 PR 3).
4. Open it to the lab; later, drop the unused `trends` table and the figure tables
   and bucket once nobody needs them.

Each gets `/code-review high` before it's called ready.

## Later, maybe: project notes

A markdown page per project, citing papers with `[@citekey]` (the same syntax as
the Obsidian work), where typing `@` searches the library and cited papers not in
the project get an "Add 3 cited papers" prompt.

Not in this plan. A shared editor brings conflicts, history and formatting, and
some researchers will prefer Obsidian or Word, which the citekey work already
serves. Ship projects first, then ask the people using them where they'd write.
