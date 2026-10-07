# Editing paper metadata — plan

Status: proposed. The `⋯` post menu it builds on shipped in #112
(`web/src/components/PaperDetail.tsx::PostMenu`).

## Why

The resolver gets papers wrong in ways no amount of resolver work will fix. Four
publisher gaps were closed in #107–#110 (Elsevier PIIs, JCI, OUP, Lancet), and
the one link still sitting in `inbound_unresolved` — a JAMA article — has **no**
deterministic route: Cloudflare-walled to a server, no `alternative-id` in
Crossref, and an article number unrelated to its DOI
(`2847987` ↔ `10.1001/jama.2026.4634`). For papers like that, a person typing
the title is the only answer there will ever be.

Today the only way to correct a paper is to re-add its URL and let
`app.py::_repair_untitled` adopt what you type — which works only when the title
is *null*, and is an odd thing to have to discover.

## What makes this harder than adding a form

**`papers` is global and deduped.** One row serves every lab that posted that DOI
or URL — that is the entire point of `url_norm` and the casefolded `doi`. An edit
is therefore an edit for everyone. The schema has no member `UPDATE` grant on
`papers` (`20260711163827_rls.sql` grants `select` only); that is not an
oversight, it is the question nobody had answered.

**The resolver re-reads papers.** `_repair_untitled` backfills on every re-add,
and `api/backfill_metadata.py` rewrites fields from Crossref. Without a flag,
**the next backfill silently overwrites a human correction** — and because both
run in the background, nobody finds out.

## Permissions

To start: in a lab that has posted this paper, the caller must be the **poster**
of that post or an **owner** of that lab. The same rule as removal, so there is
one mental model for "acting on a record other people share". It is also already
the rule the UI gates the `⋯` menu on (`PaperDetail.tsx`:
`canDelete = post.posted_by === userId || role === "owner"`).

```sql
exists (
    select 1 from public.paper_posts pp
     where pp.paper_id = :paper
       and public.is_team_member(pp.team_id)
       and (pp.posted_by = auth.uid() or public.is_team_owner(pp.team_id))
)
```

Softening to any member later is one predicate — drop the final clause.

Worth knowing going in: most production posts arrived through
`import_teams_pdfs`, which writes `posted_by = null`, so in practice this means
**owners** for the existing corpus. That is an argument for softening sooner
rather than later, but starting tight and relaxing is the safer direction.

## Editable fields

**Editable:** `title`, `authors`, `venue`, `year`, `abstract`, `code_url`,
`data_url`.

**Deliberately not editable: `doi` and `url`.** Both are unique dedup keys
(`papers_doi_key`, `papers_url_norm_key`). Editing a DOI can collide with another
row outright, or silently split one paper into two identities across labs that
have already posted it. Correcting a wrong DOI is a *merge* problem, not an edit
problem, and deserves its own design. It is also far rarer than a wrong title.

**`published_at` moves with `year`.** It is a separate column
(`20260713140000_bibtex_import.sql`) that the Papers page sorts on, and it was
backfilled from `year` as `YYYY-01-01`. Correcting 2024 → 2023 without touching
it leaves the sort disagreeing with the year on screen. So: when `year` changes
and the stored `published_at` is a January 1st — the migration's own marker for
"year only" — rewrite it to the new year. When it carries real day precision,
leave it alone; a resolver that found a true publication date knows more than the
year field does.

## Two operations, not one

They solve different failures and should not be collapsed.

**1. Re-resolve** — `POST /papers/{id}/resolve`

Re-runs `fetch_metadata(url)` and writes what it finds. Nearly free, since the
resolver already exists, and it is the right fix for the whole
bioRxiv/OUP/Lancet class: the metadata was wrong because the resolver was
broken, and the resolver has since been fixed.

Two things it inherits from the existing resolve path and must not skip:

* **The rate limiter.** `/resolve` spends `_resolve_limiter.check(user_id)`
  (30/min/user) because it makes an outbound request every call. This endpoint
  makes the same request and needs the same budget, or it is the unmetered
  door into the same work.
