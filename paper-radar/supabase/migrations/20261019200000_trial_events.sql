-- 20261019200000_trial_events.sql — clinical trials, PR 6: what changed, for
-- the "Recent updates in your collections" feed. See docs/CLINICAL_TRIALS_PLAN.md.
--
-- One row per lab and happening, like everything else trial-related (#133):
--   * registry_updated / status_changed / results_posted: the daily refresh
--     (api/trials_refresh.py) saw ClinicalTrials.gov change; one row for each
--     lab holding the trial.
--   * paper_linked / extraction_done / values_verified: written by the
--     triggers below, so no code path can forget them.
-- The feed shows them; nobody is notified (the bell stays for people).

create table public.trial_events (
    id         uuid primary key default gen_random_uuid(),
    team_id    uuid not null references public.teams (id) on delete cascade,
    trial_id   uuid not null references public.trials (id) on delete cascade,
    kind       text not null check (kind in (
                   'registry_updated', 'status_changed', 'results_posted',
                   'paper_linked', 'extraction_done', 'values_verified')),
    -- Small details: {"from": "RECRUITING", "to": "COMPLETED"}, {"paper_id": …}.
    detail     jsonb not null default '{}',
    -- Who did it, for the lab's own actions; null for Atlas.
    actor      uuid references public.profiles (id) on delete set null,
    created_at timestamptz not null default now()
);
create index trial_events_team_idx on public.trial_events (team_id, created_at desc);
create index trial_events_trial_idx on public.trial_events (trial_id);
create index trial_events_actor_idx on public.trial_events (actor);

alter table public.trial_events enable row level security;

create policy trial_events_select on public.trial_events for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

revoke all on public.trial_events from public, anon, authenticated;
grant select on public.trial_events to authenticated;
grant select, insert, update, delete on public.trial_events to service_role;
select public.close_to_connectors('public.trial_events');

-- === recorded by triggers ===================================================

create function public.trial_events_record()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if tg_table_name = 'paper_trials' then
        -- A paper newly counted as reporting the trial.
        if new.status in ('auto', 'confirmed')
           and (tg_op = 'INSERT' or old.status not in ('auto', 'confirmed')) then
            insert into public.trial_events (team_id, trial_id, kind, detail, actor)
            values (new.team_id, new.trial_id, 'paper_linked',
                    jsonb_build_object('paper_id', new.paper_id), auth.uid());
        end if;
    elsif tg_table_name = 'trial_facts' then
        if new.extraction_status = 'done'
           and new.extracted_at is distinct from old.extracted_at then
            insert into public.trial_events (team_id, trial_id, kind, detail)
            values (new.team_id, new.trial_id, 'extraction_done',
                    jsonb_build_object('model', new.extraction_model));
        end if;
    elsif tg_table_name = 'trial_fact_reviews' then
        insert into public.trial_events (team_id, trial_id, kind, detail, actor)
        values (new.team_id, new.trial_id, 'values_verified',
                jsonb_build_object('path', new.path), auth.uid());
    end if;
    return new;
end;
$$;
revoke execute on function public.trial_events_record() from public, anon, authenticated;

create trigger paper_trials_events after insert or update of status on public.paper_trials
    for each row execute function public.trial_events_record();
create trigger trial_facts_events after update of extraction_status, extracted_at on public.trial_facts
    for each row execute function public.trial_events_record();
create trigger trial_fact_reviews_events after insert on public.trial_fact_reviews
    for each row execute function public.trial_events_record();
