# Atlas Home: dashboard redesign spec

**Design reference:** `AtlasHome.dc.html` (responsive build) · canvas `Atlas Dashboard Redesign.dc.html`, turn 3 (3a–3d)
**Replaces:** `paper-radar/web/src/routes/Dashboard.tsx`
**Status:** Ready for implementation (open questions are listed at the end)

---

## 1. Goals

Today most users skip Home and go straight to Papers. The new Home should answer three questions in one screen:

1. **What's new in my lab?** The lab feed, visible on a typical laptop without scrolling.
2. **What should I read?** Recommendations, each with a visible reason.
3. **What's the field doing?** Trending tags and authors, plus tag volume over time.

It also makes two actions one step away: **search** and **add a paper**.

Non-goals: no new external data sources. All trends come from papers already shared in the lab.

---

## 2. Layout

### 2.1 Page structure (top to bottom)

| # | Block | Grid placement (≥ 900px) |
|---|---|---|
| 1 | Greeting + subtitle | spans N−1 columns, row 1 |
| 2 | Omnibar (search + add) | spans N−1 columns, row 2 |
| 3 | Continue reading | last column, rows 1–2 (label in row 1, card in row 2) |
| 4 | Recommended for you (horizontal scroll row) | full width |
| 5 | Lab feed | spans N−1 columns |
| 6 | Trending (Tags / Authors tabs) | last column |
| 7 | Tag volume chart | last column, stretches to the bottom of the Lab feed |

All blocks sit on **one shared column grid** with `gap: 24px`. Card edges in the recommendations row must line up with the column edges of the blocks above and below. This was the main layout requirement from review.

- Grid: `grid-template-columns: repeat(N, minmax(0, 1fr))`.
- Header row: the greeting/search wrapper and the Continue reading wrapper use `grid-row: span 2; display: grid; grid-template-rows: subgrid`. This puts the greeting and the "Continue reading" label on one row, and the search bar and continue-reading card on the next. Both wrappers also need `grid-template-columns: minmax(0,1fr); min-width: 0`, or long nowrap titles blow the column out.
- Recommendation card width: `calc((100% - (N-1) * 24px) / N)` with `box-sizing: border-box`.
- Lab feed and the right rail use `align-items: stretch`. The Tag volume card is `flex: 1`, so both columns end on the same line.
- Every section heading sits **outside** its card, in a fixed 28px row with 14px below it. This keeps the card tops level across columns.

### 2.2 Breakpoints

Breakpoints are based on the width of the app shell. Use a `ResizeObserver` or container queries, not only media queries.

| Name | Shell width | Nav | Columns (N) | Notes |
|---|---|---|---|---|
| Desktop XL | content ≥ 1660px | full sidebar (232px) | 5 | 5 recommendation cards visible |
| Desktop | ≥ 1360px | full sidebar | 4 when content ≥ 1400px, else 3 | content `max-width: 1680px`, centred |
| Laptop | 900–1359px | **icon strip** (64px) | 3 | 1280 × 800 is the reference laptop |
| Tablet | 640–899px | icon strip | 1 | recommendation cards 2-up; Trending + Tag volume side by side (2-col grid) under the feed |
| Mobile | < 640px | top bar (56px: menu, logo, bell) | 1 | see §2.3 |

"Content" = shell width − nav − horizontal padding. N only adds columns: on wide screens we show **more cards**, never wider cards. The rail is always one column wide.

Padding: desktop `34px 40px 44px`, laptop `30px 32px 40px`, tablet `28px`, mobile `20px 16px 32px`. Vertical gap between blocks: 30px (mobile 26px).

### 2.3 Mobile specifics

- Order: greeting → search → continue reading → recommendations → lab feed → trending → tag volume.
- Search bar is 54px tall. The add button is a 44 × 44 icon-only "+" with `aria-label="Add paper"`. ⌘K hint hidden. Input font-size 16px, to stop iOS zooming in on focus.
- Recommendations: swipeable, card width 84%, bleeding to the screen edges (`margin: 0 -16px; padding: 0 16px; scroll-padding: 0 16px`) so the next card peeks in. No arrow buttons.
- Feed rows: title wraps to 2 lines (`-webkit-line-clamp: 2`). Meta line = topic dot · venue · year · poster first name · time. Comments, avatar and the tag line are hidden. Bookmark becomes a 44 × 44 tap target on the right.
- "With comments" filter hidden; "All" and "Unread" remain.
- All tap targets are at least 44px. On touch screens the tag volume chart works by tapping, not hovering.

