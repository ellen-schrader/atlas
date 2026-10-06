# Papers page reimplementation — plan (no-feed subset)

Goal: in a fresh worktree branched off `main`, reproduce a subset of what
`redesign/phase-1-ridge` did to the Papers page — tile/list sizing, the "open
paper" detail box, and a merged Add-paper/Import flow — **without** any
Library-vs-Feed / Teams-feed work (no `announced_at`, no share toggle, no
`PaperFeed`).

Decisions below are locked in from review; implementation order follows.

## Base

New worktree off `main`. Main's Papers page (cards + table only, no feed
toggle, no share model) is already close to the target, so this is a smaller
diff than starting from the redesign branch and stripping feed code back out.

Housekeeping: the current `redesign/phase-1-ridge` working tree has an
untracked, stray `src/routes/Import.tsx` left over from local experimentation
— not part of the branch's real history, ignore/delete it, don't treat it as
design intent.

## Scope — in

**Tile (card) view** — `PaperCard.tsx` sizing is already identical to main,
so no pure styling change needed there. Add: multi-select checkbox overlay +
selected-ring border (from the branch's CSV/BibTeX export feature — see
below).

**List (table) view** — port into `PaperTable` (still inline at the bottom of
`Papers.tsx`, not worth extracting for this scope):
- `table-fixed` layout with explicit column widths (Authors `w-48`,
  Engagement `w-28`, Posted `w-24`, Save `w-14`, plus a select-checkbox column
  when multi-select is active).
- Truncated (not wrapping) author cells.
- Keyboard-operable rows: `role="button"`, `tabIndex`, Enter/Space handler,
  focus ring.

**Open-paper box** (`PaperDetail.tsx` + shared `Modal`):
- Shell fix: `ui/modal.tsx` backdrop-dismiss switched from `onClick` to a
  `pointerdown`/`pointerup` pair, so a text-drag that ends outside the dialog
  doesn't close it.
- `fullPage` mode on `PaperDetail` + new `/papers/:id` route (`PaperPage.tsx`)
  for deep reading/printing with a stable URL, with an "Open as page" link in
  the modal (hidden when already `fullPage`).
- "Cite" popover (RIS/CSV/BibTeX/Markdown export) in the action row.
- DOI rendered as a clickable `doi.org` link instead of plain text
  (`PaperIdentifier`).
- Author list truncated to 5 + "show more" (`AuthorList`).
- **Not included yet:** the unified reading-status control. Keep main's
  existing separate Bookmark + "Mark read" buttons for now — the redesign's
  version needs a DB migration (splitting "saved" from reading progress into
  two axes), which is out of scope until you decide to take that on
  separately.

**Multi-select + export** (`12ab3cd` on the branch) — checkbox overlay on
cards and table rows, a floating export bar, CSV/Markdown/BibTeX export.
Self-contained, no feed coupling.

**Add-paper / Import merge** — see below.

## Scope — explicitly excluded

- `PaperFeed.tsx` and the "Feed" view toggle (cards/table only).
- `announced_at`, `SharePostButton`, the "Share with the lab" checkbox in
  Add-Paper, `POST /posts/announce`.
- Teams-feed reply/mention UI, feed unread watermark, feed-first toggle.
- Reactions endorse/sceptical split — moot either way (added then reverted on
  the branch itself).
- Reading-status two-axis model / unified status control (deferred, see above).
- Year/author/shared-by filters, most-discussed sort, saved searches, the
  shell-wide ⌘K palette — unrelated to this scope, not touched.
- `PaperListRow.tsx` — not the list view, not reimplemented. (The plan first
  called this "dead/orphaned code"; that was wrong — `routes/Dashboard.tsx`
  imports and renders it, and `PaperCard.tsx` cites it as the source of its
  keyboard guard. It is only unreferenced *from the Papers page*, which is why
  a grep run from here appeared to confirm it. Out of scope either way.)

## Add-paper / Import: merging into one dialog

Going with the true merge, as asked. Worth knowing going in: **the redesign
branch never actually did this** — it split the old `/import` page into its
own modal (`ImportDialog.tsx`) and just cross-linked it with Add-Paper via a
callback + shared `?add=1`/`?import=1` URL params. Still two components. I
don't have a strong reason to prefer that over a true merge for this
project — the only cost is a bit more restructuring of `AddPaperDialog`'s
step state machine, which is a one-time cost — so merging is the right call
here.

Implementation shape: `AddPaperDialog`'s current flow is a 4-step wizard
(url → recover → review → done). Add a mode choice at the very first step —
either a segmented control ("Paste a link" / "Upload a .bib") or two
side-by-side affordances (a URL/DOI input plus a drop zone) in the same
screen. Choosing "upload a .bib" branches into the existing Import flow's
drop-zone → preflight-table → commit steps, reusing that logic/UI as a mode
within the same `Modal` instance rather than a second dialog. Single entry
point, single button ("Add a paper") in the Papers toolbar; no more `/import`
route, no second toolbar button, no `onImport` handoff callback.

## Implementation checklist (suggested order)

1. New worktree + branch off `main`.
2. Modal shell fix (`ui/modal.tsx` drag-dismiss) — small, independent, do first.
3. Table view: `table-fixed`/column widths/truncation/keyboard rows in `PaperTable`.
4. Open-paper box, frontend-only pieces: `fullPage` + `/papers/:id` route,
   `PaperIdentifier` (DOI link), `AuthorList` truncation, Cite popover.
5. Multi-select + export: checkbox overlay on `PaperCard`/`PaperTable`,
   export bar, CSV/Markdown/BibTeX serializers.
6. Add-paper/Import merge: restructure `AddPaperDialog` to branch at step 1
   into link-entry vs .bib-upload; retire the standalone Import page/route.
7. Manual pass in the running app: cards, table, detail modal, full-page
   route, cite export, multi-select export, and the merged add/import flow.

Flagging one dependency to verify during (4)/(5): the Cite control's
RIS/CSV/BibTeX serializers and the multi-select export's CSV/Markdown/BibTeX
serializers overlap — worth checking whether a shared exporter module already
exists on `main` or needs to be introduced once, rather than duplicated
between the two features.
