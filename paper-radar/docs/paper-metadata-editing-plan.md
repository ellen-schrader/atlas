# Editing paper metadata — plan

Status: implemented (migration `20261007140000_paper_metadata_editing.sql`). The
`⋯` post menu it builds on shipped in #112
(`web/src/components/PaperDetail.tsx::PostMenu`). Where the build departed from the
plan below, see **Changes made while building** at the end.

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

**Everything here is sized for more than one lab.** Today Atlas has one, and a
design that only works at one would be fine for months and then quietly wrong:
at two labs sharing a paper, an edit made in one lab lands in the other, made by
someone its members cannot see and cannot ask. The three decisions below —
per-field provenance, a history table, an audit line that degrades — are all
answers to that, and all cost roughly what the naive version costs *if done
now*. Retrofitting per-field provenance in particular means backfilling guesses
about which fields a human once touched.

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

Worth knowing going in: most production posts arrived through
`import_teams_pdfs`, which writes `posted_by = null`, so in practice this means
**owners** for the existing corpus.

**Do not soften this to any member yet**, tempting as that reads. Softening is
one predicate — drop the final clause — but with several labs it means any
member of any lab holding the paper may rewrite the row every other lab sees.
The dimension worth shrinking first is not who may edit, it is how much damage
an edit does: per-field provenance, a history to read, and a conflict that is
detected rather than silently won. With those in place this relaxes safely.

## Editable fields

**Editable:** `title`, `authors`, `venue`, `year`, `abstract`, `code_url`,
`data_url`.

**Deliberately not editable: `doi` and `url`.** Both are unique dedup keys
(`papers_doi_key`, `papers_url_norm_key`). Editing a DOI can collide with another
row outright, or silently split one paper into two identities across labs that
have already posted it. Correcting a wrong DOI is a *merge* problem, not an edit
problem, and deserves its own design. It is also far rarer than a wrong title —
and the more labs hold a paper, the worse splitting its identity gets.

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

**Both reject a stale write.** The caller sends the `edited_at` it rendered the
form from; if the stored value has moved, the write is refused with a 409 and
the client reloads. Two people correcting one paper — or one correcting it while
another hits Re-resolve — is close to impossible in a single lab and ordinary
across several, because the papers many labs hold are the well-known ones, which
are also the ones most likely to be interestingly wrong. Without the check the
loser of that race is never told. A null token means "this row had never been
edited when I loaded it", which is itself a claim worth checking.

## The flag: which fields a human holds

**Not `metadata_source = 'manual'` — that value is already taken.**
`PaperFields.source` defaults to `"manual"` (`api/app.py`), and the
add-a-paper-by-hand path writes it straight to `papers.metadata_source`. Every
paper anyone has ever typed into the Add dialog therefore already reads as
`manual`. Making the backfill skip manual rows would strand exactly the
population the backfill exists to repair: paste a bioRxiv `…v1` rendition DOI by
hand today and the row could never be fixed again.

**And not a single flag for the whole row, either.** A boolean (`edited_at is
not null`, say) opts the row out of *all* future backfill, not just the field
someone fixed. Correct a title today and the abstract Crossref publishes next
month never arrives — so the paper keeps a thin embedding, which is the precise
failure this feature exists to remove. Nothing surfaces that a row has opted
out, so nobody ever finds out. One lab and a dozen corrections hides this;
several labs and a growing corpus compounds it.

So the flag is **`edited_fields`** — the list of keys a human holds:

```
edited_fields  jsonb not null default '[]'::jsonb   -- e.g. ["title", "venue"]
```

`jsonb` rather than `text[]` only to match `authors`, `keywords` and `tags` on
the same table; the set is small and every reader of it is Python.

A hand edit adds the keys it wrote. Re-resolve clears the list, because asking
for it is an explicit override. `metadata_source = 'manual'` is still written on
a hand edit, as provenance; it is simply not load-bearing.

Two places must respect it, or the feature quietly undoes itself:

| Where | Change |
| --- | --- |
| `api/app.py::_repair_untitled` | skip when `"title"` is held — it writes nothing else into a titled row |
| `api/backfill_metadata.py::plan_update` | drop held keys from the patch before writing |

