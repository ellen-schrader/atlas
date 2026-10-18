-- 20261018180000_abstract_checked_at.sql — when the daily job last looked for a
-- paper's missing abstract (api/backfill_abstracts.py, issue #136).
--
-- A paper is usually posted before Europe PMC or PubMed have indexed it, so the
-- lookup at ingest finds nothing. The job retries daily for a paper's first 30
-- days, weekly until 90, then never again; this column is how it paces itself.
-- Written only by the job (service role); nothing else reads it.
alter table public.papers add column abstract_checked_at timestamptz;