* **The DOI-collision guard.** Re-resolving a rendition-DOI row is precisely how
  it learns the paper's *real* DOI — which another row may already hold, and
  `papers.doi` is unique. `backfill_metadata._doi_owner` already answers this:
  drop `doi` from the patch, write everything else, and report the pair as a
  duplicate for a human to merge. Reuse it rather than letting the constraint
  surface as a 500.

**2. Fix by hand** — `PATCH /papers/{id}`

Writes the supplied fields and records them as human-held (below). For the
residue: papers no registry will ever have.

Both are API endpoints rather than one being a `SECURITY DEFINER` RPC (as
`restore_post` is): re-resolve needs `fetch_metadata`, which is Python, and
splitting the pair across layers would mean two copies of the authorization rule
to keep in step.

## The flag, and who must respect it

**Not `metadata_source = 'manual'` — that value is already taken.**
`PaperFields.source` defaults to `"manual"` (`api/app.py`), and the
add-a-paper-by-hand path writes it straight to `papers.metadata_source`. Every
paper anyone has ever typed into the Add dialog therefore already reads as
`manual`. Making the backfill skip manual rows would strand exactly the
population the backfill exists to repair: paste a bioRxiv `…v1` rendition DOI by
hand today and the row could never be fixed again.

So the flag is **`edited_at is not null`** — a column this plan adds anyway for
audit, and one that means only what it says: a person deliberately corrected
this row. `metadata_source = 'manual'` is still written on a hand edit, as
provenance; it is simply not load-bearing.

Two places must check it, or the feature quietly undoes itself:

| Where | Change |
| --- | --- |
| `api/app.py::_repair_untitled` | return early when `edited_at is not null` |
| `api/backfill_metadata.py::needs_backfill` | exclude edited rows |

`import_paper_background` and the MCP server's `post_paper` both write through
`_upsert_paper`, so they are covered by the first.

**Editing must also reset the derived state**, exactly as `_repair_untitled`
already does: `embedded_at = null` and `enriched_at = null`.
`papers.embedding` is computed from title + abstract, so a corrected title with
a stale embedding is a paper that stays unfindable by meaning — which is the
silent failure this feature exists to remove.

## Audit

Two columns on `papers`: `edited_by uuid`, `edited_at timestamptz`.

A shared record changed by one person should say who — the same reasoning as
`removed_by` on the removal tombstone. Surfaced quietly in the detail view:
*"Metadata corrected by Ellen · 2 Oct"*.

## UI

In the `⋯` menu, above the removal and divided from it:

```
✎  Fix metadata…        Title, authors, venue, year
↻  Re-resolve           Fetch again from the publisher
──────────────────────────────────────────────────────
🗑  Remove from this lab…
```

**"Fix metadata", not "Edit"** — it is a repair affordance, and the name sets the
expectation that this is for when something is wrong, not general authorship.
The form opens pre-filled in the dialog, with a line noting that the change
applies wherever the paper appears.

**Re-resolve confirms when the row has already been corrected by hand.** As
first drafted it cleared the flag unconditionally, so one click could discard a
careful correction. The alternative — make Re-resolve fill only empty fields —
was rejected: a button whose behaviour depends on state the user cannot see is
worse than one extra click on a rare path. So Re-resolve keeps one meaning
everywhere ("fetch again and take what you find"), and on an edited row it says
so first. Confirming clears `edited_at`, because asking for it is an explicit
override.

## Migration

```sql
alter table public.papers
    add column edited_by uuid,
    add column edited_at timestamptz;
```

No member `UPDATE` grant: both writes go through the API as the service role,
which is what keeps the authorization rule in exactly one place.

## Out of scope

- Correcting a DOI or URL (a merge problem — see above).
- Merging two `papers` rows that turn out to be the same work.
- Per-lab metadata overrides. One paper, one record; per-lab titles would make
  the corpus inconsistent to avoid a governance decision, and search and
  embeddings read `papers` regardless.
- Suggest-and-approve review. Correct for a multi-lab Atlas, absurd overhead for
  one lab fixing its own typo.