---

## 3. Components and behaviour

### 3.1 Greeting

- `{greeting()}, {firstName}`, using the existing `greeting()` helper. Source Serif 4 600, 29px (mobile 24px), tracking `-0.022em`.
- Subtitle: **"{n} new papers in {team.name} since your last visit."** The count is rendered in `--fg`. If n = 0, show "Nothing new in {team.name} since your last visit."
- **Needs:** a `last_seen_at` timestamp per user and team, updated when Home unmounts or after 10s on the page.

### 3.2 Omnibar (search + quick add)

A single input that switches mode depending on what's typed in it.

| Input | Mode | Dropdown |
|---|---|---|
| empty | — | none |
| matches `^(10\.\d|https?:|doi:|arxiv)` (case-insensitive) | **Add** | Preview card: "Found via Crossref · {venue} · {year}", title, authors (first 3 + "+n"), "suggested tags …", and an **Add to {team.name}** button. On success: "✓ Added to {team.name}". If the paper already exists: show it, "Already shared by {name} · {relative}", and **Open →**. |
| anything else | **Search** | Up to 5 results from `usePaperSearch` (title + venue). Header "{n} matches"; footer "See all in Papers →" opens `/papers?q=…`. |

- Placeholder (≥ 640px): **"Search by title, author or tag, or paste a DOI or link to add"**. Mobile: **"Search, or paste a DOI to add"**.
- The **Add paper** button (accent) focuses the input in Add mode. Pressing it on an empty input opens the existing `AddPaperDialog` for PDF/BibTeX.
- ⌘K / Ctrl+K focuses the input from anywhere on Home. ↑/↓ move through results, ↵ opens, Esc clears and closes.
- Debounce search by 150ms. Run DOI resolution on paste and on ↵. Reuse the metadata lookup from `AddPaperDialog.tsx` rather than building a new one.
- In Add mode the bar gets an accent border and a `0 0 0 4px var(--accent-weak)` ring, plus a small "DOI detected" pill (desktop only).

### 3.3 Continue reading

Same data and logic as today's `ContinueReading`: the oldest unread paper on the reading list.

- Label row: "CONTINUE READING" · right: "Reading list · {count} →".
- Card is 50px tall (mobile 60px):
  - Bookmark icon tile, 34px
  - Title on one line with ellipsis
  - Meta: "{venue} · {year} · saved {relative}"
  - ✓ button, "Mark as read" (30px, mobile 44px)
- Empty list: hide the card and show "Nothing queued. Bookmark papers to build your list." in `--muted`. Keep the block so the grid keeps its height.

### 3.4 Recommended for you

- Data: `useRecommendations(team.id, "discover", 12)`. Fetch 12 so wide screens can fill 4–5 cards and still scroll.
- Header: "RECOMMENDED FOR YOU" · right: ‹ › arrow buttons (hidden on mobile; each click scrolls one page of N cards) · **"Tune →"** (opens `/settings`, research profile).
- Horizontal scroll row: `scroll-snap-type: x mandatory`, scrollbar hidden, no edge fade.
- **Card** (`--surface`, 1px `--border`, `--radius-card`):
  1. A 2px top line: gradient `transparent → {topic colour}66 → transparent`.
  2. Eyebrow: topic dot (6px) · "{VENUE} · {YEAR}" · right-aligned match score (mono, `title="Match to your interests"`).
  3. Title: `--text-card` 600, clamped to 3 lines, **fixed height 57px**.
  4. Authors on one line with ellipsis.
  5. Up to 2 tag chips (existing `Chip`). The second chip shrinks with ellipsis.
  6. Footer, pinned to the bottom with `margin-top: auto`, top border: ✦ accent icon + reason text clamped to 2 lines at a **fixed height of 34px** + bookmark button. Fixed heights keep the footers level across cards.
- **Reason copy.** Use exactly these three patterns; the referenced item is rendered in `--fg`:

  | Signal | Copy |
  |---|---|
  | similar to a saved paper | Similar to *{paper title}*, which you saved |
  | similar to a read paper | Similar to *{paper title}*, which you read |
  | followed tag(s) | Tagged *{tag}*, which you follow / Tagged *{tag}* and {tag2}, which you follow |
  | followed author | By *{author}*, who you follow |