Note the second is a change to `plan_update`, not to `needs_backfill`: the row
still *qualifies* for backfill, it just doesn't get its corrected fields
overwritten. That is the whole point — a row with a hand-fixed title and an
empty abstract should still be offered the abstract. `plan_update` already
builds its patch field by field, so this is one filter. `needs_backfill` stays
as it is.

`import_paper_background` and the MCP server's `post_paper` both write through
`_upsert_paper`, so they are covered by the first row.

**Reset derived state only when it is actually derived from what changed.**
`papers.embedding` is computed from title + abstract (`embeddings.paper_text`),
and enrichment reads the same two fields. So `embedded_at = null` and
`enriched_at = null` belong on an edit that touched `title` or `abstract`, and
nowhere else. Resetting unconditionally would mean correcting a `code_url` buys
a Voyage embed and an Anthropic enrichment call — and re-tagging rewrites
`papers.tags`, which is the `canonical` tag list rendered in *every* lab holding
the paper. Fixing a link should not silently re-tag a paper for five other labs.

## Audit and history

Two columns on `papers` for the latest edit, so the common read is still one
row:

```
edited_by  uuid
edited_at  timestamptz
```

and a table behind them for what actually happened:

```sql
create table public.paper_edits (
    id         uuid primary key default gen_random_uuid(),
    paper_id   uuid not null references public.papers (id) on delete cascade,
    edited_by  uuid,
    edited_at  timestamptz not null default now(),
    before     jsonb not null,   -- only the keys this edit touched
    after      jsonb not null
);
```

The two columns alone were the original proposal, modelled on `removed_by`. But
removal did not stop at `removed_by` — it got `removed_posts`, holding the prior
values, and `restore_post` to put them back. Editing deserves the same half of
the pattern for the same reason, and more so: the person who notices a bad edit
may be in a different lab from the person who made it, cannot reach them through
Atlas, and otherwise has no way to learn what the title said before. Storing
`before`/`after` for the touched keys answers "what did it say", "who keeps
changing this", and makes an undo a matter of writing `before` back.

Pruned on write the way `removed_posts` is (`prune_removed_posts`), so there is
no cron to own.

RLS: readable by anyone who can already see the paper — the same predicate as
`papers_select`.

```sql
create policy paper_edits_select on public.paper_edits for select
    to authenticated using (exists (
        select 1 from public.paper_posts p
        where p.paper_id = paper_edits.paper_id and public.is_team_member(p.team_id)
    ));
```

Written only by the API as the service role, so there is no member-facing
insert, update or delete.

**The undo button itself is not in this PR.** The table is, because the shape of
what gets recorded is the part that cannot be added later — an edit that
happened before the history existed is gone. Restoring from it is a UI
affordance on top of data that will already be there.

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
This copy is doing more work than it looks: one global row per paper is only
tenable while edits are *corrections*, which are right for everyone. The moment
it reads as general authorship, labs start expressing preferences through it —
"Nat. Methods" against "Nature Methods" — and a shared corpus cannot hold both.
The form opens pre-filled in the dialog, with a line noting that the change
applies wherever the paper appears.

**Re-resolve confirms when fields are held by hand.** As first drafted it
cleared the flag unconditionally, so one click could discard a careful
correction. The alternative — make Re-resolve fill only empty fields — was
rejected: a button whose behaviour depends on state the user cannot see is worse
than one extra click on a rare path. So Re-resolve keeps one meaning everywhere
("fetch again and take what you find"), and on a row with a non-empty
`edited_fields` it names what it is about to overwrite first.

**The audit line degrades across labs.** *"Metadata corrected by Ellen · 2 Oct"*
cannot render for a lab the editor does not share: `profiles_select` is
`id = auth.uid() or shares_team_with(id)`, so the profile row simply isn't
readable, and the line renders with a hole in it. Resolving the name server-side
with the service role would fix the hole by leaking a person's identity across
exactly the boundary that policy draws, which is worse. So when
`shares_team_with(edited_by)` is false, the line reads *"Metadata corrected
outside your lab · 2 Oct"*. The useful half — that it was touched by a human,
and when — survives, and the attribution is only shown to people entitled to it.

