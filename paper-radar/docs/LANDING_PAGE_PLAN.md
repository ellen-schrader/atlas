# Landing page redesign — plan (rev 2)

Status (2026-10-18): **PR A open as #152; PR B built on branch `landing-page`, awaiting review.** Replaces rev 1 (the E+F direction).

- Approved design: **G** on the canvas <https://claude.ai/artifact/Cw3sNQwvsLZKkr1HoJTtMh>
  (boards "G — Atlas, slide-glass (light)" and "G — Atlas, imaging (dark)").
- Legal text: `docs/LEGAL_PAGES_DRAFT.md`.

Cost: **$0/month**. Everything is static frontend on Vercel. The fonts are self-hosted, and
the page makes no API calls.

## What we're building, in one paragraph

A landing page for academics and the person in a lab who signs up first, often not the PI.
It says what Atlas is in one sentence: *a shared paper library that gives Claude your lab's
judgment*. Then it makes the case with real evidence:

- the growth of PubMed;
- search by meaning, with real results;
- the same question put to Claude with and without the lab's library;
- how it works;
- what the lab controls;
- who makes it.

The design uses Atlas's own identity: the AtlasMark, the slide-glass and imaging grounds,
the fluorophore teal, and a new typeface, **Schibsted Grotesk**, which replaces Source Serif
4 across the whole app.

## Decisions already made

