# Suggestions page — feedback round 1 (#164, PR #173)

Ellen's feedback, 2026-10-24, and what I propose for each. Ordered roughly by
size, smallest first. Items 1–3 are web-only and can go into #173. Items 4–6
change the backend and should be a follow-up PR on top of it.

## 1. Icon

`Radar` is abstract, and it reads as "Atlas / paper-radar" rather than "your
searches". `Bell` is taken by notifications.

**Proposal:** `ScanSearch` (a magnifier inside a viewfinder: "a search that
keeps looking"). Use it in the nav, the empty state and the dialog header.
Fallbacks: `Telescope`, `Inbox`.

## 2. Copy

The tone is mostly fine, but it explains the plumbing (sources, "only you see
this", where imports go) before the benefit, and it repeats itself across the
header, the empty state and the dialog. Proposed rewrites:

| Where | Now | Proposed |
|---|---|---|
| Nav label | Suggestions | **Search alerts** (people know "PubMed alerts"; "Suggestions" is easy to mix up with Discover) |
| Nav hover | New papers from your saved PubMed, bioRxiv and arXiv searches | Your saved searches, run every week |
| H1 | Suggested papers | Search alerts |
| Subtitle | New papers from your saved searches on PubMed, bioRxiv/medRxiv and arXiv, every week. Only you see this list; what you import goes to {lab}'s library. | New papers matching your searches, every Monday. Add the good ones to {lab}'s library and dismiss the rest. Only you see this list. |
| Empty title | Follow a topic, get the new papers every week | Never miss a paper on your topic |
| Empty body | Save a search — your PubMed alert string works as it is — and Atlas runs it on PubMed, bioRxiv/medRxiv and arXiv once a week. You pick which papers go into the library. | Paste a PubMed search or type a few keywords. Every week Atlas checks PubMed, bioRxiv, medRxiv and arXiv and lists what's new here. |
| Section heading | N waiting for you | N new papers |
| Up to date | You're up to date. Your searches run once a week, and anything new the lab doesn't have yet will appear here. | You're all caught up. New papers will show up here after the next weekly run. |
| Row button | Import | **Add to library** (Import sounds like a file upload) |
| Search status | Runs within a day | First run starting… / Next run {day} |
| Dialog title | New saved search | New search alert |
| Dialog intro | Runs once a week on what's new. What it finds is suggested to you alone; the papers you import go to the lab's library. | (drop it: the page already says this) |
| Query help | Paste your PubMed search as it is, or type keywords. AND, OR, NOT, brackets, "quoted phrases", a trailing * and tags such as [tiab] or [au] work everywhere; PubMed-only filters like [pt] apply on PubMed alone. | Paste a PubMed search or type keywords. AND, OR, NOT, "quoted phrases", brackets, `*` and tags like [tiab] work on every source. ▸ More (folds open the PubMed-only detail) |
| Test box | See what it would have found in the past week. | Preview last week's results |

The weekday needs checking against the job's schedule; if it isn't fixed,
"after the next weekly run" stays.

## 3. Grouping by search, with your own priority order

**Today:** one list, newest first, with a filter chip per search. With several
searches, a high-priority search's papers get buried under a noisy one's.

**Proposal:**
- Searches get an order. Up and down arrows on each row in "Your searches"
  (no drag and drop, so it stays accessible and simple), stored in a new
  `position` column.
- The list of papers is **grouped by search, in that order**. Each group has a
  header (name, count, "Add all / Dismiss all") and can be collapsed. The
  chips go, because the groups replace them.
- A paper found by two searches shows up once, under the higher one, with
  "also in {other}".

Backend: one small migration (`saved_searches.position smallint`), `PATCH`
accepts it, the list orders by it. Today `search_suggestions` keeps only the
*first* search to find a paper; "also in" needs a small link table, or I can
drop that line for now.

## 4. Narrowing arXiv to biology

Most "flow matching" hits are cs.LG/cs.CV papers. The arXiv API filters by
category with `cat:`, and that matches cross-lists too, so a q-bio filter keeps
the cs.LG papers that are cross-listed to q-bio.BM.

**Proposal:** under the arXiv chip in the dialog, an "arXiv subjects" choice
that only appears when arXiv is ticked:

- **Biology** (the default for new searches): q-bio.\* (all 10 subcategories)
- **Biology + ML**: q-bio.\* plus cs.LG, stat.ML, but cs.LG/stat.ML only when
  they are *also* cross-listed to q-bio or physics.bio-ph. That is the
  "flow matching for proteins, not for pianos" case.
- **Everything**: today's behaviour
- **Custom…**: a text field for category codes (e.g. `q-bio.GN cs.LG`)

Stored as `saved_searches.arxiv_categories text[]` (empty = everything) and
ANDed onto the rendered query in `to_arxiv`'s caller. I'd also allow a
`[cat]` tag in the query itself (`flow matching AND q-bio[cat]`) for people
who prefer typing, which is ignored on PubMed and bioRxiv.

The same idea applies to bioRxiv/medRxiv: `rxiv_feed` already stores
`category` (e.g. "bioinformatics", "cancer biology"), so a subject filter there
is cheap. I'd do arXiv first and add bioRxiv only if you want it.

To check during implementation: whether `cat:q-bio*` works as a wildcard (the
sandbox blocked network, so I couldn't test it). If not, the 10 codes are
OR'ed explicitly.

## 5. Sorting by relevance

The ranking itself is not the expensive part. The constraint is getting
**embeddings** for the candidates.

**How it would work:**
1. When the weekly job files candidates, it embeds each new one (title +
   abstract) with Voyage, the same model as the library. It stores the vector
   on `search_candidates`, which is shared, so each paper is embedded once
   however many people get it.
2. Each person's taste vector already exists (`api/taste.py`: profile +
   followed tags + what they've posted, saved and reacted to; Discover uses
   it). Score = cosine(candidate, taste).
3. Within each search group (item 3), sort by that score. Add a "Newest /
   Most relevant" toggle. Papers below a threshold fold into "N less likely
   matches". That also hides the piano papers, even before the arXiv filter.

**Cost:** tokens are negligible, about 300 per paper, so roughly 1,000 papers a
week comes to about 0.3M tokens. That is well inside Voyage's free 200M, so
**$0/month**. The real limit is the free tier's **rate** (4 texts per request,
3 requests a minute, see #171): 1,000 papers take about 80 minutes of the
weekly job. That's fine for a weekly batch, because it runs in the background.
If the volume grows, adding a card to Voyage lifts the rate limit, and the free
tokens still apply.

**What this does not cover:** the *Test query* preview. Embedding 60 papers
live would take about 5 minutes on the free rate limit. The preview stays
newest first, but the arXiv filter (item 4) fixes most of its noise.

Cheaper alternative: lexical scoring (title match > abstract match). It costs
nothing and needs no job time, but it's weak: every hit already matches the
query, and it doesn't know what *you* care about. I don't recommend it.

## 6. Suggested searches when you have none

**Proposal:** below the empty state, 3 or 4 cards: "Searches you might want",
each with a name, the query, and where it came from ("from tags you follow",
"from papers you've shared"). **Use this** opens the dialog pre-filled, so you
can test and edit before saving. Nothing is saved without a click.

Two ways to generate them:

- **A. From tags (free, deterministic):** the tags you follow
  (`profiles.interests`) and the most common tags on papers you posted or
  saved. Each becomes `"tag"[tiab]`, and close tags are OR'ed together. This
  runs instantly with no API calls. The queries are plain but correct.
- **B. Drafted by Claude from your profile:** send `profile_md` + those tags to
  Haiku and ask for 3 PubMed-syntax queries with names. This gives better
  queries (synonyms, MeSH, sensible ANDs). It costs about $0.002 per person,
  cached until the profile changes, so cents per month.

**Recommendation:** ship A first, because it works for everyone with tags.
Add B as a "Draft from my profile" button for people with a written profile.
If someone has neither, fall back to the lab's top tags. I'd also show the
cards (collapsed) when someone already has searches, not only when they have
none.

## Suggested order

1. **PR #173 (web only):** icon, copy, grouping by search (without
   reordering).
2. **Follow-up PR (backend + web):** `position` + reorder, arXiv subjects,
   suggested searches (A), one migration.
3. **Follow-up PR:** relevance (embeddings in the weekly job, sort toggle,
   "less likely" fold), then the Claude-drafted searches (B).

## Decisions (Ellen, 2026-10-24)

- Keep the name **Suggestions** (h1 "Suggested papers"). The row button is just
  **Add** (with the + icon).
- Suggested searches are the most wanted part: phrasing a query and the
  number of options were overwhelming. So the dialog gets simpler too:
  keywords first, PubMed syntax and source options folded away.
- arXiv: **Biology** is the default for new searches, but the other options
  stay available. Existing searches keep "Everything".
- A paper found by two searches shows up **under both**. Adding or dismissing
  it in either removes it from both. It is one suggestion, linked to several
  searches through a new `search_suggestion_searches` table.
- Relevance on Voyage's free tier is fine: about an hour of job time a week.
