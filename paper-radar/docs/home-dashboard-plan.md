# Home dashboard: implementation plan

**Spec:** `docs/dashboard.md` (+ the 1920 and 1280 screenshots). The `.dc.html` design files it cites aren't in the repo, so this plan works from the spec and screenshots.
**Branch:** `dashboard`, off `main` at `fbdfebb`.

## What the spec assumes vs what exists

| Spec needs | Today | Gap |
|---|---|---|
| Icon rail at 900–1359px, shell-width breakpoints | `Layout.tsx` has one switch at `md` (768px): full sidebar or mobile drawer | Layout change that touches **every page** |
| "{n} new papers since your last visit" | nothing tracks visits (only `mentions.seen_at`) | new table |
| Recommendation `reason` + `score 0..1` | `/recommendations` returns `{similarity, post}`; similarity is raw cosine, nothing records *why* | backend work. Tag/author reasons need **follows, which don't exist** |
| Trending tags / authors / tag volume | `team_tags` counts all-time lab tags; no author aggregation | 3 new RPCs |
| Omnibar add mode + duplicate check | `AddPaperDialog` has `resolvePaper` + `findInLab` (by `url_norm` only) | extract into `usePaperLookup`; also match on DOI |
| `/papers?q=…`, `?tag=…`, `?author=…` | Papers keeps filters in `useState`; no URL params; no author filter | Papers reads params; `search_papers` gains `p_author` |
| `topic_cluster` 1–6 per paper | clusters are KMeans per paper set, cached in process; indices shift whenever a paper is added | **no stable id to expose** (see decision 4) |

## Proposed answers to the spec's open questions

1. **Match %: drop it.** `similarity` is uncalibrated cosine (0.0 for the cold-start fallback), so "94%" would claim a precision it doesn't have. Show the reason only.
2. **"Show more": link to `/papers`** (newest first), not expand in place. Home stays one screen, and Papers already has the infinite list.
3. **Quick add: same as today.** Adding doesn't save to the reading list; the preview card's bookmark covers that. No second button.
4. **Topic clusters: not stable enough.** Cluster indices change on every rebuild, so colours would shuffle. For now, feed and recommendation dots use `--ch-off`. The Tag volume chart colours bands by **trending rank** (`--ch-1…6`): that's data colour and needs no clusters. Real topic dots can wait until maps have a persistent topic id.

## Other calls I'd make (tell me if you disagree)

- **"Needs your attention" (unseen @mentions) and "Active discussions" disappear.** The spec doesn't include them. Mentions stay in the bell, and "With comments" covers discussions. If you want mentions on Home, they'd fit as a line under the subtitle.
- **Trending uses lab tags (`paper_posts.tags`),** as the filters and `team_tags` already do, so clicking a tag in Trending finds the same papers in Papers.
- **Reason kinds in v1: `similar_saved` and `similar_read` only.** These come from the engaged paper nearest the recommendation, which the API can compute from embeddings it already loads. `tag` and `author` reasons wait for a follow feature (`profiles.interests` exists but is unused), as does "· you follow" on Trending authors. Cold-start results get no reason line; the footer row keeps its height so footers still line up.
- **Spec hex values (`#0c1118`, `#39434c`, `#2c3743`, `#5b6670`) are dark-only.** I'll map them to tokens (`--bg`/`--surface-2`, `--surface-3`/`--border-strong`, `--faint`) so light mode works.
- **Chart:** hand-rolled SVG (no chart dependency), as the spec describes.

## Phases

Each phase is a commit series on `dashboard`. I'd open **one PR after phase 3** and a second for 4–5. Phases 1–3 need no backend changes beyond the Papers URL params.

**Phase 1: shell and grid**
- `Layout`: measure shell width with `ResizeObserver` and pick a nav mode: full sidebar (≥1360), icon strip with tooltips (640–1359), top bar (<640). The current `md` drawer becomes the <640 case.
- Home grid: N columns from content width (5/4/3/1), subgrid header row, recommendation card width formula, rail stretching to the feed.
- Greeting with a placeholder subtitle until phase 4; Continue reading card with its empty state.
- Check against the layout items of the acceptance checklist at 1280×800, 1440, 1920 and 2560.

**Phase 2: recommendations, lab feed, search**
- New `RecCard` (fixed title/footer heights, 2px top line, ✦ reason slot, bookmark). Fetch 12; arrows page by N cards. Keep the cold-start, waking and error copy.
- Lab feed: day grouping, All / Unread / With comments, unread dot, comment count, avatar, relative time, bookmark. Mobile row variant.
- Omnibar search mode: debounced `usePaperSearch`, combobox a11y, ⌘K, ↑/↓/↵/Esc, "See all in Papers →".
- Papers reads `?q=` and `?tag=` (and `?author=` once phase 3 adds it).

**Phase 3: quick add, trends**
- Extract `usePaperLookup` from `AddPaperDialog` (both use it), with the duplicate check extended to DOI. Omnibar add mode: preview, add, duplicate state, accent ring. The empty-input Add button opens `AddPaperDialog`.
- Migration: `trending_tags(team, days)`, `trending_authors(team, days)`, `tag_volume(team, weeks, tags[])`, plus `p_author` on `search_papers`. Security invoker, pgTAP tests next to `recommendations_test.sql`.
- Trending (Tags/Authors) and Tag volume with shared `hoveredTag`, tap on touch, `role="img"` summary. 10-minute `staleTime`.

**Phase 4: last visit**
- Table `team_visits(user_id, team_id, last_seen_at)` with RLS limited to your own rows, plus RPC `new_posts_since_last_visit(team)`. Home reads the count on mount and writes `last_seen_at` after 10s or on unmount, so the count shown on this visit isn't reset under you.

**Phase 5: recommendation reasons**
- `/recommendations` adds `reason {kind, ref_id, ref_label}` per result: the nearest saved paper, else the nearest read paper, from the vectors `_taste_vector` already loads. Python tests in `tests/test_api.py`.

## Testing

Unit and API tests per phase; pgTAP for the RPCs; `tsc`. A browser pass with `run-atlas` at 390, 800, 1280×800, 1440, 1920 and 2560, working through the spec's acceptance checklist, and a light-mode check.