- States:
  - Loading: 3 skeleton cards (reuse `CardSkeleton`, sized to the grid).
  - Cold start: keep the existing notice copy from `Dashboard.tsx`, placed above the row.
  - Waking or error: keep the existing copy.
- **Needs (backend):** each result must include `reason: { kind: "similar_saved" | "similar_read" | "tag" | "author", ref_id, ref_label, extra_labels? }` and `score: 0..1`. Show the score only if we decide to (see open questions).

### 3.5 Lab feed

- Data: `usePaperSearch(team.id, "")`, newest first, grouped by day: Today, Yesterday, then weekday names ("Monday") within the week, then dates ("12 Sep").
- Header: "LAB FEED" + segmented filter **All · Unread {n} · With comments** · right: "Browse all →".
- Group label row: 10.5px uppercase `--faint` on `#0c1118`.
- **Row** (grid `6px | 1fr | auto`, padding `12px 18px`, minimum height 44px):
  - Unread dot (accent; transparent when read; `title="Unread"`). Uses `useReadPapers`.
  - Title: 14px 600, one line with ellipsis (mobile: 2 lines).
  - Meta: topic dot · VENUE (uppercase, `--muted`, 600) · year · tags (mono, ellipsis).
  - Right: comment count (only if > 0) · poster avatar (22px) · relative time · bookmark.
- Footer: "Show {n} more from this week" (see open questions).
- Show 8 rows by default. The list must be at least as tall as the right rail, so the rail never ends below the feed.

### 3.6 Trending · 30 days

- Tabs: **Tags | Authors** (segmented, local state).
- **Tags:** top 6 tags by number of papers posted in the last 30 days.
  - Row: tag name (mono) · count · change vs the previous 30 days.
  - Bar: the previous-30-day value as a 6px `--border-strong` track; the current value as a 3px bar on top.
  - Current bar colour: accent at 0.8 opacity if rising, `#5b6670` if falling.
  - Change colour: accent if ≥ +4, otherwise `--muted`.
  - Legend: "last 30 days" / "previous 30 days".
- **Authors:** top 5 authors by number of lab papers in the last 30 days. Shows initials avatar · name · "shared by {n} people" (+ " · you follow") · paper count.
- Clicking a tag opens `/papers?tag=…`; clicking an author opens `/papers?author=…`.
- Hovering a tag row highlights the same tag in the Tag volume chart. Shared state: `hoveredTag`.

### 3.7 Tag volume

- Header: "TAG VOLUME" · right: "papers per week · last 12 weeks".
- Stacked area chart of the same 6 tags as Trending, weekly buckets, 12 weeks. SVG `viewBox 0 0 300 110`, `preserveAspectRatio="none"`, fills the remaining card height (minimum 130px).
- **Default state is monochrome:** bands alternate `#39434c` / `#2c3743` with 1px `--surface` separators, and there is no legend.
- **Hover (tap on touch)** a band, or the matching Trending row:
  - That band takes its topic colour (`--ch-*`) at 0.9 opacity; the others dim to `--surface-3`.
  - The readout row above the chart shows: colour swatch · tag name · "{n} in 30 days · {change}".
- The readout numbers **must** match the Trending row (same source). The chart only supplies the shape.
- Idle readout text: "Hover the chart to see a tag" (touch: "Tap the chart to see a tag").
- X-axis labels: first, middle and last week (mono 10.5px `--faint`).

---

## 4. Colour usage

The goal is to stay close to the existing palette. **Cyan (`--accent`) is reserved** for:

- the primary action ("Add paper")
- unread dots
- rising-tag bars and large positive changes
- the ✦ recommendation-reason icon
- the omnibar's Add-mode ring

Topic colours (`--ch-1…6`) are **data only**, as `index.css` already requires. They appear only as:

- 6px topic dots on recommendation cards and feed rows
- the faint 2px line at the top of recommendation cards
- the hovered band in the Tag volume chart

Everything else uses the neutral tokens (`--surface`, `--surface-2`, `--border`, `--muted`, `--faint`). Use the tokens, not the hex values from the mock.

**Needs:** a `topic_cluster` (index 1–6) for each paper, taken from the Maps clustering so that Home colours match the map. Fallback: `--ch-off`.

---

## 5. Typography and tokens

These come from `index.css`; no new tokens are needed.

