-- 20260713000000_doi_casefold.sql — DOIs are case-insensitive; store them folded.
--
-- DOIs are case-insensitive by spec (ISO 26324), but we matched them with a
-- case-sensitive `=`. AACR registers "10.1158/2159-8290.CD-25-1745" while PubMed
-- reports it lowercased, so the same paper shared via the publisher and via
-- PubMed produced two rows — different url_norm, and the DOI check missed.
--
-- Fold what's already stored so the API's now-normalised lookup finds it.
update public.papers
   set doi = lower(doi)
 where doi is not null
   and doi <> lower(doi);

-- Makes the DOI dedup lookup an index scan, and — once the remaining duplicate
-- rows are merged — this is where a `unique` index should go. It is deliberately
-- NOT unique yet: creating it as unique would fail while duplicates exist, and
-- resolving those means deleting rows, which is not a migration's job.
create index if not exists papers_doi_idx on public.papers (doi) where doi is not null;
