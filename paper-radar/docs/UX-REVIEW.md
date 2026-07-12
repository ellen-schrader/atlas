# Atlas — holistic UX review

_Senior product/UX review after the redesign PRs (foundations → auth). Date: 2026-07-12._
_Method: Playwright walk-throughs of the running app against a seeded lab (TME Lab, 5 papers, comments/reactions/mentions) and a fresh no-data lab (New Lab)._

This is a critical assessment, not a status report. The redesign PRs (search backend, foundations, Papers page, shell, detail popup, dashboard, reading list, auth) are all merged and the app is coherent and genuinely usable. The notes below are where it still falls short of a product a lab would adopt without friction.

---

## 1. Core journeys walked

| Journey | Result |
|---|---|
| First run, no data (new lab owner) | ✅ Clean empty states on Home + Papers with CTAs. ⚠️ No prompt to invite teammates (see 2.4). |
| Browse / search papers | ✅ Server-side FTS, tag filters, card/table, infinite scroll, empty state all work. |
| Open a paper & engage | ✅ Route-backed popup; reactions toggle; **comment posting verified end-to-end**; bookmark works. |
| Save to reading list | ✅ Bookmark is optimistic, persists, and feeds Home "Needs your attention". |
| Post a paper | ❌ **Fails** when the Python API isn't running — raw "Failed to fetch" (see 2.1). |
| Team / tags | ✅ Tag filter (server `team_tags`); editable per-post tags in the detail (canonical tags click-to-add). |

---

## 2. Broken or awkward flows (ranked)

### 2.1 — BLOCKER: "Post a paper" is the only way to add content and it fails opaquely
Posting calls the FastAPI service (`/posts` on `:8000`). With the service down (or CORS misconfigured) the user sees a literal **"Failed to fetch"** under the input and nothing happens. This is the single most important write action in the product — a lab's entire value depends on papers getting in — and it has (a) a hard runtime dependency that isn't surfaced anywhere, and (b) an error message that tells the user nothing actionable.
**Fix:** friendly, specific error copy ("Couldn't reach the paper service — try again in a moment"); a loading/disabled state that's obvious; and, ideally, retry. Longer term, confirm CORS + uptime for the API in deployment, and consider a health signal so the Post button can disable itself with an explanation when the service is unreachable.

### 2.2 — MAJOR: "Needs your attention" never clears
Mentions and reading-list items populate Home's attention section, but there is **no way to dismiss them**. Mentions aren't filtered by `seen_at` and have no "mark read"; reading-list items only leave when you un-bookmark. The section therefore only grows, and "attention" stops meaning anything. The DB already has `mentions.seen_at` and a `paper_status` with `reading`/`read` states that the UI never uses.
**Fix:** mark mentions seen (on open, or explicit dismiss) and hide seen ones; let a reading-list item be checked off ("Mark as read" → `paper_status = read`), which also unlocks the `reading`/`read` lifecycle the schema already supports.

### 2.3 — MAJOR: Settings was not redesigned
`Settings.tsx` still uses the pre-redesign card layout. It inherits the new tokens so colours are consistent, but the composition (spacing, headings, the USER.md editor, the join-code block) is visibly from the old system and breaks the polish established everywhere else.
**Fix:** a short PR to bring Settings onto the new type scale / section pattern; surface the invite/join code more prominently (ties to 2.4).

### 2.4 — MINOR: New-lab owner isn't guided to invite anyone
A freshly created lab lands on a good "post your first paper" empty state, but a lab is a _team_ product — the owner's first job is usually to get colleagues in. The join code lives only on Settings. The empty Home/Papers should also offer "Invite your lab" with the code.

### 2.5 — MINOR: `⌘K` hint + cramped post bar on mobile
The search shows a `⌘K` affordance on touch devices where it's meaningless, and the "Post a paper" URL input is squeezed next to its button on narrow screens (should stack). Both are cosmetic but read as unfinished on a phone.

---

## 3. Improvements to existing features (ranked)

**Major**
- **Reactions are anonymous.** You see counts but never _who_ reacted — for a small lab, the "who" is the point. Add avatars/tooltip on hover.
- **No paper lifecycle in the UI.** `to_read` is the only status wired up; `reading`/`read` exist in the schema but there's no way to mark progress, so the reading list is a one-way inbox.
- **No way to remove a post.** Once a paper is posted to a lab there's no delete/hide, even for the poster or an owner. Mistaken or duplicate posts are permanent.

**Polish**
- **Table view lacks the bookmark** that cards have — inconsistent.
- **Search has no match highlighting** and no result feedback beyond the count; a query that returns 0 is handled, but partial matches give no sense of _why_ they matched.
- **`Map` is a dead "soon" affordance** with no explanation on click — a tooltip or a teaser page would set expectations.
- **Relative vs absolute dates** are mixed (cards say "Jul 11, 2026"; the mockup used "3 days ago"). Relative reads better in a feed.
- **The detail popup's editable tags** have no affordance hint that canonical (dashed) chips are click-to-add; discoverability is low.

---

## 4. Missing features a user would expect at this stage

- **A notifications surface** — mentions only appear on Home. A persistent indicator (badge on the nav, a bell) is expected once @-mentions exist. _Rationale: mentions are time-sensitive; burying them on one page loses them._
- **Delete / edit a paper post** — correct mistakes, remove duplicates. _Rationale: user-generated content always needs an undo._
- **Sort & richer filters on Papers** — sort by most-discussed/newest, filter by source/author/status. _Rationale: at 560+ papers, a single tag filter isn't enough to find things._
- **"Who's in my lab" / members view** — you can @-mention teammates but can't see the roster or manage it. _Rationale: team products need a member list; owners need to remove people._
- **Reading progress / history** — what have I already read? _Rationale: the reading list is only "to read"; there's no "done"._
- **Map view + "for you" ranking** — the literal atlas and taste model. _Rationale: promised by the product name and the pipeline; gated on the embeddings work (separate branch) and intentionally not built here._

---

## 5. Deferred UX-debt (from the per-PR reviews)

- [PR4] `⌘K` hint shows on touch/mobile where the shortcut doesn't apply. _(polish)_
- [PR4] "Post a paper" input is cramped next to the Post button on narrow screens; should stack `< sm`. _(polish)_
- [PR7] Table (list) view rows have no bookmark control, unlike cards. _(polish)_

---

## 6. Top 5 recommendations, in order

1. **Make "Post a paper" trustworthy (2.1).** Friendly error + retry + clear pending/disabled state, and verify the API's CORS/uptime in deployment. This is the product's front door.
2. **Make "Needs your attention" actionable (2.2).** Mark mentions seen; add "Mark as read" to reading-list items. Without this, Home degrades as the lab uses it.
3. **Add a notifications surface + a members view.** The two biggest _missing_ pieces for a team product now that mentions and teams exist.
4. **Bring Settings onto the new design and add an invite prompt (2.3 + 2.4).** Small effort, removes the one visibly-unfinished screen and improves new-lab onboarding.
5. **Round out the paper lifecycle:** delete/hide a post, and use the `reading`/`read` statuses so the reading list becomes a real workflow rather than a growing inbox.

---

### What's genuinely solid (so it isn't lost)
Server-side search + pagination; the `PaperCard`/`Cover` system and the microscopy identity; the route-backed, accessible detail popup (focus-trapped, shareable, back-button aware); optimistic bookmarks; the responsive shell; and coherent empty/loading/error states on the rebuilt screens. The foundation is strong — the gaps above are product-completeness, not architecture.
