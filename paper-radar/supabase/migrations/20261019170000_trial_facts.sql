-- 20261019170000_trial_facts.sql — clinical trials, PR 2: what a lab knows
-- about each of its trials. See docs/CLINICAL_TRIALS_PLAN.md.
--
-- One row per lab and trial, like everything a lab decides (#133): the short
-- name the lab uses ("NeoTRIP", where the registry says "NeoTRIPaPDL1") and
-- the classification the All trials page filters by. Claude fills it in when a
-- trial joins the lab's list; any member can correct it, and a correction is
-- never overwritten by Claude again. Later PRs add the extracted data
-- (schema, results, enrolment) as more columns here.
--
-- The vocabularies are the breast cancer taxonomy in
-- paper_radar/trials/taxonomy.py and web/src/lib/trials.ts.

create table public.trial_facts (
    team_id         uuid not null references public.teams (id) on delete cascade,
    trial_id        uuid not null references public.trials (id) on delete cascade,
    acronym         text check (acronym is null or length(btrim(acronym)) between 1 and 40),
    settings        text[] not null default '{}'
        check (settings <@ array['neoadjuvant', 'adjuvant', 'metastatic']),
    patient_groups  text[] not null default '{}'
        check (patient_groups <@ array['tnbc', 'hr_pos_her2_neg', 'her2_pos', 'her2_low', 'gbrca']),
    therapy_classes text[] not null default '{}'
        check (therapy_classes <@ array['immunotherapy', 'adc', 'cdk46', 'parp', 'her2_targeted',
                                        'other_targeted', 'endocrine', 'chemotherapy']),
    -- 'claude' until a person edits the row; then 'person', and Claude leaves it.
    classified_by   text check (classified_by in ('claude', 'person')),
    classified_at   timestamptz,
    updated_by      uuid references public.profiles (id) on delete set null,
    updated_at      timestamptz not null default now(),
    primary key (team_id, trial_id)
);
create index trial_facts_updated_by_idx on public.trial_facts (updated_by);
create index trial_facts_trial_idx on public.trial_facts (trial_id);

alter table public.trial_facts enable row level security;

-- Read while the trial is on the lab's list.
create policy trial_facts_select on public.trial_facts for select
    to authenticated using (
        public.has_feature(team_id, 'clinical_trials')
        and exists (select 1 from public.trial_posts tp
                     where tp.trial_id = trial_facts.trial_id and tp.team_id = trial_facts.team_id)
    );

-- A member writes as themselves, as a person, for a trial on the list. An
-- insert covers a trial Claude hasn't classified yet.
create policy trial_facts_insert on public.trial_facts for insert
    to authenticated with check (
        public.has_feature(team_id, 'clinical_trials')
        and classified_by = 'person'
        and updated_by = auth.uid()
        and exists (select 1 from public.trial_posts tp
                     where tp.trial_id = trial_facts.trial_id and tp.team_id = trial_facts.team_id)
    );

create policy trial_facts_update on public.trial_facts for update
    to authenticated
    using (public.has_feature(team_id, 'clinical_trials'))
    with check (
        public.has_feature(team_id, 'clinical_trials')
        and classified_by = 'person'
        and updated_by = auth.uid()
    );

revoke all on public.trial_facts from public, anon, authenticated;
grant select on public.trial_facts to authenticated;
-- Only the lab's own fields: a row can't be moved to another lab or trial.
grant insert (team_id, trial_id, acronym, settings, patient_groups, therapy_classes,
              classified_by, classified_at, updated_by, updated_at)
    on public.trial_facts to authenticated;
grant update (acronym, settings, patient_groups, therapy_classes,
              classified_by, classified_at, updated_by, updated_at)
    on public.trial_facts to authenticated;
grant select, insert, update, delete on public.trial_facts to service_role;

select public.close_to_connectors('public.trial_facts');
