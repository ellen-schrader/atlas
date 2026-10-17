# Merging a preprint into its published paper — plan

Status: PR 1 built (migration `20261017120000_paper_aliases.sql`,
`api/merge_preprints.py`). PRs 2–4 to follow.

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

## PRs

1. **Detection, schema, script** (this PR). `uv run python -m
   api.merge_preprints` reports; `--apply` merges DOI-case duplicates, then
   preprints with a stated published version already in Atlas, then lists
   title pairs. Run it on prod after merge, then the embedding and enrichment
   backfills.
2. **Ingest.** `_upsert_paper` (and `import_teams_pdfs`) looks up url_norm →
   DOI → `paper_aliases` → the published DOI. A preprint whose published version
   exists is stored as the published paper with an alias, and the response
   (web dialog, MCP `post_paper`, Teams reply) says so. A published paper whose
   preprint is in Atlas (`has-preprint`) is merged straight away. arXiv rows get
   their own DOI (`10.48550/arxiv.<id>`), the journal DOI becoming
   `published_doi`; the script then handles arXiv rows still holding a journal
   DOI. Old ids redirect; cards and the paper page show the preprint link.
3. **`create unique index on papers (lower(doi))`**, after the PR 1 script has
   run on prod (a migration would fail while duplicates remain).
4. **"Your preprint has been published" alerts.** A scheduled run (GitHub
   Actions cron, free) of the check, notifying everyone in a lab who posted or
   saved the preprint, in-app and in Teams.
