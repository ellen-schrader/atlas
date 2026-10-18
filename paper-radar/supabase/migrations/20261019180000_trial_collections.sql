-- 20261019180000_trial_collections.sql — clinical trials, PR 3: collections.
-- See docs/CLINICAL_TRIALS_PLAN.md.
--
-- A collection is a clinical question the lab follows ("Does adding checkpoint
-- inhibition to neoadjuvant chemotherapy help in early TNBC?"), with the
-- trials that answer it, papers about the question as a whole, lab notes and
-- followers. Every member can edit a collection (decided 18 Oct); the creator
-- or a lab owner can delete it.
--
-- All of it is the lab's, and every policy asks has_feature(team,
-- 'clinical_trials') as the other trial tables do.

create table public.trial_collections (
    id              uuid primary key default gen_random_uuid(),
    team_id         uuid not null references public.teams (id) on delete cascade,
    title           text not null check (length(btrim(title)) between 1 and 140),
    question        text check (question is null or length(question) <= 600),
    -- The question's tags, from the same taxonomy as trial_facts.
    settings        text[] not null default '{}'
        check (settings <@ array['neoadjuvant', 'adjuvant', 'metastatic']),
    patient_groups  text[] not null default '{}'
        check (patient_groups <@ array['tnbc', 'hr_pos_her2_neg', 'her2_pos', 'her2_low', 'gbrca']),
    therapy_classes text[] not null default '{}'
        check (therapy_classes <@ array['immunotherapy', 'adc', 'cdk46', 'parp', 'her2_targeted',
                                        'other_targeted', 'endocrine', 'chemotherapy']),
    -- "Immunotherapy + chemotherapy vs chemotherapy"
    comparison      text check (comparison is null or length(comparison) <= 140),
    created_by      uuid references public.profiles (id) on delete set null,
    created_at      timestamptz not null default now(),
    updated_by      uuid references public.profiles (id) on delete set null,
    updated_at      timestamptz not null default now()
);
create index trial_collections_team_idx on public.trial_collections (team_id);
create index trial_collections_created_by_idx on public.trial_collections (created_by);
create index trial_collections_updated_by_idx on public.trial_collections (updated_by);

create table public.collection_trials (
    collection_id uuid not null references public.trial_collections (id) on delete cascade,
    trial_id      uuid not null references public.trials (id) on delete cascade,
    added_by      uuid references public.profiles (id) on delete set null,
    added_at      timestamptz not null default now(),
    primary key (collection_id, trial_id)
);
create index collection_trials_trial_idx on public.collection_trials (trial_id);
create index collection_trials_added_by_idx on public.collection_trials (added_by);

-- Papers about the question as a whole (a meta-analysis, a review). Papers
-- reporting one trial come from paper_trials and aren't listed here.
create table public.collection_papers (
    collection_id uuid not null references public.trial_collections (id) on delete cascade,
    paper_id      uuid not null references public.papers (id) on delete cascade,
    added_by      uuid references public.profiles (id) on delete set null,
    added_at      timestamptz not null default now(),
    primary key (collection_id, paper_id)
);
create index collection_papers_paper_idx on public.collection_papers (paper_id);
create index collection_papers_added_by_idx on public.collection_papers (added_by);

create table public.collection_followers (
    collection_id uuid not null references public.trial_collections (id) on delete cascade,
    user_id       uuid not null references public.profiles (id) on delete cascade,
    followed_at   timestamptz not null default now(),
    primary key (collection_id, user_id)
);
create index collection_followers_user_idx on public.collection_followers (user_id);

create table public.collection_notes (
    id            uuid primary key default gen_random_uuid(),
    collection_id uuid not null references public.trial_collections (id) on delete cascade,
    author_id     uuid references public.profiles (id) on delete set null,
    body          text not null check (length(btrim(body)) between 1 and 4000),
    created_at    timestamptz not null default now()
);
create index collection_notes_collection_idx on public.collection_notes (collection_id, created_at);
create index collection_notes_author_idx on public.collection_notes (author_id);

-- The lab a collection belongs to, for the child tables' policies.
create function public.collection_team(c uuid)
returns uuid
language sql
stable
security definer
set search_path = public
as $$
    select team_id from public.trial_collections where id = c;
$$;
revoke execute on function public.collection_team(uuid) from public, anon;
grant execute on function public.collection_team(uuid) to authenticated, service_role;

alter table public.trial_collections enable row level security;
alter table public.collection_trials enable row level security;
alter table public.collection_papers enable row level security;
alter table public.collection_followers enable row level security;
alter table public.collection_notes enable row level security;

-- === trial_collections ======================================================

create policy trial_collections_select on public.trial_collections for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

create policy trial_collections_insert on public.trial_collections for insert
    to authenticated with check (
        public.has_feature(team_id, 'clinical_trials')
        and created_by = auth.uid() and updated_by = auth.uid()
    );

-- Any member edits, as themselves. The column grants keep team_id and the
-- creator fixed.
create policy trial_collections_update on public.trial_collections for update
    to authenticated
    using (public.has_feature(team_id, 'clinical_trials'))
    with check (public.has_feature(team_id, 'clinical_trials') and updated_by = auth.uid());

