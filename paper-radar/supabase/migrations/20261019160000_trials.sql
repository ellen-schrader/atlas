-- 20261019160000_trials.sql — clinical trials, PR 1: trial records, a lab's
-- trials, and the papers that report them. See docs/CLINICAL_TRIALS_PLAN.md.
--
-- Shaped like papers: `trials` is one row per registered trial (NCT ID),
-- shared, written only by the service role from ClinicalTrials.gov.
-- `trial_posts` is the lab's list and the visibility boundary, like
-- paper_posts. `paper_trials` (which paper reports which trial) belongs to
-- the lab, as everything a lab adds or decides does since #133.
--
-- Every policy also asks has_feature(team_id, 'clinical_trials'): until the
-- feature is switched on for a lab or a person (20261019150000), nobody reads
-- or writes any of it.

create table public.trials (
    id                  uuid primary key default gen_random_uuid(),
    nct_id              text not null unique check (nct_id ~ '^NCT[0-9]{8}$'),
    acronym             text,           -- "KEYNOTE-522"; from the registry, else the title
    title               text not null,  -- the registry's brief title
    official_title      text,
    phases              text[] not null default '{}',  -- "PHASE3", as the registry has them
    status              text,           -- "COMPLETED", "RECRUITING", …
    sponsor             text,
    conditions          text[] not null default '{}',
    enrollment          integer,
    start_date          text,           -- the registry's partial dates ("2017-03", "2017-03-07")
    completion_date     text,
    has_results         boolean not null default false,  -- results posted on ClinicalTrials.gov
    -- The registry's protocolSection, as fetched. Later PRs read arms,
    -- eligibility and outcomes from it.
    registry            jsonb not null,
    registry_updated_at date,           -- the registry's own last-update date
    fetched_at          timestamptz not null default now(),
    created_at          timestamptz not null default now()
);

