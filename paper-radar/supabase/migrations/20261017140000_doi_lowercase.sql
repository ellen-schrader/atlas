-- 20261017140000_doi_lowercase.sql — papers.doi is stored lowercase, enforced.
--
-- DOIs are case-insensitive (ISO 26324) and every lookup folds them
-- (paper_radar/ingest/urls.py: norm_doi), so a row holding a mixed-case DOI is
-- one no lookup finds, and the same paper posted again comes in twice. Two
-- migrations folded what was stored (20260713000000, 20260725100000); the
-- second had to skip rows whose folded DOI another row already held, because
-- merging papers was not a migration's job. Those were the DOI-case duplicates
-- api/merge_preprints.py merges (20261017120000_paper_aliases.sql).
--
-- With none left, a check constraint makes the existing case-sensitive UNIQUE
-- on doi case-insensitive in effect, and turns a writer that forgets norm_doi
-- into a failed write instead of a silent duplicate. Prod on 2026-10-17: 716
-- DOIs, none mixed-case, no collisions.
--
-- If this fails on `papers_doi_lowercase`, a DOI-case duplicate has appeared
-- since: run `python -m api.merge_preprints --apply` and deploy again.

update public.papers
   set doi = lower(doi)
 where doi is not null
   and doi <> lower(doi);

alter table public.papers
    add constraint papers_doi_lowercase check (doi = lower(doi));

-- The partial index 20260713000000 added "until the duplicates are merged" adds
-- nothing beside papers_doi_key's index, which serves the same lookups.
drop index if exists public.papers_doi_idx;