create policy trial_collections_delete on public.trial_collections for delete
    to authenticated using (
        public.has_feature(team_id, 'clinical_trials')
        and (created_by = auth.uid() or public.is_team_owner(team_id))
    );

-- === collection_trials: trials on the lab's list ============================

create policy collection_trials_select on public.collection_trials for select
    to authenticated using (public.has_feature(public.collection_team(collection_id), 'clinical_trials'));

create policy collection_trials_insert on public.collection_trials for insert
    to authenticated with check (
        public.has_feature(public.collection_team(collection_id), 'clinical_trials')
        and added_by = auth.uid()
        and exists (select 1 from public.trial_posts tp
                     where tp.trial_id = collection_trials.trial_id
                       and tp.team_id = public.collection_team(collection_trials.collection_id))
    );

create policy collection_trials_delete on public.collection_trials for delete
    to authenticated using (public.has_feature(public.collection_team(collection_id), 'clinical_trials'));

-- === collection_papers: papers the lab holds ================================

create policy collection_papers_select on public.collection_papers for select
    to authenticated using (public.has_feature(public.collection_team(collection_id), 'clinical_trials'));

create policy collection_papers_insert on public.collection_papers for insert
    to authenticated with check (
        public.has_feature(public.collection_team(collection_id), 'clinical_trials')
        and added_by = auth.uid()
        and exists (select 1 from public.paper_posts pp
                     where pp.paper_id = collection_papers.paper_id
                       and pp.team_id = public.collection_team(collection_papers.collection_id))
    );

create policy collection_papers_delete on public.collection_papers for delete
    to authenticated using (public.has_feature(public.collection_team(collection_id), 'clinical_trials'));

-- === collection_followers: each person their own ============================

create policy collection_followers_select on public.collection_followers for select
    to authenticated using (public.has_feature(public.collection_team(collection_id), 'clinical_trials'));

create policy collection_followers_insert on public.collection_followers for insert
    to authenticated with check (
        public.has_feature(public.collection_team(collection_id), 'clinical_trials')
        and user_id = auth.uid()
    );

create policy collection_followers_delete on public.collection_followers for delete
    to authenticated using (user_id = auth.uid());

-- === collection_notes =======================================================

create policy collection_notes_select on public.collection_notes for select
    to authenticated using (public.has_feature(public.collection_team(collection_id), 'clinical_trials'));

create policy collection_notes_insert on public.collection_notes for insert
    to authenticated with check (
        public.has_feature(public.collection_team(collection_id), 'clinical_trials')
        and author_id = auth.uid()
    );

-- Your own notes; a lab owner tidies up notes whose author left Atlas.
create policy collection_notes_delete on public.collection_notes for delete
    to authenticated using (
        author_id = auth.uid()
        or (author_id is null and public.is_team_owner(public.collection_team(collection_id)))
    );

-- === grants =================================================================

revoke all on public.trial_collections, public.collection_trials, public.collection_papers,
    public.collection_followers, public.collection_notes from public, anon, authenticated;
grant select, insert, delete on public.trial_collections to authenticated;
grant update (title, question, settings, patient_groups, therapy_classes, comparison,
              updated_by, updated_at)
    on public.trial_collections to authenticated;
grant select, insert, delete on public.collection_trials, public.collection_papers,
    public.collection_followers, public.collection_notes to authenticated;
grant select, insert, update, delete on public.trial_collections, public.collection_trials,
    public.collection_papers, public.collection_followers, public.collection_notes to service_role;

select public.close_to_connectors('public.trial_collections');
select public.close_to_connectors('public.collection_trials');
select public.close_to_connectors('public.collection_papers');
select public.close_to_connectors('public.collection_followers');
select public.close_to_connectors('public.collection_notes');

-- === keeping collections consistent =========================================

-- A trial taken off the lab's list leaves the lab's collections too: they
-- only hold trials the lab follows.
create function public.trial_posts_leave_collections()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    delete from public.collection_trials ct
     using public.trial_collections c
     where c.id = ct.collection_id and c.team_id = old.team_id and ct.trial_id = old.trial_id;
    return old;
end;
$$;
revoke execute on function public.trial_posts_leave_collections() from public, anon, authenticated;

create trigger trial_posts_leave_collections
    after delete on public.trial_posts
    for each row execute function public.trial_posts_leave_collections();

-- merge_papers() deletes the old paper; move its collection entries to the
-- kept paper first, as 20261019160000 does for trial links.
create function public.paper_aliases_move_collection_papers()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    if new.old_paper_id is null or new.old_paper_id = new.paper_id then
        return new;
    end if;
    delete from public.collection_papers s
     where s.paper_id = new.old_paper_id
       and exists (select 1 from public.collection_papers d
                    where d.paper_id = new.paper_id and d.collection_id = s.collection_id);
    update public.collection_papers set paper_id = new.paper_id where paper_id = new.old_paper_id;
    return new;
end;
$$;
revoke execute on function public.paper_aliases_move_collection_papers() from public, anon, authenticated;

create trigger paper_aliases_move_collection_papers
    after insert on public.paper_aliases
    for each row execute function public.paper_aliases_move_collection_papers();
