# Merging a preprint into its published paper — plan

Status: PR 1 built (migration `20261017120000_paper_aliases.sql`,
`api/merge_preprints.py`, #129). PR 2 built (ingest, `api/paper_identity.py`,
preprint venues and labels). PRs 3–4 to follow.

## Why

A preprint and the paper it became are one piece of work with two DOIs and two
URLs, so `papers` holds them as two rows. A lab that posted the bioRxiv link in
spring and the journal link in autumn sees the paper twice, with its comments,
reactions and reading status split between them. Nothing linked the two:
`parse_crossref` ignored Crossref's `relation`, and an arXiv row could end up
holding the journal's DOI with arXiv's metadata.

## Finding the published version

Only sources that state the link are trusted to merge on their own:

| Source | What it says | Notes |
|---|---|---|
| Crossref `relation.is-preprint-of` | preprint → published DOI | bioRxiv, medRxiv, Research Square, SSRN deposit it, sometimes weeks late |
| Crossref `relation.has-preprint` | published → preprint DOIs | when the published paper is posted second |
| bioRxiv/medRxiv `api.biorxiv.org/pubs/{server}/{doi}` | preprint → published DOI | often ahead of Crossref; asked only for `10.1101/`, `10.64898/` |
| arXiv `<arxiv:doi>` | preprint → journal DOI | |

Same title and first author with no stated link is a **probable pair**: listed
for a person to review, merged only with `merge_preprints --pair`.

`PaperMetadata` gains `is_preprint`, `published_doi` and `preprint_dois`;
`metadata.published_version(doi, url)` asks the three sources in that order.

## Data model

`paper_aliases` remembers what a merged-away row (or a preprint never stored
separately) was: `paper_id` (the kept paper), `kind` (`preprint` | `duplicate`),
`reason` (`crossref | biorxiv | arxiv | manual | doi_case`), `doi`, `url`,
`url_norm`, `venue`, `old_paper_id`, `snapshot` (the old row minus embedding).
It serves three purposes:

1. ingest looks up its DOI and url_norm, so the preprint posted again lands on
   the published paper;
2. `old_paper_id` redirects old `/papers/<id>` links and Teams cards;
3. the card shows a "Preprint" link, for whatever the journal version cut.

`merge_papers(from, into, reason)` (service role, atomic) folds one row into
another:

| What | How |
|---|---|
| Lab posts | lab held both → one post: tags combined, earlier share date and sharer, notes joined; otherwise moved. No undo tombstone is left for the folded post. |
| Reactions | moved; exact duplicates dropped |
| Reading status | saved if either; the further progress (unread < reading < read) |
| Comments, mentions, figures, edit history, removed-post tombstones, inbound links, aliases | moved |
| Maps pinned/excluded, summary citations, trends | ids swapped in the jsonb |
| The kept paper | keeps title, venue, year, DOI; gains a missing abstract, code/data link, keywords — never a field in `edited_fields`; AI tags combined; re-queued for embedding/enrichment if it gained an abstract |
| The old row | snapshot into `paper_aliases`, then deleted |

There is no unmerge. The snapshot is there for repair by hand; an undo gets
built if a bad merge ever happens.

## Decisions (Ellen, 2026-10-17)

1. A preprint posted when its published version exists is stored **as the
   published paper**, and the person posting it is told a published version
   exists so they can read that instead. Cards link to the preprint, for
   content the published version dropped.
2. Stated links merge automatically; title-only matches need a person.
3. No undo for now.
4. DOI-case duplicates use the same machinery; the unique `lower(doi)` index
   follows once prod has none left.
5. Preprints carry their server as the venue (bioRxiv, arXiv, …) and are
   marked "Preprint" wherever Atlas shows a venue.

## Preprint venues and the label

Crossref files a preprint as `posted-content` with the server under
`institution`, which the resolver ignored, so most preprints had no venue and
showed as a bare year. The resolver now names the server (Crossref's
institution, else `preprint_server()` from the URL host or DOI prefix);
migration `20261017130000_preprint_venues.sql` does the same for stored rows,
and `merge_preprints.py` asks Crossref for bioRxiv/medRxiv rows, whose shared
DOI prefix can't tell the two apart.

The label is derived from the venue (`web/src/lib/preprint.ts`, mirroring
`metadata._PREPRINT_VENUE_RE`) rather than stored in an `is_preprint` column:
every surface that shows a venue already has it, where a column would have
meant widening every search RPC's return type. Exports use the same test: a
preprint is BibTeX `@misc` with `howpublished = {bioRxiv}`, RIS `GEN` with the
server as `PB`.

## PRs

1. **Detection, schema, script** (this PR). `uv run python -m
   api.merge_preprints` reports; `--apply` merges DOI-case duplicates, then
   preprints with a stated published version already in Atlas, then lists
   title pairs. Run it on prod after merge, then the embedding and enrichment
   backfills.
2. **Ingest** (built). Every path finds a paper by url_norm → DOI →
   `paper_aliases` (`api/paper_identity.find_paper`; the BibTeX preflight and
   the Teams fast path do the same lookups). A preprint whose published version
   exists is stored as the published paper (`swap_to_published`) with the
   preprint recorded as an alias; the web dialog says so before posting, and
   MCP `post_paper` says so in its preview and result. Teams answers before the
   lookup runs, so its reply cannot; the card's preprint link is what the lab
   sees there. A published record naming its preprints (`has-preprint`)
   records them, merging any Atlas holds as a paper. arXiv rows get arXiv's own
   DOI (`10.48550/arxiv.<id>`), the journal DOI becoming `published_doi`. Old
   ids redirect (paper page and modal); cards, the table and the paper page
   link the preprint. The alias the web dialog posts back is trusted as far as
   the fields it posts with are: both come from /resolve, and a member could
   already store any title under any link.
3. **`create unique index on papers (lower(doi))`**, after the PR 1 script has
   run on prod (a migration would fail while duplicates remain).
4. **"Your preprint has been published" alerts.** A scheduled run (GitHub
   Actions cron, free) of the check, notifying everyone in a lab who posted or
   saved the preprint, in-app and in Teams. The same run should turn a stored
   preprint whose published version is *not* in Atlas into that version in
   place (with an alias), and do the same for old arXiv rows that hold their
   journal DOI — the two cases `merge_preprints.py` only reports today.