## Migration

```sql
alter table public.papers
    add column edited_by     uuid,
    add column edited_at     timestamptz,
    add column edited_fields jsonb not null default '[]'::jsonb;
```

plus `paper_edits` and its policy above.

No member `UPDATE` grant on `papers`: both writes go through the API as the
service role, which is what keeps the authorization rule in exactly one place.

## Out of scope

- Correcting a DOI or URL (a merge problem — see above).
- Merging two `papers` rows that turn out to be the same work.
- An undo button for an edit. The history it would read from ships here; the
  affordance does not.
- Per-lab metadata overrides. One paper, one record; per-lab titles would make
  the corpus inconsistent to avoid a governance decision, and search and
  embeddings read `papers` regardless.
- Suggest-and-approve review. Correct for a multi-lab Atlas, absurd overhead for
  one lab fixing its own typo.

## Changes made while building

Checking the plan against the code turned up five gaps. Each one fails silently
in the multi-lab case the plan is designed for.

- **Re-resolve is recorded too.** As planned, only hand edits wrote history and
  moved `edited_at`. But Re-resolve is the one write that can *discard* a hand
  correction, which makes it the last thing that should go unrecorded. And the
  stale-write token is `edited_at`, so a Re-resolve that didn't move it could
  race a hand edit undetected. Both operations now go through the same write,
  and `paper_edits.kind` says which one it was (`edit` | `resolve`).
- **One atomic write, via a service-role RPC.** Checking the token, updating the
  row and inserting the history as separate PostgREST calls would let an edit
  land with no history behind it. `apply_paper_edit` does all three in one
  transaction. It is granted to `service_role` only, and refuses any column
  outside an allow-list, so `url`/`url_norm` can't be written even by mistake.
  Authorization stays in one place: `can_edit_paper(p_paper)` is written in terms
  of `auth.uid()`, so the API calls it with the caller's JWT, and the same
  function can back an RLS policy later.
- **The Re-resolve override is enforced by the server.** The API returns 409
  when fields are held unless the request has `discard_edits: true`. A confirm
  dialog only in the web client would not stop any other client (MCP, scripts).
- **History is pruned by count, not age.** Each paper keeps its newest 50 edits.
  Pruning by age would eventually delete the record of the edit that is still
  live on the row, which is the one most worth keeping.
- **An edit kicks off re-embedding and re-tagging, not just a reset.**
  Setting `embedded_at`/`enriched_at` to null only helps if a backfill runs, and
  backfills are run by hand. The PATCH queues the same background tasks
  `/posts` does, and only when `title` or `abstract` changed.

Also:

- A title can't be cleared by hand (400): an untitled row is exactly what the
  resolver backfills.
- Only fields that actually changed become held. Saving the form without
  changing a field doesn't take that field away from future backfills.
- `plan_update` now compares the author and keyword lists before writing them,
  so an unchanged list doesn't make a history entry. It also re-embeds when the
  abstract changes, not only the title, and moves `published_at` with `year`
  (`follow_year`, shared with the API).
- The audit line says *"Metadata refreshed"* rather than *"corrected"* when the
  last write was a Re-resolve (no held fields).
- `PaperDetail.tsx` approximates `can_edit_paper` with this lab's half of the
  rule (the same gate as removal). The server is the authority. A poster in
  another lab simply won't see the menu here.

**Re-resolve is not in the UI (yet).** After using it, it turned out to have no
moment where a person would reach for it. The papers people notice are wrong
are mostly bot-walled, so fetching the same URL again returns the same nothing.
The case it does fix — the resolver has since been fixed — is invisible to a
reader and is already covered across the corpus by `api/backfill_metadata.py`.
It earns a button once a link or DOI can be corrected: "point it at the right
URL, then fetch". So `POST /papers/{id}/resolve` stays in place, with its
history, rate limit and override guard, and the web app does not call it.

The menu item is **"Edit paper…"** rather than "Fix metadata…", and the form
has no explanatory paragraph; the button text "Save for every lab" carries the
one thing that has to be said.