create table public.trial_posts (
    id         uuid primary key default gen_random_uuid(),
    trial_id   uuid not null references public.trials (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    -- null when Atlas added it because a lab paper names it (source 'paper'),
    -- or when the person who added it has deleted their account.
    added_by   uuid references public.profiles (id) on delete set null,
    source     text not null check (source in ('manual', 'paper')),
    created_at timestamptz not null default now(),
    unique (trial_id, team_id)
);
create index trial_posts_team_idx on public.trial_posts (team_id);
create index trial_posts_added_by_idx on public.trial_posts (added_by);

create table public.paper_trials (
    id          uuid primary key default gen_random_uuid(),
    team_id     uuid not null references public.teams (id) on delete cascade,
    paper_id    uuid not null references public.papers (id) on delete cascade,
    trial_id    uuid not null references public.trials (id) on delete cascade,
    -- How the link was found: the NCT ID in the paper's abstract, the trial's
    -- acronym in its title, or a person.
    source      text not null check (source in ('nct_in_abstract', 'acronym_in_title', 'manual')),
    -- 'auto': found by NCT ID, shown as linked. 'suggested': a weaker match
    -- that waits for a person. 'confirmed' / 'rejected': a person decided.
    -- A rejected link stays, so it is not suggested again.
    status      text not null check (status in ('auto', 'suggested', 'confirmed', 'rejected')),
    role        text check (role in ('primary', 'survival', 'secondary', 'translational', 'other')),
    reviewed_by uuid references public.profiles (id) on delete set null,
    reviewed_at timestamptz,
    created_at  timestamptz not null default now(),
    unique (team_id, paper_id, trial_id)
);
create index paper_trials_trial_idx on public.paper_trials (team_id, trial_id);
create index paper_trials_paper_idx on public.paper_trials (paper_id);
create index paper_trials_reviewed_by_idx on public.paper_trials (reviewed_by);

alter table public.trials enable row level security;
alter table public.trial_posts enable row level security;
alter table public.paper_trials enable row level security;

-- === trials: read if one of your labs has it ================================

create policy trials_select on public.trials for select
    to authenticated using (
        exists (
            select 1 from public.trial_posts tp
             where tp.trial_id = trials.id
               and public.has_feature(tp.team_id, 'clinical_trials')
        )
    );

-- === trial_posts: the lab's list ============================================

create policy trial_posts_select on public.trial_posts for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

-- Added by hand, as yourself. Rows from papers (source 'paper') come from the
-- service role.
create policy trial_posts_insert on public.trial_posts for insert
    to authenticated with check (
        public.has_feature(team_id, 'clinical_trials')
        and added_by = auth.uid()
        and source = 'manual'
    );

-- Any member can take a trial off the lab's list.
create policy trial_posts_delete on public.trial_posts for delete
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

-- === paper_trials: the lab's links ==========================================

create policy paper_trials_select on public.paper_trials for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

-- A person links a paper the lab holds to a trial the lab holds.
create policy paper_trials_insert on public.paper_trials for insert
    to authenticated with check (
        public.has_feature(team_id, 'clinical_trials')
        and source = 'manual'
        and status = 'confirmed'
        and reviewed_by = auth.uid()
        and exists (select 1 from public.paper_posts pp
                     where pp.paper_id = paper_trials.paper_id and pp.team_id = paper_trials.team_id)
        and exists (select 1 from public.trial_posts tp
                     where tp.trial_id = paper_trials.trial_id and tp.team_id = paper_trials.team_id)
    );

-- Confirm, reject or give a role, as yourself. Only those columns are granted,
-- so a link can't be moved to another paper, trial or lab.
create policy paper_trials_update on public.paper_trials for update
    to authenticated
    using (public.has_feature(team_id, 'clinical_trials'))
    with check (
        public.has_feature(team_id, 'clinical_trials')
        and reviewed_by = auth.uid()
        and status in ('confirmed', 'rejected')
    );

create policy paper_trials_delete on public.paper_trials for delete
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

-- Named roles too (see 20261010140000).
revoke all on public.trials, public.trial_posts, public.paper_trials from public, anon, authenticated;
grant select on public.trials to authenticated;
grant select, insert, delete on public.trial_posts to authenticated;
grant select, insert, delete on public.paper_trials to authenticated;
grant update (status, role, reviewed_by, reviewed_at) on public.paper_trials to authenticated;
grant select, insert, update, delete on public.trials, public.trial_posts, public.paper_trials to service_role;

-- Closed to Claude connectors for now; MCP trial tools come in a later PR.
select public.close_to_connectors('public.trials');
select public.close_to_connectors('public.trial_posts');
select public.close_to_connectors('public.paper_trials');

-- === merges keep their links ================================================
--
-- merge_papers() deletes the old paper, and the cascade would take its trial
-- links with it. It records the merge in paper_aliases (old_paper_id) while
-- the old row still exists, so the links move to the kept paper here, without
-- touching merge_papers itself. Where the lab already links the kept paper to
-- the same trial, the person's decision wins over an automatic one.
create function public.paper_aliases_move_trial_links()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if new.old_paper_id is null or new.old_paper_id = new.paper_id then
        return new;
    end if;

    update public.paper_trials d set
        status      = s.status,
        source      = s.source,
        role        = coalesce(d.role, s.role),
        reviewed_by = s.reviewed_by,
        reviewed_at = s.reviewed_at
      from public.paper_trials s
     where s.paper_id = new.old_paper_id and d.paper_id = new.paper_id
       and d.team_id = s.team_id and d.trial_id = s.trial_id
       and d.status in ('auto', 'suggested') and s.status in ('confirmed', 'rejected');

    delete from public.paper_trials s
     where s.paper_id = new.old_paper_id
       and exists (select 1 from public.paper_trials d
                    where d.paper_id = new.paper_id
                      and d.team_id = s.team_id and d.trial_id = s.trial_id);

    update public.paper_trials set paper_id = new.paper_id where paper_id = new.old_paper_id;
    return new;
end;
$$;

revoke execute on function public.paper_aliases_move_trial_links() from public, anon, authenticated;

create trigger paper_aliases_move_trial_links
    after insert on public.paper_aliases
    for each row execute function public.paper_aliases_move_trial_links();
