-- A paper can also be linked to a trial because PubMed lists the trial's NCT
-- ID on the paper's record (its databank list), which covers papers whose
-- abstract doesn't name it. Found automatically, like 'nct_in_abstract'.

alter table public.paper_trials drop constraint paper_trials_source_check;
alter table public.paper_trials
    add constraint paper_trials_source_check
    check (source in ('nct_in_abstract', 'acronym_in_title', 'pubmed', 'manual'));
