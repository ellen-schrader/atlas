-- 20261019190000_trial_extraction.sql — clinical trials, PR 4: the papers
-- behind a trial and what Claude extracts from them. See
-- docs/CLINICAL_TRIALS_PLAN.md (decided 18 Oct: Claude Opus 5.5; sources kept,
-- private to the lab; open-access full text fetched from Europe PMC).
--
--   * trial_sources: the files a lab has for a trial. PDFs a member uploads
--     (the bytes live in the private `trial-sources` bucket, policies in
--     20261019190500) and full-text XML Atlas fetched from Europe PMC.
--   * trial_facts gains the extraction (one jsonb document, shaped by
--     paper_radar/trials/extraction.py), its status and what it cost.
--   * trial_fact_reviews: which extracted values a member has checked
--     against the source ("verified").
--   * trial_fact_edits: every correction, with the value before and after.
--     Corrections go through edit_trial_fact(), which writes both.
--
-- All of it per lab (#133), all behind has_feature(team, 'clinical_trials').

create table public.trial_sources (
    id           uuid primary key default gen_random_uuid(),
    team_id      uuid not null references public.teams (id) on delete cascade,
    trial_id     uuid not null references public.trials (id) on delete cascade,
    -- The lab paper it is the full text (or supplement) of, if known.
    paper_id     uuid references public.papers (id) on delete set null,
    kind         text not null check (kind in ('paper', 'supplement')),
    origin       text not null check (origin in ('upload', 'europepmc')),
    -- `{team_id}/{trial_id}/{file}` in the trial-sources bucket.
    storage_path text not null unique,
    filename     text not null check (length(filename) between 1 and 200),
    media_type   text not null check (media_type in ('application/pdf', 'application/xml')),
    bytes        integer not null check (bytes > 0),
    added_by     uuid references public.profiles (id) on delete set null,
    added_at     timestamptz not null default now()
);
create index trial_sources_trial_idx on public.trial_sources (team_id, trial_id);
create index trial_sources_paper_idx on public.trial_sources (paper_id);
create index trial_sources_added_by_idx on public.trial_sources (added_by);

alter table public.trial_facts
    add column extraction            jsonb,
    add column extraction_status     text check (extraction_status in ('running', 'done', 'failed')),
    add column extraction_error      text,
    add column extraction_started_at timestamptz,
    add column extracted_at          timestamptz,
    add column extraction_model      text,
    -- Rough cost in US dollars, from the API's token counts.
    add column extraction_cost_usd   numeric(8, 4),
    -- The trial_sources ids Claude read, in order: "Doc 2" is the second, even
    -- after files are added or removed.
    add column extraction_sources    uuid[];

create table public.trial_fact_reviews (
    team_id     uuid not null references public.teams (id) on delete cascade,
    trial_id    uuid not null references public.trials (id) on delete cascade,
    -- A value's place in the extraction, e.g. "endpoints.0.exp_value".
    path        text not null check (path ~ '^[a-z_]+(\.[a-z0-9_]+)*$'),
    verified_by uuid references public.profiles (id) on delete set null,
    verified_at timestamptz not null default now(),
    primary key (team_id, trial_id, path)
);
create index trial_fact_reviews_verified_by_idx on public.trial_fact_reviews (verified_by);

create table public.trial_fact_edits (
    id        uuid primary key default gen_random_uuid(),
    team_id   uuid not null references public.teams (id) on delete cascade,
    trial_id  uuid not null references public.trials (id) on delete cascade,
    path      text not null,
    old_value jsonb,
    new_value jsonb,
    edited_by uuid references public.profiles (id) on delete set null,
    edited_at timestamptz not null default now()
);
create index trial_fact_edits_trial_idx on public.trial_fact_edits (team_id, trial_id, edited_at);
create index trial_fact_edits_edited_by_idx on public.trial_fact_edits (edited_by);

alter table public.trial_sources enable row level security;
alter table public.trial_fact_reviews enable row level security;
alter table public.trial_fact_edits enable row level security;

-- === trial_sources ==========================================================

create policy trial_sources_select on public.trial_sources for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

-- A member records a PDF they uploaded for a trial on the lab's list, at the
-- lab's own path. Europe PMC rows come from the service role.
create policy trial_sources_insert on public.trial_sources for insert
    to authenticated with check (
        public.has_feature(team_id, 'clinical_trials')
        and origin = 'upload'
        and media_type = 'application/pdf'
        and added_by = auth.uid()
        and storage_path like team_id::text || '/' || trial_id::text || '/%'
        and exists (select 1 from public.trial_posts tp
                     where tp.trial_id = trial_sources.trial_id and tp.team_id = trial_sources.team_id)
        and (paper_id is null or exists (select 1 from public.paper_posts pp
                     where pp.paper_id = trial_sources.paper_id and pp.team_id = trial_sources.team_id))
    );

create policy trial_sources_delete on public.trial_sources for delete
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

-- === reviews and edits ======================================================

create policy trial_fact_reviews_select on public.trial_fact_reviews for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));
create policy trial_fact_reviews_insert on public.trial_fact_reviews for insert
    to authenticated with check (
        public.has_feature(team_id, 'clinical_trials') and verified_by = auth.uid()
    );
