# Atlas — maps as living topic dashboards (v2 proposal)

_Senior UX proposal, 2026-07-13. Companion visual: the "Atlas — Map dashboard (Ovarian Cancer)" artifact._

## 0. Why revisit — and what's different this time

The v1 saved-maps proposal (`MAP_DASHBOARDS_PROPOSAL.md`) was **superseded by user testing**:
a researcher called saved maps *"a nice gimmick… the general stats overview and interactive
map of the current prototype seems more practical."*

That verdict was correct **about v1**, and it tells us exactly what to change. v1 saved a
**lens** — a colour/size/filter configuration over the whole corpus. Reopening a v1 map showed
you a scatter you could recreate in fifteen seconds by re-applying the filters. It stored *how
you looked*, and added no information. Of course it felt like a gimmick.

This proposal saves something categorically different: a **subject the lab tracks** — "Ovarian
Cancer", "ECM remodeling" — and every time you open it, it does the reading-and-synthesis work
*for* you. A v2 map is a standing **research radar** for a topic:

- an **interactive t-SNE** of the papers in that topic,
- an **AI summary of recent developments** in it (grounded in, and citing, the lab's papers),
- a **ranked, searchable, filterable list of the important papers** — including *"what I haven't
  read yet"*,
- the **important labs** driving the topic and the **sub-themes** inside it.

None of that is reproducible by re-filtering. The tester found saved *views* pointless and the
live *overview* practical — so v2 keeps the overview exactly as-is and gives the lab **scoped,
synthesized overviews for the units it actually organizes around.** Recall + synthesis + action
— the three things the saved *view* was missing.

## 1. What we keep

The shipped `/map` Overview is the validated core and **does not change**: the whole-corpus
t-SNE (`/overview` → points + LLM-named clusters + stats), the semantic topic lens, colour/size
controls, and click-to-filter stat panels. It becomes the **pinned lab map** — the "everything"
view. v2 adds **topic maps** beside it. We are extending the thing that tested well, not
replacing it.

## 2. The core reframe (one line)

> **A map is not a saved filter. A map is a topic the lab watches, and Atlas keeps it current,
> summarized, and ranked.**

Everything below follows from that sentence.

## 3. What defines a map's membership

A map is a **definition, not a snapshot** (the one good bone from v1: live data, saved intent).
The definition is a **semantic seed** plus light curation:

- **Seed** — a short phrase ("ovarian cancer, HGSOC, platinum resistance"). Membership = papers
  whose embedding is within a relevance band of the seed (cosine via the existing `match_papers`).
  New papers that match join automatically; the map stays current with zero upkeep.
- **Curation (fast-follow, not v1)** — **pin** a must-have paper the seed missed, **exclude** a
  false positive, optionally widen by a tag/cluster/lab rule. A small **"3 new candidates"**
  affordance lets the owner accept/reject drift rather than being surprised by it.

Ship the semantic seed first (it reuses infrastructure that already exists); curation is additive.
Because membership is a query, the map self-updates — which is the entire reason it earns a return
visit.

**Scope: lab-shared by default.** The user framed this as "maps *for the lab*." A lab's Ovarian
Cancer map is a shared asset, not a personal bookmark — so maps are team-scoped and visible to
every member (unlike v1's personal-by-default). Each member still gets their **own** read-state,
so "unread" means unread *for me* on a shared map.

## 4. The map dashboard (`/maps/:id`)

One scrollable page, top = at-a-glance, below = the intelligence. Reading order is deliberate:
*where it sits → what's new → what to read → who & what drives it.*

### 4.1 Identity header
Name ("Ovarian Cancer"), the plain-language definition ("papers near *ovarian cancer · HGSOC ·
platinum resistance*"), and a meta line: `142 papers · +7 this week · shared with Tumour Lab ·
tracked by Ellen`. Actions: **Edit definition**, Share, Duplicate, Delete (owner). The definition
is legible on the page — never hidden state.

### 4.2 Hero — interactive t-SNE of the map's papers
The validated Overview scatter, **scoped to the members**. Points coloured by **sub-theme**
(clusters computed within the subset), sized by engagement; hover → title, click → paper modal;
click a sub-theme hull → highlight + filter the list below. A toggle **"show in full-corpus
context"** dims the rest of the lab's papers behind the highlighted topic, so a PI can see *where
this topic sits in our world* — the atlas metaphor doing real work. Default: scoped, for focus.

### 4.3 What's new — AI summary of recent developments
A short synthesized brief (3–5 sentences or tight bullets) of what's moved in this topic, built
from the **most recent + most relevant** member papers and **citing each claim** with a deep link.
This is the single feature that converts "a filter" into "a tool you open on Monday." Rules:
- **Grounded and cited only** — synthesized strictly from the lab's own papers, never invented
  references (reuses the `draft_related_work` discipline and untrusted-content framing).
- **Honest freshness** — "Summarizing 7 papers added since 12 Jun" + a *Regenerate* affordance;
  cached, not recomputed on every open (cost + trust).
- Degrades gracefully on a thin topic ("only 4 papers here yet — too little to summarize").

### 4.4 Important papers — searchable, filterable, actionable
The heart of the page: a ranked list, default sort **Importance** (relevance-to-seed × engagement
× recency), with **Recency** and **Most-discussed** as alternates. Above it:
- a **semantic search box** ("search within this map"), and
- filter chips: **Unread** (my `paper_status` ≠ read — the killer filter: *"what haven't I read in
  Ovarian Cancer?"*), sub-theme, lab, year, has code/data.

Each row: read-state dot · title · authors · venue·year · engagement summary · a quiet "why it's
here" relevance hint. This is the lab's **reading queue for the topic** — the actionable payoff the
saved view never had.

### 4.5 Important labs & sub-themes (the right rail)
- **Labs driving this topic** — ranked last-authors/groups within the member set (paper count +
  engagement). "Who owns this field, in our corpus" — for citing, following, collaborating. Click
  → filter list + scatter.
- **Themes within the map** — the sub-clusters, LLM-named, with counts and a bar. A zoom-in: the
  corpus has themes; a map has *sub*-themes. Click → highlight scatter + filter list.

Layout: hero scatter + AI summary span the top; below, the important-papers list is the wide
primary column with labs + themes in a narrower rail. Everything cross-filters. Mobile: stacks,
rail becomes collapsible sections.

## 5. IA, routes, and creation

- Nav **Map → Maps** (an atlas is a *collection* of maps). `/maps` = a light gallery: the pinned
  **Overview** card + the lab's topic-map cards (name · mini-scatter thumbnail · `N papers` ·
  `+N new` · a one-line summary snippet) + **New map**.
- `/maps/overview` — today's Overview, unchanged. `/maps/:id` — the dashboard above.
- **Creation is low-friction (the tester's practicality bar):**
  1. **From the Overview's topic lens** — after searching "ovarian cancer" there, offer **"Save as
     map"**. The transient search becomes a standing, valuable map (v1's "saving is promotion"
     bone, now attached to something worth saving).
  2. **From a cluster** — click a theme on the Overview → "Make this a map."
  3. **New map** — one inline input: *"What's this map about?"* → the scoped dashboard renders
     live, name pre-filled, Save. No wizard, no empty preview.

## 6. Feasibility (mostly reuse)

| Piece | Reuses |
|---|---|
| Membership | `match_papers` (semantic) against the seed embedding; config on one `maps` row |
| Scatter + sub-themes | `/overview` layout+clustering, run on the member subset (points already embedded) |
| AI summary | the `draft_related_work` / synthesis path over the map's recent papers (grounded, cited, cached) |
| Important-paper ranking | `recommend_papers`-style relevance × engagement × recency |
| Labs / themes | existing `by_lab` / `by_tag` stats, computed over the subset |
| **Unread filter** | **new-ish:** join `paper_status` per viewer (table exists; points don't carry read-state yet) |

```sql
create table maps (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references teams(id),
  created_by uuid not null references profiles(id),
  name text not null,
  seed text not null,                 -- the phrase; embedded server-side for membership
  config jsonb not null default '{}', -- { threshold|topN, pinned:[], excluded:[], rules:{} }
  ai_summary jsonb,                    -- { text, cited_ids, generated_at, n_papers }
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- RLS: team members read; creator/owner edits. Shared with the lab by default.
```

**Cohesion win:** this dashboard is the in-app home for the six MCP scientist tools just shipped —
the same synthesis Claude does over MCP (`recommend`, `similar`, `novelty`, `lab_digest`,
`draft_related_work`), surfaced per topic for people who aren't in a Claude session. The AI summary
is `draft_related_work` scoped to a map; "important papers" is `recommend`/`similar` scoped to a
map. One capability, two front doors.

## 7. Why this passes the test v1 failed

- The tester rejected a saved **view** (no new information) and endorsed the live **overview**
  (practical). v2 keeps the overview and adds **scoped, synthesized** overviews for the topics a
  lab is organized around. It's the validated mechanics aimed at the lab's actual unit of work.
- The **AI summary** and the **unread filter** deliver recall + synthesis + action — precisely the
  three things a saved view lacked and the reason it felt like a gimmick.
- It makes the product's name true: an *Atlas* is a collection of maps; we finally ship more than
  one, and each is worth keeping.

## 8. Risks & open questions

1. **Membership precision.** Semantic-only membership has false pos/neg. Mitigation: pin/exclude +
   a "review candidates" queue. Ship semantic first; measure precision before over-engineering.
2. **AI-summary trust & cost.** Must be grounded, cited, cached, and cheap — regenerate on demand
   or when *N* new papers land, never on every open. Always show what it summarized.
3. **Overlap with the Overview.** Keep the Overview as the pinned whole-corpus map; topic maps are
   zoom-ins, not competitors. The gallery must make that hierarchy obvious.
4. **Thin topics.** Below ~15 members, show honesty ("a bit thin to summarize") rather than a fake
   dashboard.
5. **Auto-updating membership** could disorient. Surface deltas ("+7 new") and let owners review
   rather than silently mutating the set.

## 9. Open decisions for you

- **Seed vs. curated first?** Recommendation: ship semantic-seed membership in v1 of *this*, add
  pin/exclude curation as the immediate fast-follow.
- **Shared-by-default** for lab topic maps — agree? (I believe yes, given "maps for the lab".)
- **Which lens leads the dashboard** — is the scatter the hero, or should the AI summary sit above
  it for a "brief first, explore second" reading? (Mockup shows scatter + summary side-by-side at
  the top; easy to flip.)