- Section headings: `text-eyebrow font-bold uppercase tracking-eyebrow text-muted` (existing `Section`).
- Card titles: `text-card font-semibold tracking-snug`.
- Meta text: `text-meta text-muted`.
- Display text: `font-serif` (Source Serif 4 600) for the greeting only.
- Numbers: `font-mono tabular-nums`.
- Radii: cards `--radius-card` (13px), controls `--radius-control`, chips `--radius-chip`.

---

## 6. Data and API summary

| Need | Source | New? |
|---|---|---|
| Papers since last visit | `last_seen_at` per user/team + posts query | **new column** |
| Search results | `usePaperSearch` | existing |
| DOI / URL lookup | logic from `AddPaperDialog` | refactor into a hook, `usePaperLookup(input)` |
| Duplicate check on add | lookup by DOI / normalised URL within the team | **new query** |
| Next to read | `useReadingList` | existing |
| Recommendations + reason + score | `useRecommendations` | **extend response** |
| Read state | `useReadPapers` | existing |
| Comment counts | `useEngagementCounts` | existing |
| Trending tags (30d vs previous 30d) | aggregate over the team's posts | **new RPC** `trending_tags(team_id, days)` |
| Trending authors | aggregate over the team's posts | **new RPC** `trending_authors(team_id, days)` |
| Weekly tag series (12w, top 6) | aggregate | **new RPC** `tag_volume(team_id, weeks, tags[])` |
| Topic cluster per paper | Maps clustering | **expose on paper** |

Cache the trend RPCs for 10 minutes; they don't need to be live.

---

## 7. Accessibility

- All icon-only buttons have an `aria-label`: Add paper, Mark as read, Save, Scroll left/right.
- The omnibar uses the combobox pattern (`role="combobox"`, `aria-expanded`, `aria-activedescendant` on results).
- The unread dot has `aria-label="Unread"`; read rows have no label.
- The chart has `role="img"` with an `aria-label` summarising the top rising tag. The Trending list is the accessible equivalent of the chart.
- Text contrast is at least 4.5:1. `--faint` is used only for non-essential labels (group headers, axis labels).
- Focus rings use the existing `focus-visible:ring-2 ring-accent`.

---

## 8. Copy reference

| Location | Copy |
|---|---|
| Subtitle | {n} new papers in {team} since your last visit. |
| Omnibar placeholder | Search by title, author or tag, or paste a DOI or link to add |
| Omnibar placeholder (mobile) | Search, or paste a DOI to add |
| Search header / footer | {n} matches · See all in Papers → |
| Add preview | Found via Crossref · {venue} · {year} · suggested tags … · **Add to {team}** → ✓ Added to {team} |
| Duplicate | Already shared by {name} · {relative} · Open → |
| Continue reading | CONTINUE READING · Reading list · {n} → · saved {relative} |
| Recs header | RECOMMENDED FOR YOU · Tune → |
| Feed header | LAB FEED · All · Unread {n} · With comments · Browse all → |
| Feed footer | Show {n} more from this week |
| Trending | TRENDING · 30 DAYS · Tags / Authors · last 30 days / previous 30 days |
| Tag volume | TAG VOLUME · papers per week · last 12 weeks · Hover the chart to see a tag |

---

## 9. Open questions

1. **Match %:** show it on recommendation cards? Only if the recommender's score is calibrated enough to trust. If not, drop it and keep only the reason.
2. **"Show more" in the feed:** expand in place, or open `/papers` filtered to this week?
3. **Quick add:** should adding a paper also save it to the adder's reading list, or offer that as a second button?
4. **Topic clusters:** are Maps clusters stable enough to colour papers on Home? If they change between rebuilds, users will see papers change colour.

---

## 10. Acceptance checklist

- [ ] At 1280 × 800 the Lab feed header is visible without scrolling.
- [ ] At 1440, 1920 and 2560 widths, recommendation card edges line up with the column edges of the Lab feed and the rail.
- [ ] The Lab feed card and the Tag volume card end on the same line at all widths ≥ 900px.
- [ ] The reason footers on all visible recommendation cards line up horizontally.
- [ ] Hovering a tag in Trending highlights the same band in Tag volume; the readout numbers match the Trending row.
- [ ] Pasting a DOI shows the preview; pasting a DOI already in the library shows the duplicate state.
- [ ] Mobile (390px): no horizontal page scroll, every tap target ≥ 44px, and the input doesn't trigger iOS zoom.
- [ ] No topic colour on chrome (buttons, nav, headings).
S