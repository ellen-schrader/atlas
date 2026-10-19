-- 20261019220000_trial_extraction_claude.sql — clinical trials, PR 8:
-- extractions recorded by a lab member's own Claude through the Atlas
-- connector (atlas_mcp/trials.py: record_trial_extraction). They cost Atlas
-- nothing and are marked as such.

alter table public.trial_facts drop constraint trial_facts_extraction_mode_check;
alter table public.trial_facts add constraint trial_facts_extraction_mode_check
    check (extraction_mode in ('batch', 'now', 'claude'));
