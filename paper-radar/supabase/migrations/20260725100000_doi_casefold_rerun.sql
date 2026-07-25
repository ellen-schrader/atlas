-- 20260725100000_doi_casefold_rerun.sql — re-fold DOIs written raw since 13 July.
--
-- 20260713000000_doi_casefold.sql lowercased the rows that existed then, but
-- api/import_teams_pdfs.py kept writing meta.doi verbatim until it was routed
-- through the shared norm_doi (PR #96), so PDF-imported papers could store
-- mixed-case DOIs that the casefolded dedup lookups (fast inbound-webhook
-- reply, _upsert_paper) never match.
--
-- Collision-safe under papers.doi's case-sensitive UNIQUE constraint: a row is
-- only folded when no OTHER row folds to the same key (whether that other row
-- is already lowercase, or is a second mixed-case variant). Colliding pairs
-- are duplicate papers; merging rows is not a migration's job — they keep
-- today's behavior (background dedup still prevents new duplicates).
update public.papers p
   set doi = lower(p.doi)
 where p.doi is not null
   and p.doi <> lower(p.doi)
   and not exists (
         select 1
           from public.papers q
          where q.id <> p.id
            and lower(q.doi) = lower(p.doi)
       );
