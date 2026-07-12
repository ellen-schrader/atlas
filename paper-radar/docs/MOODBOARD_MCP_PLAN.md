# Mood board over MCP — plan

Goal: let **Claude** (Claude Code, and Claude for Life Sciences at the hackathon) see and
use the lab's **mood board** — so a researcher can ask *"plot X in a style like this
board figure"* or *"visualise Y using our lab's visual identity"* and get code that matches
the lab's look, with the right handling for owned vs. third-party images.

This extends the MCP server from `docs/CLAUDE_INTEGRATION_PLAN.md` (P1, the `atlas_mcp`
package). It is **additive**: it exposes the mood board that already exists on `main`.

## What already exists (do not rebuild)

The mood board shipped in PR #21. Relevant pieces (see the migrations for detail):

- **`public.figures`** — lab-scoped from birth (`team_id` on the row). Columns:
  `id, team_id, uploaded_by, storage_path, title, caption, category` (free text,
  lab-defined), `paper_id` (optional link to a paper), `tags jsonb, width, height,
  mime_type, file_size, created_at`. Joins: `uploader` (profile), `papers` (linked paper).
- **RLS** (`20260712120000_mood_board.sql`): any lab member reads the board;
  insert/update/delete only your own rows (`uploaded_by = auth.uid()`).
- **Private Storage bucket `figures`** (`20260712121000_mood_board_storage.sql`): objects at
  `{team_id}/{figure_id}.{ext}`; `storage.objects` policies enforce lab isolation on the
  bytes (select/insert gated by `is_team_member(first path segment)`, delete by owner). The
  web app serves images via short-lived **signed URLs**.
- **`figure_categories(p_team)` RPC** — the lab's category facets.
- Parallel engagement tables `figure_comments` / `figure_reactions` (mentions out of scope).
- Web: `web/src/routes/MoodBoard.tsx`, `web/src/lib/figures.ts` (bucket name
  `FIGURES_BUCKET = "figures"`, accepted mime types, storage-path helper).
- Noted as future in the migration: a `figures.embedding` column for multi-modal
  similarity search — **not present yet**.

Because figures are already lab-scoped with RLS, the MCP tools are a thin read layer over
`figures` acting as the signed-in user — the same model `atlas_mcp` uses for papers.

## Decisions (agreed)

1. **Scope = lab identity, by default.** Tools return the whole lab's board (RLS keeps it
   lab-only). An optional `mine_only` flag restricts to `uploaded_by = you`.
2. **Support both own and third-party images**, distinguished by an explicit **origin
   toggle** (not owned-work-only). Default `own`; `third_party` chosen at upload.
3. **Third-party images carry provenance + license**; **own images are treated as the
   lab's confidential unpublished work.** The MCP surfaces this per image so Claude behaves
   correctly (derive style + attribute for third-party; confidentiality for own).
4. **Automatic license hint** for third-party figures linked to a paper (advisory only).

## Data model change (one migration)

Add to `public.figures`:

```sql
alter table public.figures
  add column origin      text not null default 'own'
             check (origin in ('own', 'third_party')),
  add column source_url  text,     -- third-party: where it came from
  add column license     text,     -- third-party: 'cc-by' / 'publisher' / … (hint, confirmable)
  add column attribution text;     -- third-party: display credit
```

- `own` → the other three stay null; the lab holds the rights (unpublished work).
- `third_party` → capture `source_url` / `license` / `attribution`.
- No `embargo`/`confidential` flag for now — the board is already private + lab-scoped;
  add later if a per-figure "do not send externally" signal is wanted.

## Automatic license — scope and honesty

Only meaningful for **third-party** figures **linked to a paper** (or with a DOI in
`source_url`):

- Resolve the **article** license from **OpenAlex** (`primary_location.license`) or
  **Crossref** (`license[]`); prefill `figures.license` as an **unconfirmed hint** the
  uploader confirms/overrides.
- Caveat (surface in UI): the article license ≠ the specific figure's license — a CC-BY
  article can contain excepted third-party panels; "closed" says nothing about reuse. So
  it's a strong default, not clearance.
- `own` figures need no lookup.

Copyright reasoning behind this (not legal advice): **style/palette/layout is not
copyrightable** — emulating a look is fine. Risk sits in **storing/redistributing** a
third-party figure and in **reproducing** (vs. restyling) one. Keeping the bucket private +
lab-scoped is a real mitigation (internal use). Surfacing source + license steers Claude to
"derive style, attribute, don't reproduce."

