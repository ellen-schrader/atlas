# Atlas — map dashboards: design proposal

> ## ⛔ SUPERSEDED — do not build this (2026-07-13)
>
> **User testing killed the core premise.** Asked about saved map documents, a
> researcher said: *"Saving maps is a nice gimmick but I don't know if I would
> use it. The general stats overview and interactive map of the current
> prototype seems more practical."*
>
> That is precisely the falsification condition this proposal set for itself, so
> the **library, lens gallery, composer, and `maps` table are all cut**.
>
> **What survives:** a *Share this view* link that encodes the current Overview
> filters in the URL — the useful 5% of "saving a map", at roughly a day's work
> instead of a sprint. The Overview page becomes the centrepiece rather than one
> map among many.
>
> **What replaced it in priority:** BibTeX import (the PDF scrape was called
> "quite hacky") and the Connect/MCP setup screen (the only feature a user
> called *important* unprompted).
>
> See `docs/atlas-redesign-mockup.html` for the current (v3) direction. The text
> below is kept as a record of the reasoning and how it was wrong.

_Redesign proposal series · Flow 2: **creating a map dashboard + new-map selection**._
_Senior UX draft, 2026-07-12. Companion visual: the "Atlas — Map dashboards" artifact (wireframes of every step)._

---

## 1. Where this sits

The redesign shipped `/map` as a single **Overview** page: the UMAP scatter with
color/size controls, a semantic topic lens, LLM-named themes, and six stat
panels. It's good — and it has a ceiling built in:

- **Every insight is ephemeral.** A PI who builds "our corpus, colored by
  relevance to *ductal carcinoma*, filtered to the Werb lab" loses that view the
  moment they navigate away. There is no way to save it, return to it, or show
  it to anyone.
- **One page serves every question.** Weekly lab-meeting recap, grant-landscape
  scan, onboarding a new student — all share one screen and one transient
  configuration. The controls row keeps growing to compensate (color, size,
  hulls, topic, plus four filter kinds), which is the classic sign that one
  document is trying to be several.
- **The name over-promises.** The product is called *Atlas*; an atlas is a
  *collection* of maps. We ship exactly one.

**Proposal: maps become documents.** Users create, name, save, and share map
dashboards. The Overview stays — as the pinned, always-current lab map — and
user maps live beside it. This flow covers the journey from "I want a map of X"
to a saved, shareable dashboard.

## 2. Principles

1. **Maps are documents, not settings.** A map has a name, an owner, a
   description, and a URL. It appears in a library, not in a dropdown of
   presets. Everything about the flow (create, rename, duplicate, delete,
   share) should feel like working with files, because the mental model already
   exists.
2. **Create by doing, not by form.** Never show an empty preview or a wizard.
   From the first click the user is looking at *their corpus, live*, and every
   control change repaints it. Configuration is a side effect of exploring.
3. **Templates are questions, not chart types.** A lab doesn't think
   "categorical color encoding" — it thinks "what are our themes?", "what's
   near this topic?", "what are we actually reading?". The new-map gallery
   sells starting points by the question each one answers.
4. **The free version of saving is promotion.** The existing Overview controls
   already produce interesting states; when the user has dirtied one, offer
   "Save as map". The transient state they already built becomes the seed of a
   document — zero extra learning.

## 3. IA & naming

- Nav item **Map → Maps** (icon unchanged). It lands on the **library** when
  the user has maps, or straight on Overview when they have none (no pointless
  hub page for a single item).
