-- 20261019210000_trial_extraction_queue.sql — cheaper, automatic extraction.
-- See docs/CLINICAL_TRIALS_PLAN.md.
--
--   * Extractions are queued and sent through Anthropic's Message Batches API
--     (half price, results within hours) by api/trial_extract_batch.py, every
--     two hours. "Extract now" still runs one at full price.
--   * A trial queues itself when it gets its first source (an upload, or the
--     daily open-access fetch), if it was never extracted.
--   * trial_extraction_spend records every paid call, so each lab's monthly
--     cap can be enforced, whatever the outcome of the call.

alter table public.trial_facts drop constraint trial_facts_extraction_status_check;
alter table public.trial_facts add constraint trial_facts_extraction_status_check
    check (extraction_status in ('queued', 'batched', 'running', 'done', 'failed'));

alter table public.trial_facts
    add column extraction_queued_at timestamptz,
    -- The Anthropic batch it was sent in (status 'batched').
    add column extraction_batch_id  text,
    -- The trial_sources the batch request read, in order (its "Doc N").
    add column extraction_batch_sources uuid[],
    -- Paid attempts for the current request: a failure is retried once.
    add column extraction_attempts  integer not null default 0,
    add column extraction_mode      text check (extraction_mode in ('batch', 'now')),
    -- What a sent batch request is expected to cost, so a lab's batches can't
    -- overshoot its cap before their results (and real costs) come back.
    add column extraction_estimate_usd numeric(8, 4),
    -- When the daily job last looked for this trial's open-access full text,
    -- so closed-access trials don't hold the queue.
    add column open_access_checked_at timestamptz;

create table public.trial_extraction_spend (
    id       uuid primary key default gen_random_uuid(),
    team_id  uuid not null references public.teams (id) on delete cascade,
    trial_id uuid not null references public.trials (id) on delete cascade,
    usd      numeric(8, 4) not null check (usd >= 0),
    model    text,
    mode     text not null check (mode in ('batch', 'now')),
    spent_at timestamptz not null default now()
);
create index trial_extraction_spend_team_idx on public.trial_extraction_spend (team_id, spent_at);
create index trial_extraction_spend_trial_idx on public.trial_extraction_spend (trial_id);

alter table public.trial_extraction_spend enable row level security;
-- The lab sees what its extractions cost ("$3.20 of $10 this month").
create policy trial_extraction_spend_select on public.trial_extraction_spend for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));
revoke all on public.trial_extraction_spend from public, anon, authenticated;
grant select on public.trial_extraction_spend to authenticated;
grant select, insert, update, delete on public.trial_extraction_spend to service_role;
select public.close_to_connectors('public.trial_extraction_spend');

-- A trial that gets its first source and was never extracted queues itself.
-- The batch job waits half an hour after queueing before sending it, so the
-- rest of a set of uploads (paper, then supplement) is read with it.
-- A finished or running extraction is left alone: extracting again is a
-- person's decision (it costs, and replaces checked values).
create function public.trial_sources_queue_extraction()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.trial_facts (team_id, trial_id)
    values (new.team_id, new.trial_id)
    on conflict (team_id, trial_id) do nothing;
    update public.trial_facts
       set extraction_status = 'queued',
           extraction_queued_at = now(),
           extraction_error = null,
           extraction_attempts = 0,
           extraction_mode = 'batch'
     where team_id = new.team_id and trial_id = new.trial_id
       and extraction is null
       and (extraction_status is null or extraction_status = 'failed');
    return new;
end;
$$;
revoke execute on function public.trial_sources_queue_extraction() from public, anon, authenticated;

create trigger trial_sources_queue_extraction
    after insert on public.trial_sources
    for each row execute function public.trial_sources_queue_extraction();
