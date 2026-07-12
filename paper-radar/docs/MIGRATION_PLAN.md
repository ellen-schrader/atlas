# paper-radar → hosted web app: migration plan

Moving from a single-user Streamlit prototype to a **hosted, multi-lab web
application**. The Streamlit UI becomes a React + TypeScript frontend; the
Python domain logic (PDF ingest, metadata enrichment, embeddings, ranking) is
kept and repackaged as a service; persistence and auth move to a hosted
platform so lab members can use the app over the internet.

Status: **planning**. Nothing here is built yet. This document is the thing to
agree on before writing code. It reflects the extraction/enrichment code
already on `main` (see §6).

---

## 1. Goals

A lab shares papers (today via a Microsoft Teams channel). The app should let a
lab:

- **Post papers** — paste a URL, upload a PDF, or bulk-import a Teams channel
  export; the system extracts the real URL and looks up metadata (title,
  authors, abstract, DOI, venue, year, keywords).
- **Browse & search** the papers the lab has posted (full-text first, semantic
  later).
- **Engage** — comment on papers and react to them, and **@-mention** lab
  members on a paper. Comments and reactions are visible to the whole lab; a
  mention notifies the tagged member — it lands on their dashboard and is
  auto-added to their to-be-read list.
- **Discover** — cut through the firehose: **per-user relevance ranking within
  the lab** (what's relevant to *you*, not just what was posted), trends across
  the lab's papers via embeddings, and a dashboard of recommendations, newest
  posts, and a personal to-be-read list. A single lab can post ~500+ papers in
  six months; interdisciplinary cancer research means most aren't relevant to
  any one member, and good ones get lost. Recovering that signal per person is a
  core goal, not a nice-to-have.
- **Describe your focus** — each member keeps a short, editable free-text
  profile — a "USER.md" (e.g. *"an oncologist working on an immunotherapy
  dataset focused on myeloid cells"*). It is embedded and directly shapes that
  member's relevance ranking, and gives useful recommendations from day one,
  before any click history exists. Editing it immediately reshapes their feed.
- **Work online** — accessible to lab members from anywhere, with real accounts.

### Confirmed product rules

- **Papers are a single global corpus, deduplicated** (one row per real paper).
- **A lab only sees papers it has posted.** The global table is never browsed
  directly; visibility is always mediated by the lab's own "posts."
- **Users belong to one or more labs (teams).** All engagement is lab-scoped.

---

## 2. Target architecture

```
┌─ web/  React + TypeScript (Vite) ───────────────────────────┐
│                                                             │
│   supabase-js ───────────────►  Supabase                    │
│     • auth (sign in/up)          ├─ Postgres  (data)         │
│     • CRUD: posts, comments,     ├─ pgvector  (embeddings)   │
│       reactions, read-status     ├─ Auth      (accounts/JWT) │
│     • text + vector search       ├─ Storage   (uploaded PDFs)│
│     • realtime (live comments,   └─ RLS       (lab isolation)│
│       "enriching…" → ready)                                  │
│   fetch /api ────────────────►  api/  FastAPI (Python)      │
└──────────────────────────────────┬──────────────────────────┘
                                    │  reads/writes same Postgres
                                    ▼
┌─ api/ + worker/  Python service — kept for what Python is best at ─┐
│   ingest   PDF/URL → canonical URL → dedup (tracking-strip + DOI)  │
│   metadata arXiv / Crossref / PubMed / Europe PMC / citation-scrape │
│   enrich   LLM: summary, tags, code/data links                     │
│   embed    compute embeddings → write pgvector                     │
│   rank     taste model → recommendations                           │
│   trends   cluster embeddings on a schedule → trends table         │
└────────────────────────────────────────────────────────────────────┘
```

**Division of labour**

- **Supabase owns** auth, the database, lab isolation (Row-Level Security),
  file storage, and realtime. The frontend talks to it directly for all CRUD
  and search — very little bespoke API code.
- **The Python service owns** everything ML/ingest. Metadata resolution is
  network-bound (up to ~10 s per source, several fallbacks), so **posting a
  paper returns immediately** with a pending row and enrichment runs in the
  worker; the UI flips from "enriching…" to ready over realtime.

This keeps the hand-written REST surface tiny and puts the security-critical
rules (who-can-see-what) in the database, not scattered across app code.

---

## 3. Technology choices

| Area | Choice | Status | Why |
|---|---|---|---|
| Database | **Supabase Postgres** | locked | Hosted, relational, `pgvector`, RLS. Replaces SQLite. |
| Vector search | **pgvector** | locked | Embeddings as a column; search is SQL. Replaces FAISS/UMAP files. |
| Auth | **Supabase Auth** (email/password; Microsoft SSO deferred) | locked | Hosted sessions + JWT; integrates with RLS via `auth.uid()`. Retires hand-rolled PBKDF2/session code. §13.4 |
| Frontend | **Vite + React + TypeScript** | locked | Entirely behind auth; a Next.js server tier would be a redundant third backend. §13.3 |
| Server state | **TanStack Query** | locked | Caching/invalidation for an API-driven UI. |
| UI kit | **shadcn/ui (Radix + Tailwind)** | locked | Accessible IDE primitives — `cmdk` palette, data tables, dialogs, toasts — tuned to §4. §13.5 |
| Icons | **Lucide** | locked | Already in use; thin, consistent, professional. |
| API service | **FastAPI** | locked | Reuses the existing Python; async; OpenAPI → typed TS client. |
| Metadata | **existing `ingest/metadata.py`** (stdlib only) | locked | Works today; moves into the service near-verbatim (§6). |
| Embeddings | **hosted API for MVP**, swappable; benchmark SPECTER2/SciNCL | by phase 6 | Per-user relevance leans on embedding quality; pick the flagship model on a benchmark. Sets `vector(N)`. §13.1 |

---

## 4. Design language

The audience is **computational biologists**. The app should feel like a
professional research instrument — closer to an IDE / Linear / Zotero than a
consumer web app. Minimal, information-dense, keyboard-friendly, quietly
styled. The earlier indigo/gradient restyle is **superseded** by this
direction; what carries over is the *infrastructure* (CSS-variable token
system, light/dark switching, the Lucide `icon()` helper), not the playful
palette.

**Principles**

- **Restraint over decoration.** Flat surfaces, 1px hairline borders, no
  gradients or heavy shadows. Color is functional, not ornamental.
- **Density.** The corpus is a **sortable data table** (title, authors, venue,
  year, posted-by, reactions, status), not a feed of large cards. A detail pane
  shows the abstract, links, comments, and reactions. Optional comfortable/
  compact density.
- **Monospace for identifiers.** DOIs, arXiv ids, dates, counts, tags, and
  provenance render in a monospace face — this is what gives the "IDE" read and
  suits scientific identifiers.
- **Keyboard-first.** A command palette (`⌘K`) for search + actions (post a
  paper, jump to a paper, filter by tag); shortcuts for navigation and
  read-status. Comp-bio users live on the keyboard.
- **Dark-first, both first-class.** IDE users default to dark; light mode gets
  equal care (both already exist in the token system).

**Tokens (starting point — to be tuned)**

- **Neutrals:** a slate/zinc scale for backgrounds, borders, and text
  (editor-like grounds: near-white/`#fafafa` light, `#0d1117`-ish dark; hairline
  borders `#e5e7eb` / `#2a2e37`). Neutrals carry a slight cool bias, not pure
  grey.
- **Accent:** a single **restrained blue** (not violet), used sparingly for
  focus, links, and the primary action only.
- **Semantic (muted):** distinct low-chroma chips for **new / unread**,
  **recommended**, and **trending** so state reads at a glance without shouting.
- **Type:** a clean grotesque for UI (Inter / IBM Plex Sans) + a monospace for
  data (JetBrains Mono / IBM Plex Mono).
- **Icons:** Lucide, 1.5px stroke, 16–18px.

---

## 5. Data model

Canonical papers, deduped; lab visibility mediated by `paper_posts`. Column set
reflects what `metadata.py` and `pdf_extract.py` actually produce.

```
profiles       one row per auth user
  id            uuid PK  = auth.users.id
  display_name  text
  interests     jsonb                       -- optional explicit interest tags
  profile_md    text                        -- editable free-text self-description ("USER.md")
  profile_vec   vector(1024) null           -- embedding of profile_md; cold-start taste vector (re-embed on edit)
  created_at    timestamptz

teams          a lab
  id, name, slug (unique), created_by → profiles.id, created_at

team_members   membership (users can be in several labs)
  team_id, user_id, role check in ('owner','member'), joined_at
  PRIMARY KEY (team_id, user_id)

papers         GLOBAL canonical corpus (deduped)
  id             uuid PK
  doi            text unique null           -- preferred dedup key when present
  url            text                        -- canonical (untruncated) URL as found
  url_norm       text unique                 -- normalized dedup key (pdf_extract._normalize_key)
  title          text
  authors        jsonb
  abstract       text
  venue          text
  year           int
  keywords       jsonb                       -- from metadata (author kw / MeSH / subjects)
  tags           jsonb                       -- from LLM enrichment
  code_url       text
  data_url       text
  metadata_source text                       -- arxiv|crossref|pubmed|europepmc|citation_meta|unknown
  embedding      vector(1024) null           -- dim depends on embedding model
  enriched_at    timestamptz null            -- metadata + LLM done  (null = pending)
  embedded_at    timestamptz null
  created_at     timestamptz

paper_posts    a paper posted INTO a lab  (this is the visibility boundary)
  id             uuid PK
  paper_id       uuid → papers.id
  team_id        uuid → teams.id
  posted_by      uuid → profiles.id  null    -- set for in-app posts
  posted_by_label text null                  -- free-text name from a Teams export
  posted_at      timestamptz
  source         text check in ('web','teams_pdf')
  source_pdf     text null                   -- provenance for bulk imports
  page           int  null
  via            text null                    -- 'annotation' | 'text'
  note           text null
  UNIQUE (paper_id, team_id)                  -- a lab posts a given paper at most once

comments       lab-scoped: id, paper_id, team_id, author_id, body, created_at
reactions      lab-scoped emoji: … UNIQUE (paper_id, team_id, user_id, emoji)
paper_status   per-user read state (powers "to be read"):
               user_id, paper_id, team_id, status check in ('to_read','reading','read'), updated_at
               PRIMARY KEY (user_id, paper_id, team_id)
mentions       @-mention of a member on a paper (notifies them):
               id, paper_id, team_id, mentioned_user → profiles.id, mentioned_by → profiles.id,
               comment_id null → comments.id, created_at, seen_at null
trends         computed clusters per lab: id, team_id, label, description, paper_ids jsonb, computed_at
```

Notes:

- **Dedup:** prefer `doi` when the resolver returns one; otherwise `url_norm`
  (the tracking-stripped, param-sorted key `pdf_extract.py` already computes).
  The same real paper posted by two labs → **one** `papers` row, **two**
  `paper_posts` rows; enrichment/embedding happen once.
- **Attribution:** a Teams-imported post carries a free-text `posted_by_label`
  (e.g. "Ellen Schrader") + `posted_at`, which may not map to a registered user;
  in-app posts set `posted_by`. Reconciling labels → accounts is a later nicety.
- The frontend browses **`paper_posts` joined to `papers`**, never `papers`
  alone — that is what enforces "a lab only sees what it posted."
- **Mentions:** creating a `mentions` row also upserts
  `paper_status(mentioned_user, paper_id, team_id, 'to_read')` — *only if the
  user has no status yet*, so a mention never overwrites something they've
  already read or started. This is done in a DB trigger (or the service) so the
  invariant can't be bypassed by a client. The mentioned user's dashboard reads
  unseen mentions; marking one seen sets `seen_at`.

---

## 6. Ingest pipeline & provenance (from `main`)

The extraction code already on `main` is production-grade and moves into the
service with little change:

- **`ingest/pdf_extract.py`** — pulls URLs from Teams-exported PDFs via link
  annotations (untruncated hrefs) + a text-regex fallback, dedupes on a
  normalized key (lowercases host, drops `www.`, strips `utm_*`/tracking params,
  sorts the rest), and attributes each URL to the nearest Teams poster
  stamp/timestamp by vertical position. Produces `ExtractedURL(url, source_pdf,
  page, via, posted_by, posted_at)`.
- **`ingest/metadata.py`** — `fetch_metadata(url)` returns `PaperMetadata(url,
  title, authors, venue, year, doi, abstract, keywords, source)` by trying, in
  order: arXiv API → Nature-DOI/Crossref → DOI/Crossref → PubMed → landing-page
  citation-tag scrape (Highwire/Dublin Core/OpenGraph/JSON-LD) → Europe PMC
  abstract backfill. **stdlib-only** (urllib), fully defensive, with a
  `network=False` mode for tests.

**Two ingest paths, one funnel:**

1. **In-app posting** — user pastes a URL or uploads a PDF → create `papers`
   (or attach existing) + `paper_posts(source='web', posted_by=<uid>)` →
   enqueue metadata + embedding in the worker → realtime "enriching… → ready".
2. **Bulk Teams import** — one channel export (folder of PDFs) → many
   `ExtractedURL` → dedup into `papers` + `paper_posts(source='teams_pdf',
   posted_by_label=…, posted_at=…)` for that lab.

**Known gap:** publisher bot-walls (Elsevier / Cell / ScienceDirect) block
server-side scraping; those return a URL-only record and rely on LLM enrichment
or manual metadata. Zotero avoids this by reading through the user's logged-in
browser — a future option is a browser-extension/user-supplied metadata path.

---

## 7. Security model (Row-Level Security)

RLS is the backbone; the app never hand-filters by team.

```sql
create policy "members read their labs' posts"
  on paper_posts for select
  using (team_id in (select team_id from team_members where user_id = auth.uid()));

create policy "members post into their labs"
  on paper_posts for insert
  with check (team_id in (select team_id from team_members where user_id = auth.uid()));
```

- `paper_posts`, `comments`, `reactions`, `paper_status`, `mentions`, `trends`:
  readable/writable only for teams the user belongs to (you can only @-mention
  members of the same lab).
- `papers` (global): selectable only if the user's lab has a post for it
  (`exists (select 1 from paper_posts p where p.paper_id = papers.id and p.team_id in (…))`).
  Writes to `papers`/`embedding` are **service-role only**.
- The **Python service uses the service-role key** (bypasses RLS) to write
  canonical papers/embeddings; all user traffic is anon/JWT and bound by policy.

---

## 8. Repository layout

```
paper-radar/
  web/                     React + TS (Vite, shadcn/ui)          [new]
    src/{routes,components,lib,hooks}
  api/                     FastAPI service                       [new shell]
    paper_radar/           ← existing package moves here, mostly intact
      ingest/ enrich/ embed/ taste/ models.py …
    app.py                 routes (post-paper, ingest, ML)
  worker/                  scheduled jobs (metadata, embed, trends, recs) [new]
  supabase/                migrations + RLS policies + seed              [new]
    migrations/*.sql
  docs/MIGRATION_PLAN.md
```

The current Streamlit app stays until the React app reaches parity, then is
removed. The `theme.py` token *system* and Lucide helper are reused; the palette
is re-tuned to §4.

---

## 9. Supabase setup (no project yet)

1. Create a Supabase org + project (region near the lab).
2. Enable the **pgvector** extension.
3. Capture keys: project URL, `anon` key (frontend), `service_role` key (Python
   service only — never shipped to the browser).
4. Configure Auth: email/password; site + redirect URLs. (Microsoft SSO is
   deferred — see §13.4.)
5. Manage schema as SQL migrations in `supabase/migrations/` via the Supabase
   CLI (reproducible, not hand-clicked).
6. Storage bucket for uploaded PDFs with a lab-scoped access policy.

---

## 10. Phased roadmap

Sizes rough (S/M/L). Phases 2–3 are the foundation — do them carefully first.

1. **Scaffold (S)** — Supabase project; `web/` + `api/` shells; env/secrets; CI.
2. **Schema & RLS (M)** — §5 tables as migrations; pgvector on; §7 policies +
   policy tests. *A correct, isolated DB before any UI.*
3. **Auth & teams (M)** — Supabase Auth flows in React; create/join lab; the
   editable free-text "USER.md" profile (embedded for ranking once phase 6 lands).
4. **Ingest (M)** — move `pdf_extract.py` + `metadata.py` into the service;
   both ingest paths (§6); "post a paper" UI; async enrichment + realtime.
5. **Core app (L)** — corpus table, paper detail pane, full-text search,
   comments, reactions, **@-mentions** (notify → dashboard + auto-TBR),
   read-status (TBR). Streamlit UI → React, styled per §4.
6. **Embeddings & semantic search (M)** — worker → pgvector; "find similar" +
   semantic search, scoped to the lab's posts. Benchmark a scientific embedding
   model here (§13.1).
7. **Dashboard & personal relevance (L)** — per-user "For you" relevance ranking
   *within* the lab (the firehose filter: reactions/read-status/interests ×
   paper embeddings), papers you were @-mentioned in, newest posts, to-be-read,
   trend clusters.
8. **Deploy & harden (M)** — frontend host; Python service host; scheduled jobs;
   backups; rate limits; monitoring.

*Follow-on (post-MVP):* **External discovery radar** — poll arXiv/bioRxiv/PubMed
for new work matching lab/user taste (§13.2). Its own milestone: needs the taste
model and external-feed ingestion.

---

## 11. Reuse map

- **Kept, moves to `api/`/`worker/` near-intact:** `ingest/pdf_extract.py`,
  `ingest/metadata.py` (stdlib-only — trivial to lift), `embed/*`,
  `enrich/agent.py`, `taste/*`, and most `models.py` field definitions
  (retargeted SQLite → Postgres).
- **Replaced:** `db.py`/`store.py` (→ Supabase), `auth.py` (→ Supabase Auth),
  Streamlit `app/*` (→ React). `theme.py` token system + Lucide helper reused,
  palette re-tuned (§4).
- **New:** FastAPI routes, React app, SQL migrations + RLS, pgvector usage,
  scheduled worker.

---

## 12. Environments & deployment

- **Local:** Supabase CLI (local stack) or a dev project; Vite dev server
  proxying `/api` to FastAPI; `.env` per app.
- **Prod:** Supabase (managed) + frontend on a static host + Python service on a
  container host (RAM for local embeddings, or a hosted embedding API to avoid
  that). Migrations run in CI on deploy.

---

## 13. Decisions

Resolved after debate. Four are locked; two stay data-dependent (decide by the
noted phase).

1. **Embeddings — hosted API (Voyage/OpenAI) for the MVP, behind a swappable
   interface; benchmark a scientific model (SPECTER2/SciNCL) before building
   relevance.** *Decide by phase 6.* Quality now matters *sooner*, because
   per-user relevance (#2) is near-term and leans directly on embedding quality
   — generic tags won't capture cross-disciplinary relevance. The benchmark
   winner sets `vector(N)`; swapping later is a re-embed job, cheap because of
   the interface.

2. **Recommendations — three tiers, in priority order:**
   - **Per-user relevance *within* the lab — near-term, high value (build
     first).** With ~500+ papers posted per lab in six months and cancer
     research spanning many disciplines, most papers aren't relevant to a given
     member and the good ones get lost. Rank each lab's recent/unread papers
     *per user* by similarity between their taste signal and paper embeddings.
     This is the primary recommendation feature — a firehose filter, not a
     glorified TBR sort.
   - **External discovery — north-star, follow-on.** Poll arXiv/bioRxiv/PubMed
     for new work matching lab/user taste. Its own milestone (taste model +
     external feeds); leaks nothing about other labs.
   - **Cross-lab ranking — not built** (soft leakage + cold-start).

   *Taste signal* = a blend of (a) the member's **editable free-text profile**
   (`profile_md` → `profile_vec`, e.g. *"oncologist working on an immunotherapy
   dataset focused on myeloid cells"*), embedded into the same space as papers,
   and (b) behavioural signal — reactions, read-status, comments, @-mentions,
   `Label` judgements — via the existing `taste/` model. The embedded profile
   gives relevant ranking on day one (cold-start), before any click history, and
   editing it immediately reshapes the feed.

3. **Frontend — Vite SPA. Locked.** The app is entirely behind auth (no
   SSR/SEO value), Supabase+RLS suits direct client access, and FastAPI already
   covers privileged server logic; a Next.js server tier would be a redundant
   third backend.

4. **Auth — email/password only for now; Microsoft SSO deferred.** SSO depends
   on an Entra app registration and institutional-IT/admin consent, which is
   slow; we are **not** starting that now. Supabase makes adding the Microsoft
   provider later a config change, not a rearchitecture, so nothing is lost by
   deferring. Email/password also covers external collaborators regardless.

5. **UI kit — shadcn/ui (Radix + Tailwind). Locked.** The IDE character *is*
   the interactive components (⌘K palette, data table, dialogs, keyboard menus);
   Radix gets their accessibility right. Tuned to §4 tokens so it doesn't read
   generic. Pairs cleanly with Vite.

6. **Poster-label → account reconciliation — later**, via a "claim your
   imported posts" flow. The schema already supports it (`posted_by` nullable +
   `posted_by_label`), so deferring is free — and it falls out near-automatically
   if SSO is added later (Entra display name ↔ Teams label). Otherwise a manual
   "claim" flow. Linked to #4.

---

## 14. Risks

- **RLS mistakes leak data across labs.** Mitigate: policy tests in phase 2 (a
  member of lab A gets zero rows from lab B) before any UI.
- **SQLite → Postgres type drift** (JSON, datetimes, enums). Mitigate: port
  models early; test round-trips.
- **Metadata latency / bot-walls.** Mitigate: always async in the worker; show
  pending state; accept the publisher-bot-wall gap (§6) and allow manual/LLM
  fill.
- **Embedding hosting cost/ops.** Mitigate: decide §13.1 early.
- **Prompt injection via user free-text.** The `profile_md` ("USER.md"),
  comments, and post notes are untrusted input. Using them only for *embedding*
  (ranking) is safe. But if any of them is ever fed to an LLM — enrichment,
  generated summaries, "explain this recommendation" — it becomes an injection
  vector (e.g. a profile that says "ignore instructions and …"). Mitigate:
  prefer embedding-only for user text; when an LLM must read it, isolate it as
  clearly delimited, untrusted *data* (never instructions), don't grant that
  call tools/side-effects, and keep authoritative instructions in the system
  prompt. Note that abstracts scraped from the web (§6) are untrusted for the
  same reason.
- **Scope creep** (dashboard/trends are large). Mitigate: ship phases 4–5 as a
  usable app first; treat 6–7 as follow-ons.

---

## 15. Immediate next steps

1. Confirm **open decisions** §13 (at least embeddings + UI kit).
2. Stand up the **Supabase project** (§9) and scaffold the repo (§8).
3. Land **phase 2** (schema + RLS + policy tests) — the foundation.