- Routes:
  - `/maps` — library (pinned Overview + user maps + New map).
  - `/maps/overview` — the pinned lab map (today's page, unchanged behavior).
  - `/maps/new` — new-map selection, a route-backed modal over the library
    (same pattern as the paper detail popup: shareable, back-button aware,
    focus-trapped).
  - `/maps/:id` — a saved map dashboard.
- Vocabulary: "**map**" for the document ("New map", "Save as map", "Share
  map"). "Dashboard" stays internal — users only ever see *maps*, which keeps
  the Atlas metaphor doing the work.

## 4. The flow

### 4.0 Entry points

| Entry | Where | Behavior |
|---|---|---|
| **New map** button | Maps library header + empty-slot card in the grid | opens `/maps/new` |
| **Save as map** | Overview toolbar, appears once any control/filter is dirtied | opens the composer pre-seeded with the current state, skipping the gallery |
| **Duplicate** | any saved map's ⋯ menu | composer seeded from that map, named "Copy of …" |

### 4.1 New-map selection (`/maps/new`)

A route-backed modal: a 3×2 gallery of **starting lenses**. Each card =
miniature live thumbnail (a mini-scatter of the *actual* corpus rendered in
that lens's encoding — cheap: the point set is already cached client-side),
a name, and the question it answers.

| Lens | Question it answers | Seed configuration |
|---|---|---|
| **Theme atlas** | What are the areas of our corpus? | color: cluster · hulls on · panels: themes, tags |
| **Topic lens** | What do we have near *this* topic? | asks for a topic inline → color: relevance · panels: top matches, themes |
| **Timeline** | How has our reading shifted over time? | color: year ramp · panels: shared-over-time, by-year |
| **Venue landscape** | Where does this field publish? | color: venue · panels: top venues, labs |
| **Lab activity** | What is the lab actually reading & discussing? | size: engagement · color: cluster · panels: most-discussed, over-time |
| **Blank map** | Start from the raw map. | uniform everything, no panels |

Details that matter:

- **Topic lens asks inline.** Selecting it flips the card face to a single
  topic input ("relevance to…") with the search affordance; submit → composer.
  No intermediate screen.
- **Small-corpus honesty.** Theme atlas needs enough embedded papers to
  cluster meaningfully; below ~20 the card stays visible but carries a quiet
  "needs ~20 papers" badge and is non-primary. Never hide capability, never
  fake it.
- Keyboard: arrows move between cards, Enter selects, Esc closes back to the
  library. The gallery is a `listbox`, cards are options.

### 4.2 The composer (unsaved map)

Selecting a lens lands in the **composer**: the full dashboard, live, with a
right-hand configuration rail. It *is* the map page — not a preview of one.

- **Header**: breadcrumb `Maps / `, then an inline-editable title, pre-filled
  by the lens ("Topic: ductal carcinoma", "Theme atlas"). A dashed underline +
  pencil-on-hover mark it editable. An "Unsaved" chip sits beside it.
- **Config rail** (280px, collapsible, becomes a bottom sheet `< md`):
  - *Lens* — switch starting lens without losing filters.
  - *Color by* / *Size by* — the existing segmented controls, relocated.
  - *Topic* — the semantic query input (visible in all lenses; filled = adds
    relevance option to Color by, exactly as today).
  - *Filters* — theme / tag / lab chips, same semantics as today's filter row.
  - *Panels* — the preset panel list for this lens with checkboxes; a light
    version of composability (reordering and custom panels are follow-ups).
- **Primary action**: **Save map** (accent, rail footer + header). Secondary:
  Discard. Saving with the default name is fine — names are editable forever.
- Leaving with unsaved changes → the standard confirm ("Save map? / Discard /
  Keep editing"). Cheap insurance, rarely seen.

### 4.3 The saved map (`/maps/:id`)

The same page, rail collapsed by default. Identity comes from the header:

- Title (inline-editable by the owner), optional one-line description, and the
  **lens chips**: the map's configuration rendered as the same chips used
  everywhere in Atlas (`Topic: ductal carcinoma` · `Color: relevance` ·
  `Lab: Werb`). The config is never hidden state — it's legible on the page.
- Meta line: owner avatar + "by Ellen · updated 2 days ago" ·
  visibility ("Only you" / "Lab").
- Actions: **Share with lab** toggle (personal by default; shared maps appear
  in every member's library with the owner's avatar), Duplicate, Delete
  (owner-only, confirm). A **map switcher** on the breadcrumb (dropdown:
  pinned Overview, your maps, lab maps, "New map…") makes hopping between maps
  one click.
- **Live data, saved lens.** A map saves its *configuration*, not a snapshot —
  reopening always shows the current corpus through the saved lens. (A paper
  count delta — "+12 since you last opened" — is a cheap, delightful follow-up.)
- Ad-hoc exploration on a saved map (hover, click-through, temporary filters)
  doesn't dirty it; only rail changes do, which then show "Edited" with
  Update / Save as new / Reset. Viewers of a *shared* map they don't own get
  "Save as new" only.

### 4.4 States

- **No embedded papers**: the library still renders; Overview card explains
  ("embeddings compute shortly after posting"), New map disabled with the same
  reason. Never a dead end: link to Papers.
- **First run (has papers, no user maps)**: `/maps` shows the pinned Overview
  full-width plus a slim "Make your own map" strip teasing three lens cards —
  the library grows out of the page rather than starting empty.
- **Deleted / unshared map**: visiting its URL → "This map is gone or private"
  with a link back to `/maps`.

## 5. Feasibility (why this is cheap)

Rendering reuses everything the Overview already has: `/overview` (points,
clusters, stats) and `/search/semantic` (relevance). A map is **one row**:

```sql
create table maps (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references teams(id),
  owner_id uuid not null references users(id),
  name text not null,
  description text,
  config jsonb not null,      -- { lens, colorBy, sizeBy, topic, filters, panels }
  shared boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- RLS: owner full access; team members read where shared.
```

No new chart work, no new endpoints beyond `maps` CRUD. The composer is a
re-layout of the existing Map.tsx controls into a rail. The riskiest piece is
the gallery's live thumbnails; fallback is static sketches in the lens palette.

## 6. Success measures

- ≥1 saved map per active lab within 2 weeks of ship (activation).
- Return visits to a saved map URL (the whole point: recall).
- Share-with-lab rate on saved maps (team value).
- Shrinkage of the Overview's transient-control usage in favor of saved maps
  would be a *good* sign, not a loss.

## 7. Out of scope (follow-ups)

- Panel reordering / custom panels beyond per-lens presets.
- Map snapshots & change deltas ("+12 papers since last visit").
- Embedding a map in comments / the dashboard's Home page.
- Scheduled digests ("email me this map monthly").

## 8. Open questions

1. **Library vs. direct landing** — proposal says `/maps` lands on Overview
   until the first user map exists. Comfortable, or always show the library?
2. **Shared-by-default?** Proposal: personal by default. A small lab might
   prefer everything shared; could be a team setting later.
3. **Lens set** — are these six the right starting questions for the pilot
   labs, and is "Lab activity" worth shipping before engagement data accrues?
