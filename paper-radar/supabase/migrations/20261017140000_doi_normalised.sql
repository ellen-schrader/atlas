-- 20261017140000_doi_normalised.sql — DOIs are stored in norm_doi's form, enforced.
--
-- Every DOI lookup goes through norm_doi (paper_radar/ingest/urls.py:
-- lowercased, resolver prefix and surrounding slashes stripped), so a stored
-- DOI in any other form is one no lookup finds, and the same paper posted
-- again comes in twice. Two migrations folded what was stored (20260713000000,
-- 20260725100000); the second had to skip rows whose folded DOI another row
-- already held, because merging papers was not a migration's job. Those were
-- the DOI-case duplicates api/merge_preprints.py merges
-- (20261017120000_paper_aliases.sql).
--
-- With none left, a check constraint on papers.doi makes the existing UNIQUE
-- on it case-insensitive in effect, and turns a writer that skips norm_doi into
-- a failed write instead of a silent duplicate. paper_aliases.doi, the other
-- column ingest looks DOIs up in, gets the same. Prod on 2026-10-17: 716 paper
-- DOIs and 4 alias DOIs, all already in this form.
--
-- If this migration fails on papers_doi_key (unique_violation) in the UPDATE
-- below, two papers hold one DOI in different spellings: run
-- `python -m api.merge_preprints --apply`, which merges them, and deploy again.

-- norm_doi in SQL, for the constraint and the fold below. Python's strip()
-- trims all Unicode whitespace where btrim here trims the ASCII kind; a DOI
-- where the two disagree is refused at write time and the API stores the paper
-- without it (app.py: _find_or_insert_paper).
create function public.norm_doi(d text)
returns text
language sql
immutable
as $$
    select nullif(
        btrim(
            regexp_replace(
                lower(btrim(d, E' \t\r\n')),
                '^(https?://(dx\.)?doi\.org/|doi:)+',
                ''
            ),
            '/'
        ),
        ''
    );
$$;

update public.papers
   set doi = public.norm_doi(doi)
 where doi is distinct from public.norm_doi(doi);

update public.paper_aliases
   set doi = public.norm_doi(doi)
 where doi is distinct from public.norm_doi(doi);

-- `is not distinct from`, so a DOI that folds to nothing ('', 'doi:') is
-- refused rather than passing as a NULL comparison would.
alter table public.papers
    add constraint papers_doi_normalised
        check (doi is not distinct from public.norm_doi(doi));

alter table public.paper_aliases
    add constraint paper_aliases_doi_normalised
        check (doi is not distinct from public.norm_doi(doi));

-- The partial index 20260713000000 added "until the duplicates are merged" adds
-- nothing beside papers_doi_key's index, which serves the same lookups.
drop index if exists public.papers_doi_idx;