-- "Not verified after all".
create policy trial_fact_reviews_delete on public.trial_fact_reviews for delete
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

create policy trial_fact_edits_select on public.trial_fact_edits for select
    to authenticated using (public.has_feature(team_id, 'clinical_trials'));

revoke all on public.trial_sources, public.trial_fact_reviews, public.trial_fact_edits
    from public, anon, authenticated;
grant select, delete on public.trial_sources to authenticated;
grant insert (team_id, trial_id, paper_id, kind, origin, storage_path, filename, media_type,
              bytes, added_by)
    on public.trial_sources to authenticated;
grant select, insert, delete on public.trial_fact_reviews to authenticated;
grant select on public.trial_fact_edits to authenticated;
grant select, insert, update, delete on public.trial_sources, public.trial_fact_reviews,
    public.trial_fact_edits to service_role;

select public.close_to_connectors('public.trial_sources');
select public.close_to_connectors('public.trial_fact_reviews');
select public.close_to_connectors('public.trial_fact_edits');

-- === correcting a value =====================================================

-- Sets one value in the lab's extraction and logs it, as the caller. The
-- extraction column isn't writable by members directly, so this is the only
-- way in: it checks the lab and the switch itself (security definer). A
-- corrected value is no longer "verified" (someone checked the old one), and
-- neither is any group that contains it.
create function public.edit_trial_fact(p_team uuid, p_trial uuid, p_path text, p_value jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
    keys   text[];
    n      int;
    doc    jsonb;
    parent jsonb;
    last   text;
    old    jsonb;
begin
    if not public.has_feature(p_team, 'clinical_trials') then
        raise exception 'Not allowed' using errcode = '42501';
    end if;
    if p_path !~ '^[a-z_]+(\.[a-z0-9_]+)*$' then
        raise exception 'Bad path' using errcode = '22023';
    end if;
    keys := string_to_array(p_path, '.');
    n := array_length(keys, 1);
    select extraction into doc
      from public.trial_facts
     where team_id = p_team and trial_id = p_trial and extraction is not null
       for update;
    if not found then
        raise exception 'Nothing extracted for this trial' using errcode = 'no_data_found';
    end if;
    -- Only an existing place: an edit never invents structure.
    parent := doc #> keys[1:n - 1];
    last := keys[n];
    if not coalesce(case jsonb_typeof(parent)
        when 'object' then parent ? last
        when 'array' then last ~ '^[0-9]+$' and last::int < jsonb_array_length(parent)
        else false end, false) then
        raise exception 'No such value' using errcode = '22023';
    end if;
    old := doc #> keys;
    -- Leaves only, and like for like: a number (or nothing) for a number, text
    -- (or nothing) for text. One call can't replace a whole section.
    if jsonb_typeof(old) in ('object', 'array')
       or jsonb_typeof(p_value) in ('object', 'array', 'boolean')
       or (jsonb_typeof(old) = 'number' and jsonb_typeof(p_value) not in ('number', 'null'))
       or (jsonb_typeof(old) = 'string' and jsonb_typeof(p_value) not in ('string', 'null')) then
        raise exception 'That value can''t be changed to this' using errcode = '22023';
    end if;
    update public.trial_facts
       set extraction = jsonb_set(extraction, keys, coalesce(p_value, 'null'::jsonb), false),
           updated_by = auth.uid(),
           updated_at = now()
     where team_id = p_team and trial_id = p_trial;
    insert into public.trial_fact_edits (team_id, trial_id, path, old_value, new_value, edited_by)
    values (p_team, p_trial, p_path, old, p_value, auth.uid());
    -- The value's own check and those of every group containing it
    -- ("enrolment" covers "enrolment.n_randomised").
    delete from public.trial_fact_reviews
     where team_id = p_team and trial_id = p_trial
       and (path = p_path or p_path like path || '.%');
end;
$$;
revoke execute on function public.edit_trial_fact(uuid, uuid, text, jsonb) from public, anon;
grant execute on function public.edit_trial_fact(uuid, uuid, text, jsonb) to authenticated;
