# Atlas redesign — implementation plan

_2026-07-13. Sequencing the approved design into shippable PRs._

**Locked decisions (don't relitigate):**
- Positioning: **Territory 2** — _"Every lab has a taste. Atlas gives yours to Claude."_ Copy already shipped ([`atlas-copy-deck.html`](atlas-copy-deck.html)).
- **Saved maps are cut** (user testing). Overview stays; `Share this view` is the only survivor. See the banner on [`MAP_DASHBOARDS_PROPOSAL.md`](MAP_DASHBOARDS_PROPOSAL.md).
- Import is **BibTeX, from Zotero** (confirmed). PDF scrape becomes legacy fallback.
- Design direction: [`atlas-redesign-mockup.html`](atlas-redesign-mockup.html).

**Still open (decide before PR1):** the microscopy identity — fluorophore-cyan
accent + 6-channel data palette + serif display. Everything below assumes yes.
If it's a no, PR1 shrinks to "fix the type scale" and PR2–5 are unaffected.

---

## The one structural fact that shapes everything

`web/src/App.tsx` today:

```tsx
<Route path="/login" element={<Login />} />
<Route path="*" element={<Navigate to="/login" replace />} />   // signed out → everything redirects
```

**There is no public surface.** A signed-out visitor cannot see anything but a
login form. So "add a landing page" is not a new component — it's a **routing
change**, and it's the prerequisite for having anything to market.

---

## PR1 — Foundations: tokens, type, mark

_No behaviour change. Everything after this depends on it._

| File | Change |
|---|---|
| `web/src/index.css` | Replace the palette in `:root` / `.dark`. Token **names** stay identical (`--accent`, `--surface`…), so no component needs touching. Add `--ch1…--ch6` (data channels) + `--r0…--r6` (relevance ramp). |
| `web/src/index.css` | `@font-face` for one self-hosted display serif (subset, woff2, ~30 KB, in `web/public/`). **Not a CDN link** — and not a system stack: it resolves to Iowan on macOS and Georgia on Windows, i.e. a different product per OS. |
| `web/src/components/Brand.tsx` | Replace `lucide` `Compass` with the cell-field mark (inline SVG, ~10 lines). |
| `web/src/routes/Map.tsx` | Delete the local `CATEGORICAL_LIGHT/DARK`, `YEAR_RAMP_*`, `REL_RAMP_*` consts (lines 15–22) — read the new CSS vars instead. Removes a duplicate palette. |

**Risk:** low. The token-name discipline in the existing CSS is the whole reason
this is cheap — thank whoever did that.
**Verify:** `/run-atlas`, eyeball every screen in both themes.

---

## PR2 — Landing page (public surface)

**Routing** (`App.tsx`), the actual work:

```tsx
// signed out
<Route path="/" element={<Landing />} />          // NEW — public
<Route path="/login" element={<Login />} />
<Route path="*" element={<Navigate to="/" replace />} />   // was → /login
```

Signed-*in* users hitting `/` still get the Dashboard — the existing signed-in
branch already owns `/`, so the split is purely on session state.

| File | Change |
|---|---|
| `web/src/routes/Landing.tsx` | **new.** Hero + the sections from the mock-up. |
| `web/src/components/HeroField.tsx` | **new.** The canvas animation — 420 points, noise → 6 clusters, ~2.6 s ease, then ambient drift. Users explicitly liked this; port it as-is from the mock-up. Must honour `prefers-reduced-motion` (render the settled state, no rAF) and pause via `IntersectionObserver` when scrolled away. |
| `web/index.html` | `<title>`, description meta, OG tags. |

**Content** = the approved deck: hero → "it learns by being used" (the taste
weights, from `_taste_vector`) → two readers / MCP → mood board compiles →
"when the postdoc leaves, the taste stays" → CTA.

**Risk:** the canvas is the only real work; it's self-contained and already
written in the mock-up.
**Verify:** load signed-out at `/`, confirm no redirect; throttle CPU and check
the animation degrades; toggle `prefers-reduced-motion`.

---

## PR3 — Connect (the highest-value screen)

The MCP server is **already built and working** — 9 tools in `atlas_mcp/server.py`.
It has **no door in the UI**. This PR is mostly a static page plus two small
backend additions, and it's the only feature a user called _important_ unprompted.

| File | Change |
|---|---|
| `web/src/routes/Connect.tsx` | **new.** Four-step setup guide (the real config: `.mcp.json` with `uv run --directory paper-radar --extra mcp python -m atlas_mcp`; `api/.env` with `ATLAS_EMAIL`/`ATLAS_TEAM_ID`; `/mcp` to verify). Copy-to-clipboard on each block. Troubleshooting `<details>`. **Pre-fill the lab's real `team_id`** — that's the one value a user can't guess. |
| `web/src/routes/Layout.tsx` | Add the `Connect` nav item. |
| `supabase/migrations/` | **new.** `mcp_access` (team-level enable flag, `enabled_by`, `enabled_at`) + `mcp_tool_calls` (audit log: `team_id`, `tool`, `called_at`). RLS: members read; **owner-only** write on `mcp_access`. |
| `atlas_mcp/server.py` | Log each tool call to `mcp_tool_calls`. Refuse if `mcp_access.enabled` is false. |
| `web/src/routes/Settings.tsx` | Per-member "exclude my engagement from the lab's taste signal" toggle. |

**Governance is not optional here.** Connecting exposes *colleagues'* comments,
reactions, and reading history. Owner-enables, members-notified, anyone-can-opt-out,
log-visible-to-all. A researcher will not point a model at unpublished work on a
colleague's behalf — if we get this wrong nothing else matters.

**Risk:** the `atlas_mcp` changes are the first *write* path in a read-only server.
Keep the audit insert best-effort (never fail a tool call because logging failed).
**Verify:** actually run `claude mcp` against a local lab and watch the log populate.

---

## PR4 — Onboarding + BibTeX import

Replaces the PDF scrape as the front door ("quite hacky" — user).

| File | Change |
|---|---|
| `paper_radar/ingest/bibtex.py` | **new.** Parse `.bib` (`bibtexparser`), map entries → `Paper`. **Reuse `ingest/metadata.py`** to resolve abstracts from the DOI — don't write a second metadata path. |
| `api/app.py` | `POST /import/bibtex` → returns a **pre-flight report** (new / duplicate / missing-DOI / unparseable) *without writing*. `POST /import/bibtex/commit` writes. Two-step so the user sees what will happen first. |
| `web/src/routes/Import.tsx` | **new.** Drop-zone → pre-flight table → commit. **The Zotero export how-to lives inline on this screen**, not in a docs site — the user asked for "an explanation of how to get it", and that's the moment they need it. |
| `web/src/routes/Onboarding.tsx` | Rework: create/join lab → **import** → invite. |

Dedupe on `papers.url_norm` (unique) and `doi` (unique) — both already exist.
Keep `ingest/pdf_extract.py` working; demote it to "legacy Teams import".

**Risk:** the highest of any PR here — real parsing of messy third-party `.bib`
files. Unit-test against a genuine Zotero export with the ugly cases (no DOI,
`@misc`, unicode, duplicate keys).
**Verify:** export a real Zotero library, import it, check the counts.

---

## PR5 — Overview polish + the Home/Papers backlog

| Change | Where | Note |
|---|---|---|
| **Share this view** | `Map.tsx` | Serialise filter state → querystring; read it back on mount. The *entire* survivor of the saved-maps idea. ~a day. |
| **Shape-encode themes** | `Map.tsx` | Each cluster gets a glyph as well as a hue. I simulated the palette: under deuteranopia **cyan/magenta** converge (ΔE ≈ 0.04) — hue alone is not safe. |
| **`cold_start` placement bug** | `Dashboard.tsx` | **Real bug, found by running the app.** The explainer is nested *inside* `recResults.length > 0`, so a lab with **zero** recommendations — exactly the new-lab case the message exists for — sees nothing. Lift it out of that branch. |
| Dismissible mentions / mark-as-read | `Dashboard.tsx` | Schema (`mentions.seen_at`, `paper_status`) already supports it; the UI never used it. From the UX review. |
| Sort + multi-filter | `Papers.tsx` | One tag filter is not enough at 425 papers. |
| Settings redesign | `Settings.tsx` | The one screen still on the pre-redesign layout. |

---

## Order, and why

```
PR1 foundations ─┬─► PR2 landing
                 └─► PR3 connect ──► PR4 onboarding + import ──► PR5 polish
```

PR1 first because everything renders through it. Then **PR2 and PR3 are
independent and can go in parallel.**

If you want *value* soonest, do **PR3 before PR2**: Connect is the thing users
asked for, and it works for the labs you already have. If you want the *story*
soonest — a link to send people — do PR2. My call: **PR1 → PR3 → PR2 → PR4 → PR5**,
because a landing page selling an MCP integration that has no UI door is a promise
we can't yet keep.

**Fix the `cold_start` bug in PR1** rather than waiting for PR5 — it's a two-line
move and it's actively wrong today.

---

## Testing

- **Per PR:** `npm run build` (tsc + vite) and `uv run pytest` must pass.
- **`bibtex.py`:** real unit tests against a genuine Zotero export. This is the
  only PR with meaningful parsing logic.
- **Every PR:** drive the app via `/run-atlas` and look at the screen. Two of the
  defects in this plan (the `cold_start` placement, the stale `:8000` server) were
  invisible to the type-checker and the test suite, and obvious within thirty
  seconds of actually using the thing.
- **Before PR2 ships:** the five-researcher test on the mock-up. One round of user
  feedback already deleted a sprint of work.
