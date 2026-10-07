# Editing paper metadata — plan

Status: proposed. Depends on the `⋯` post menu from the Papers-page branch (#112).

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
`papers`; that is not an oversight, it is the question nobody had answered.

**The resolver re-reads papers.** `_repair_untitled` backfills on every re-add,
and `api/backfill_metadata.py` rewrites fields from Crossref. Without a flag,
**the next backfill silently overwrites a human correction** — and because both
run in the background, nobody finds out.

## Permissions

To start: in a lab that has posted this paper, the caller must be the **poster**
of that post or an **owner** of that lab. The same rule as removal, so there is
one mental model for "acting on a record other people share".

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

## Two operations, not one

They solve different failures and should not be collapsed.

**1. Re-resolve** — `POST /papers/{id}/resolve`

Re-runs `fetch_metadata(url)` and writes what it finds. Nearly free, since the
resolver already exists, and it is the right fix for the whole
bioRxiv/OUP/Lancet class: the metadata was wrong because the resolver was
broken, and the resolver has since been fixed. Clears the manual flag, because
asking for it is an explicit override.

**2. Fix by hand** — `PATCH /papers/{id}`

Writes the supplied fields and sets `metadata_source = 'manual'`. For the
residue: papers no registry will ever have.

Both are API endpoints rather than one being a `SECURITY DEFINER` RPC (as
`restore_post` is): re-resolve needs `fetch_metadata`, which is Python, and
splitting the pair across layers would mean two copies of the authorization rule
to keep in step.

## The flag, and who must respect it

`metadata_source = 'manual'`, joining the existing `crossref` / `arxiv` /
`pubmed` / `europepmc` / `citation_meta` / `unknown`.

Two places must check it, or the feature quietly undoes itself:

| Where | Change |
| --- | --- |
| `api/app.py::_repair_untitled` | return early when `metadata_source = 'manual'` |
| `api/backfill_metadata.py::needs_backfill` | exclude manual rows |

`import_paper_background` writes through `_upsert_paper`, so it is covered by the
first.

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

## Open question to settle before building

**Should Re-resolve be able to discard a manual edit by accident?** As proposed
it clears the flag, so one click can overwrite a careful correction. The
alternatives are to confirm when the row is already `manual`, or to make
Re-resolve fill only empty fields. Confirming is the better of the two — it
keeps one predictable meaning for the button rather than making its behaviour
depend on state the user cannot see.