For **own unpublished** figures the concern is **confidentiality**, not copyright: the lab
already shares these in a Microsoft Teams channel (a vendor cloud), so the genuinely new
exposure is the **image bytes going to Claude/Anthropic** via MCP. Mitigations: private +
RLS (already true); confirm Anthropic's commercial data terms (no training on inputs by
default) against the lab's pre-publication / data-governance policy; scrub PHI if patient
imaging is involved.

## MCP tool surface (new, in `atlas_mcp`)

Acts as the signed-in user; RLS scopes every read to their lab. Image bytes are fetched via
`storage.from("figures").download(storage_path)` under the user client (storage RLS applies),
downscaled, and returned as **MCP image content** so Claude can see them.

- `list_moodboard(category?, tag?, origin?, mine_only=false, limit=20)` → text list:
  id, title, caption, category, tags, origin, uploader, linked paper, and (third-party)
  source/license/attribution.
- `moodboard_categories()` → `figure_categories` (the lab's visual vocabulary).
- `get_figure_image(id)` → downscaled image content + a text header (title/caption/category/
  origin + provenance). Powers *"plot like this figure."* Steers per origin:
  third-party → "derive style only, attribute {source}, don't reproduce"; own → "confidential."
- `get_figure_palette(id)` → deterministic dominant hex colors (Pillow), so Claude doesn't
  eyeball colors from pixels.
- `get_moodboard_style(category?)` → **the lab-identity tool**: aggregates palette +
  recurring conventions across the board (or a category) into a style spec **and** a ready
  `.mplstyle`. Answers *"visualise X based on our mood board."*

Defaults keep outputs transformative: the palette/style path (not pixel reproduction) is the
primary route, and provenance travels with every third-party image.

## Technical notes

- **Downscale before base64** (longest side ~768–1024px); cap with
  `_meta["anthropic/maxResultSizeChars"]`. `get_figure_palette` / `get_moodboard_style` are
  cheap and often enough without shipping the full image.
- **Inline bytes, not signed URLs** — vision needs the actual bytes in the tool result; a URL
  in the result doesn't let Claude see the image. Signed URLs remain the web/human path.
- Fetch under the **user client** so storage RLS enforces lab isolation.
- Deep links: the web mood board can take a `?figure=<id>`-style link (parallel to `?paper=`)
  so tool output can point a human at the figure; add if not already present.
- Reuse `figures.ts` constants (`FIGURES_BUCKET`, accepted mime types) conceptually; the MCP
  server is Python, so it reads bucket name/`storage_path` from the `figures` row directly.

## Build order / sequencing

PR #22 (the `atlas_mcp` base) is **merged to `main`**, and `feature/mcp-moodboard` is rebased
onto it — so `atlas_mcp` and the `figures` model are both present on this branch. Ready to
build:

1. ~~Get `atlas_mcp` and `figures` on the same branch~~ — **done** (PR #22 merged; this
   branch rebased onto `main`).
2. Migration: add `origin` + `source_url` + `license` + `attribution` (+ optional
   auto-license backfill for existing paper-linked figures).
3. MCP tools: `list_moodboard`, `moodboard_categories`, `get_figure_image`,
   `get_figure_palette`, then `get_moodboard_style`.
4. Validate over a real MCP stdio handshake against a seeded lab with a few figures
   (own + third-party), as we did for the paper tools.

## Phases

- **M1** — migration (origin toggle + fields) + read tools (`list_moodboard`,
  `moodboard_categories`, `get_figure_image`, `get_figure_palette`), provenance surfaced.
- **M2** — `get_moodboard_style` (the identity theme / `.mplstyle`) + the auto-license hint
  (OpenAlex/Crossref) wired into upload.
- **M3 (web, fast follow)** — the mood-board upload UI gains the **own/third-party toggle**
  and the license prefill; `get_figure_image` deep link.

## Status

- Plan written; design agreed. **Not yet implemented.**
- Prerequisite cleared: **PR #22 merged to `main`** (the `atlas_mcp` P1 base, validated live),
  and `feature/mcp-moodboard` rebased onto `main` — `atlas_mcp` + `figures` both present.
- Next action: **M1** — the `origin`-toggle migration + the read tools.