| Topic | Decision |
|---|---|
| Typeface | Schibsted Grotesk everywhere: landing page, app UI, wordmark. No serif. Free (OFL), self-hosted. |
| Headline | Product first: "A shared paper library that gives Claude your lab's judgment." |
| Sign-up | Open, free during beta. One primary action: **Create your lab**. |
| Claude | The hosted connector is live (#139, #141): "Add Atlas as a connector in Claude." |
| Voice | "Your lab" / "the lab owner", never "the PI". Short copy, at most one sentence of body text per section. |
| Proof | Named maker: "Ellen Schrader, a PhD student". No usage numbers. Beta tag. GitHub link with the GitHub mark. |
| Lab name | Never shown ("Ali Lab" stays out). Papers are real and approved; the lab is anonymous. |
| Theme | Follows the system setting, with the toggle kept. |
| Motion | Only where it explains something; plays once on scroll; off under `prefers-reduced-motion`. |
| Film | Not mentioned yet; a later step. |

## The page, section by section

| # | Section | Content | Motion |
|---|---|---|---|
| 1 | Nav | AtlasMark + "Atlas" + Beta tag · Sign in · **Create your lab** · theme toggle | — |
| 2 | Hero | H1; "Keep your group's papers in one place. Let Claude answer from them."; CTA + "Free during beta"; the 5 approved papers in the real `PaperListRow` style, with the Preprint badge | Row hover only |
| 3 | Volume | "1.7 million papers were added to PubMed in 2025." / "More than three times as many as in 2000."; bar chart 2000–2025; source link | Bars grow once, then the 1.7M label |
| 4 | Find it again | "Search by meaning" (`immunosuppressive macrophages` → 4 real results, "myeloid" and "M2" marked) and "More like this" (Xenium paper → 4 real results) | Query types in, results stagger in, marks appear |
| 5 | Same model, same answer | Dark band. Platform question: *Claude on its own* vs *Claude with your lab's Atlas* (cites Cervilla, Bilous, Chen) and "Example answer…" caption | — |
| 6 | How it works | Add papers · Atlas tidies up · Connect Claude, each with a small product image | — |
| 7 | Your lab decides | "Your lab decides what Claude can see." Off until you turn it on · Read-only · Every request logged · Hosted in Europe | — |
| 8 | About | Maker line + GitHub link (mark) | — |
| 9 | Close | "Start with the papers you have." Create your lab · Sign in | — |
| 10 | Footer | "Atlas is in beta and provided as is." · Privacy · Terms · Report an issue (mark) | — |

The canvas file `Atlas.dc.html` is the reference for copy, spacing and order. The values
below are the ones that need care when porting.

## PR A — typeface and colour tokens (app-wide)

Do this first: it touches every screen and should settle before the landing page builds on
it.

1. **Self-host Schibsted Grotesk.**
   - Download the variable woff2 (weights 400–700, Latin subset) into `web/public/fonts/`.
   - Add its OFL licence to `public/fonts/LICENSE.txt` and to `THIRD_PARTY_NOTICES.md`.
   - Add an `@font-face` with `font-display: swap`, and preload it in `index.html`.

   The CSP allows `font-src 'self'` only, so no Google Fonts.
2. **Tokens in `index.css`.**
   - `--font-sans`: `"Schibsted Grotesk", ui-sans-serif, system-ui, …`.
   - `--font-serif`: point it at the same family for now. That changes nothing visually in
     code and avoids a 46-site edit in this PR.
   - Then replace the `font-serif` classes (46 uses in 21 files) with `font-sans` plus the
     heading weights. Mechanical, but each heading gets checked for weight, and tracking:
     the serif was 600, the grotesk wants 700 at display sizes with `--tracking-tight`.
   - Remove the Source Serif 4 `@font-face` blocks and font files.
3. **Accent contrast (light theme).**
   - `--accent` `#0e8e8a` is 4.0:1 for white text (just under 4.5:1), used by about 20 `bg-accent
     text-accent-fg` buttons. Move light `--accent` to `#0a6e6b` (6.1:1 on white, 5.4:1 on
     `--bg`) and `--accent-weak` to match.
   - Data channels (`--ch-1` and the ramps) stay as they are: they colour data, not chrome.
   - Dark theme is unchanged, since `#2fd4cf` on `#04100f` already passes.
4. **Wordmark.** `Brand.tsx` drops `font-serif`; "Atlas" is set in Schibsted 700 at
   tracking −0.02em, as on the canvas.

**Check:**
- `npm run typecheck && npm run build`.
- Screenshots of Dashboard, Papers, a paper page, Settings and Connect, light and dark,
  before and after, attached to the PR.
- No CSP errors in the console.

**Risk:** headings reflow. The sans-serif is wider than Source Serif 4 at the same size, so
look for truncation in cards and the sidebar.

## PR B — landing page, and About / Privacy / Terms

1. **Rebase `landing-page` onto `main` first.** The branch predates the connector PRs
   (#139, #141) and App.tsx has moved.
2. **Components** in `web/src/components/landing/`, ported from the canvas:

   | Component | What it renders |
   |---|---|
   | `HeroPaperList` | Reuses the `PaperListRow` styles and `PreprintBadge`, not a copy. Static data, no queries. |
   | `PubMedChart` | Plain divs (26 bars), one series, no legend. Native `title` tooltips plus an `aria-label` summary and a visually hidden data table. The data is a constant with its source comment. |
   | `FindAgain` | The two panels and the typing demo. |
   | `SameQuestion` | The dark band. |
   | `HowItWorks` | The three steps. |
   | `LabControls`, `About` | The two short sections. |

   `Landing.tsx` composes them. All copy is literal in the components.
3. **Motion.** One small hook, `useInViewOnce(ref, { threshold: 0.35 })`, built on
   IntersectionObserver and returning `played`.
   - CSS keyframes live in `index.css`, under `@media (prefers-reduced-motion: no-preference)`.
   - The default render is the final state; JavaScript only arms the hidden starting state.
     So nothing is invisible without JS, or in a screenshot or crawler.
   - No animation library.
4. **Remove** `HeroField.tsx` (only Landing uses it).
5. **Legal and About pages.**
   - New routes `/about`, `/privacy` and `/terms`, reachable signed in **and** signed out:
     added to both `<Routes>` trees in `App.tsx`, through one shared `PublicPage` layout
     (nav + footer + a prose column).
   - Text from `LEGAL_PAGES_DRAFT.md`, with the `[BRACKETS]` filled. Contact:
     `hello@labatlas.app`.
   - **Blocked on you** (see Open items): the forwarder working and
     your review.
6. **Meta.** `index.html`:
   - `<title>Atlas — a shared paper library for research groups</title>` and a new
     description;
   - remove the old "every lab has a taste" `og:title`/`og:description`;
   - add an `og:image`: a 1200×630 PNG of the hero, so links pasted into Slack and Teams get
     a proper preview card.
7. **Links.**
   - "Create your lab" → `/login?mode=signup`, "Sign in" → `/login`;
   - "Code and issues on GitHub" → the repo;
   - "Report an issue" → `/issues`;
   - the PubMed source → the PubMed query used for 2025.

**Check:**
- Typecheck and build.
- With the `run-atlas` skill, signed out:
  - 1440 px and 390 px wide, light and dark, plus reduced motion on;
  - every section screenshotted onto the PR.
- Signed in, `/` is still the Dashboard and `/privacy` still opens.
- Keyboard: tab through every link and button. All are real `<a>`/`<button>`, with focus
  rings.
- Lighthouse accessibility ≥ 95 on `/`.
- No CSP errors.
- Then `/code-review high`, fixing what it finds before calling the PR ready.

## PR C — delete account (before opening sign-up wider)

The Privacy draft promises deletion on request within 30 days. That's fine by hand at two
labs, but it doesn't scale.

- Add a "Delete my account" control in Settings: a confirm dialog, then a server-side route
  that removes the user from their labs and deletes the auth user.
- The user's posts stay, attributed to "a former member", matching the draft.
- Needs a test that a deleted user's sessions and connector tokens stop working.

Separate PR; not needed to ship A or B.

## Not in scope

- The product film (later; the page has no slot for it yet, by choice).
- Exposing save, reaction and comment counts to the connector. The page no longer claims
  Claude sees them; it only shows lab notes, which `get_paper` returns.
- Renaming or restyling the map and mood board.

## Open items for you

1. **Contact email:** `hello@labatlas.app` via free ImprovMX forwarding. Set it up before PR B ships.
2. **Legal review:** a qualified read of Privacy and Terms; your university's and funder's
   policy on side projects; the ICO data protection fee self-assessment.
3. ~~Resend region~~: EU (Ireland), from the `rsend-euw1` DNS record. Done.
4. **Go-ahead to start PR A.**
