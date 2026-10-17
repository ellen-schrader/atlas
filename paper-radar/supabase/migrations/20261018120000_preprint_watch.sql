-- 20261018120000_preprint_watch.sql — tell labs when a preprint is published,
-- and let them merge the duplicates Atlas can only guess at.
--
-- Three pieces, driven by api/preprint_watch.py (daily, GitHub Actions) and
-- the web app. See docs/preprint-dedup-plan.md, PR 4.
--
--   * notifications: "your preprint has been published", in the bell beside
--     @mentions. One row per person, lab and paper.
--   * promote_to_published(): a preprint whose published version is not in
--     Atlas becomes that version in place — same id, so its posts, comments
--     and reading status stay put — and the preprint is kept as an alias.
--   * merge_suggestions + decide_merge_suggestion(): pairs that look like a
--     preprint and its published version (same title, shared author) but that
--     nothing states. Any member of the lab holding both may merge them or
--     say they are not the same; a dismissed pair is never suggested again.

-- === notifications ==========================================================

create table public.notifications (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references public.profiles (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    paper_id   uuid not null references public.papers (id) on delete cascade,
    kind       text not null check (kind in ('preprint_published')),
    -- What the bell shows without another query: {title, venue, year, preprint_venue}.
    payload    jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    seen_at    timestamptz,
    -- The job may see the same publication twice (a retry); tell people once.
    unique (user_id, team_id, paper_id, kind)
);

create index notifications_inbox_idx on public.notifications (user_id, seen_at);

alter table public.notifications enable row level security;

-- Your own, and only in labs you are still in.
create policy notifications_select on public.notifications for select
    to authenticated using (user_id = auth.uid() and public.is_team_member(team_id));
create policy notifications_update on public.notifications for update
    to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

grant select on public.notifications to authenticated;
-- Marking one seen is the only change a person makes.
grant update (seen_at) on public.notifications to authenticated;
grant select, insert, update, delete on public.notifications to service_role;
-- Not for the Claude connector (20261017150000_connector_lockdown.sql).
select public.close_to_connectors('public.notifications');

-- === who merged what ========================================================

-- Set when a person confirmed the merge (decide_merge_suggestion), null when a
-- stated link (Crossref, bioRxiv, arXiv) did it.
alter table public.paper_aliases add column merged_by uuid references public.profiles (id) on delete set null;

-- === merge_papers: notifications move with the paper =========================

create or replace function public.merge_papers(p_from uuid, p_into uuid, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    src   public.papers;
    dst   public.papers;
    held  jsonb;
    alias  uuid;
    folded uuid[];
begin
    if p_from = p_into then
        raise exception 'Cannot merge a paper into itself.' using errcode = '22023';
    end if;

    -- Lock in id order, so two merges touching the same pair cannot deadlock.
    perform 1 from public.papers where id in (p_from, p_into) order by id for update;
    select * into src from public.papers where id = p_from;
    if not found then
        raise exception 'Paper % no longer exists.', p_from using errcode = 'no_data_found';
    end if;
    select * into dst from public.papers where id = p_into;
    if not found then
        raise exception 'Paper % no longer exists.', p_into using errcode = 'no_data_found';
    end if;

    -- 1. Lab posts. Where a lab holds both, fold the old post into the kept one
    --    and delete it; the rest move. The delete fires capture_removed_post(),
    --    whose tombstone would offer "undo" for a removal nobody made, so it is
    --    deleted straight after.
    update public.paper_posts d set
        tags            = (select coalesce(jsonb_agg(distinct t), '[]'::jsonb)
                             from jsonb_array_elements(d.tags || s.tags) t),
        note            = case
                              when nullif(btrim(s.note), '') is null or s.note = d.note then d.note
                              when nullif(btrim(d.note), '') is null then s.note
                              else d.note || E'\n\n' || s.note
                          end,
        posted_at       = least(d.posted_at, s.posted_at),
        posted_by       = case when s.posted_at < d.posted_at then s.posted_by else d.posted_by end,
        posted_by_label = case when s.posted_at < d.posted_at then s.posted_by_label else d.posted_by_label end,
        source          = case when s.posted_at < d.posted_at then s.source else d.source end,
        source_pdf      = case when s.posted_at < d.posted_at then s.source_pdf else d.source_pdf end,
        page            = case when s.posted_at < d.posted_at then s.page else d.page end,
        via             = case when s.posted_at < d.posted_at then s.via else d.via end
      from public.paper_posts s
     where s.paper_id = p_from and d.paper_id = p_into and d.team_id = s.team_id;

    -- Two statements, not one with a CTE: the trigger is AFTER, so it only
    -- writes the tombstone once the delete statement has finished.
    with gone as (
        delete from public.paper_posts s
         where s.paper_id = p_from
           and exists (select 1 from public.paper_posts d where d.paper_id = p_into and d.team_id = s.team_id)
        returning s.id
    )
    select coalesce(array_agg(id), '{}') into folded from gone;
    delete from public.removed_posts where id = any (folded);

    update public.paper_posts set paper_id = p_into where paper_id = p_from;

    -- 2. Reactions: move what doesn't already exist on the kept paper.
    delete from public.reactions s
     where s.paper_id = p_from
       and exists (
           select 1 from public.reactions d
            where d.paper_id = p_into and d.team_id = s.team_id
              and d.user_id = s.user_id and d.emoji = s.emoji
       );
    update public.reactions set paper_id = p_into where paper_id = p_from;

    -- 3. Reading status: saved on either axis stays saved; progress takes the
    --    further of the two (unread < reading < read).
    update public.paper_status d set
        saved      = d.saved or s.saved,
        status     = case
                         when 'read' in (d.status, s.status) then 'read'
                         when 'reading' in (d.status, s.status) then 'reading'
                         else 'unread'
                     end,
        updated_at = greatest(d.updated_at, s.updated_at)
      from public.paper_status s
     where s.paper_id = p_from and d.paper_id = p_into
       and d.user_id = s.user_id and d.team_id = s.team_id;
    delete from public.paper_status s
     where s.paper_id = p_from
       and exists (
           select 1 from public.paper_status d
            where d.paper_id = p_into and d.user_id = s.user_id and d.team_id = s.team_id
       );
    update public.paper_status set paper_id = p_into where paper_id = p_from;

    -- 4. No uniqueness on the paper: these just move.
    update public.comments           set paper_id = p_into where paper_id = p_from;
    update public.mentions           set paper_id = p_into where paper_id = p_from;
    update public.figures            set paper_id = p_into where paper_id = p_from;
    update public.paper_edits        set paper_id = p_into where paper_id = p_from;
    update public.removed_posts      set paper_id = p_into where paper_id = p_from;
    update public.inbound_unresolved set resolved_paper_id = p_into where resolved_paper_id = p_from;
    update public.paper_aliases      set paper_id = p_into where paper_id = p_from;
    update public.notifications      set paper_id = p_into where paper_id = p_from;

    -- 5. Paper ids held in jsonb, without a foreign key to cascade.
    update public.maps set config = jsonb_set(config, '{pinned}', public.jsonb_swap_id(config -> 'pinned', p_from, p_into))
     where config -> 'pinned' ? p_from::text;
    update public.maps set config = jsonb_set(config, '{excluded}', public.jsonb_swap_id(config -> 'excluded', p_from, p_into))
     where config -> 'excluded' ? p_from::text;
    update public.maps set ai_summary = jsonb_set(ai_summary, '{cited_ids}', public.jsonb_swap_id(ai_summary -> 'cited_ids', p_from, p_into))
     where ai_summary -> 'cited_ids' ? p_from::text;
    update public.trends set paper_ids = public.jsonb_swap_id(paper_ids, p_from, p_into)
     where paper_ids ? p_from::text;

    -- 6. Fill what the kept paper lacks. A new title or abstract changes what the
    --    embedding and tags were computed from, so both are queued again.
    held := dst.edited_fields;
    update public.papers set
        title       = case when nullif(btrim(dst.title), '') is null and not held ? 'title'
                           then coalesce(src.title, dst.title) else dst.title end,
        authors     = case when dst.authors = '[]'::jsonb and not held ? 'authors'
                           then src.authors else dst.authors end,
        year        = case when dst.year is null and not held ? 'year'
                           then src.year else dst.year end,
        abstract    = case when nullif(btrim(dst.abstract), '') is null and not held ? 'abstract'
                           then coalesce(src.abstract, dst.abstract) else dst.abstract end,
        code_url    = case when dst.code_url is null and not held ? 'code_url'
                           then src.code_url else dst.code_url end,
        data_url    = case when dst.data_url is null and not held ? 'data_url'
                           then src.data_url else dst.data_url end,
        keywords    = case when dst.keywords = '[]'::jsonb and not held ? 'keywords'
                           then src.keywords else dst.keywords end,
        tags        = (select coalesce(jsonb_agg(distinct t), '[]'::jsonb)
                         from jsonb_array_elements(dst.tags || src.tags) t)
     where id = p_into;
    update public.papers set embedded_at = null, enriched_at = null
     where id = p_into
       and (title, abstract) is distinct from (dst.title, dst.abstract);

    -- 7. Remember the old row, then delete it. Nothing references it any more,
    --    so the cascade has nothing left to do. Its DOI or url_norm can already
    --    be an alias key — a third copy of one DOI, or a merged preprint posted
    --    again before ingest read aliases — and those keys already lead to a
    --    paper, so this alias goes without them rather than failing the merge.
    insert into public.paper_aliases (paper_id, kind, reason, doi, url, url_norm, venue, old_paper_id, snapshot)
    values (
        p_into,
        case when p_reason = 'doi_case' then 'duplicate' else 'preprint' end,
        p_reason,
        case when exists (select 1 from public.paper_aliases where doi = lower(src.doi))
             then null else lower(src.doi) end,
        src.url,
        case when exists (select 1 from public.paper_aliases where url_norm = src.url_norm)
             then null else src.url_norm end,
        src.venue,
        src.id,
        to_jsonb(src) - 'embedding'
    )
    returning id into alias;

    delete from public.papers where id = p_from;
    return alias;
end;
$$;


-- === promote_to_published ===================================================

-- Turn preprint p_paper into its published version, in place. Service role.
--
-- p_patch is the published record: doi, url and url_norm (always written —
-- they are the paper's identity now), and title, authors, venue, year,
-- abstract, keywords, published_at, metadata_source (written unless a person
-- has edited that field). An empty value in the patch never blanks a field.
-- p_preprint_doi names the preprint's DOI when the row does not hold it: an
-- arXiv row that stored its journal DOI keeps arXiv's as the alias.
--
-- Fails rather than creating a duplicate if another paper already holds the
-- new DOI or link; the job merges into that paper instead.
create function public.promote_to_published(
    p_paper        uuid,
    p_patch        jsonb,
    p_reason       text,
    p_preprint_doi text default null
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    cur      public.papers;
    nxt      public.papers;
    held     jsonb;
    pre_doi  text;
    alias    uuid;
    touched  text[];
    content  constant text[] := array[
        'title', 'authors', 'venue', 'year', 'abstract', 'keywords', 'published_at'
    ];
begin
    select * into cur from public.papers where id = p_paper for update;
    if not found then
        raise exception 'Paper % no longer exists.', p_paper using errcode = 'no_data_found';
    end if;
    if exists (select 1 from public.papers
                where id <> p_paper
                  and (doi = p_patch ->> 'doi' or url_norm = p_patch ->> 'url_norm')) then
        raise exception 'Another paper already holds that DOI or link.' using errcode = '23505';
    end if;

    -- The preprint as it was, kept as an alias: its DOI and link still find
    -- this paper, and the card links to it.
    pre_doi := public.norm_doi(coalesce(p_preprint_doi, cur.doi));
    if pre_doi = p_patch ->> 'doi'
       or exists (select 1 from public.paper_aliases where doi = pre_doi) then
        pre_doi := null;
    end if;
    insert into public.paper_aliases (paper_id, kind, reason, doi, url, url_norm, venue, snapshot)
    values (
        p_paper, 'preprint', p_reason, pre_doi, cur.url,
        case when exists (select 1 from public.paper_aliases where url_norm = cur.url_norm)
             then null else cur.url_norm end,
        cur.venue,
        to_jsonb(cur) - 'embedding'
    )
    returning id into alias;

    -- Content keys a person holds, and empty values, are dropped from the patch.
    held := cur.edited_fields;
    select coalesce(jsonb_object_agg(k, v), '{}'::jsonb) into p_patch
      from jsonb_each(p_patch) as e(k, v)
     where not (k = any (content) and held ? k)
       and v not in ('null'::jsonb, '""'::jsonb, '[]'::jsonb);

    nxt := jsonb_populate_record(cur, p_patch);
    update public.papers set
        doi             = nxt.doi,
        url             = nxt.url,
        url_norm        = nxt.url_norm,
        title           = nxt.title,
        authors         = nxt.authors,
        venue           = nxt.venue,
        year            = nxt.year,
        abstract        = nxt.abstract,
        keywords        = nxt.keywords,
        published_at    = nxt.published_at,
        metadata_source = nxt.metadata_source,
        -- Title and abstract are what the embedding and tags are computed from.
        embedded_at     = case when (nxt.title, nxt.abstract) is distinct from (cur.title, cur.abstract)
                               then null else cur.embedded_at end,
        enriched_at     = case when (nxt.title, nxt.abstract) is distinct from (cur.title, cur.abstract)
                               then null else cur.enriched_at end
     where id = p_paper;

    -- The paper's history shows what the publication changed, like a Re-resolve.
    select array_agg(k) into touched
      from unnest(content || array['doi', 'url']) k
     where to_jsonb(cur) -> k is distinct from to_jsonb(nxt) -> k;
    if touched is not null then
        insert into public.paper_edits (paper_id, kind, edited_by, before, after)
        values (
            p_paper, 'resolve', null,
            (select jsonb_object_agg(k, to_jsonb(cur) -> k) from unnest(touched) k),
            (select jsonb_object_agg(k, to_jsonb(nxt) -> k) from unnest(touched) k)
        );
    end if;
    return alias;
end;
$$;

revoke execute on function public.promote_to_published(uuid, jsonb, text, text) from public;
grant execute on function public.promote_to_published(uuid, jsonb, text, text) to service_role;

-- === merge suggestions ======================================================

create table public.merge_suggestions (
    id           uuid primary key default gen_random_uuid(),
    team_id      uuid not null references public.teams (id) on delete cascade,
    -- A merge deletes the preprint row, and the suggestion goes with it: what
    -- the merge did is on the paper_aliases row (merged_by).
    preprint_id  uuid not null references public.papers (id) on delete cascade,
    published_id uuid not null references public.papers (id) on delete cascade,
    score        real not null,
    status       text not null default 'pending' check (status in ('pending', 'dismissed')),
    decided_by   uuid references public.profiles (id) on delete set null,
    decided_at   timestamptz,
    created_at   timestamptz not null default now(),
    -- One suggestion per pair and lab; a dismissed one stays, so it is never
    -- suggested again.
    unique (team_id, preprint_id, published_id),
    check (preprint_id <> published_id)
);

create index merge_suggestions_pending_idx on public.merge_suggestions (team_id) where status = 'pending';

alter table public.merge_suggestions enable row level security;

create policy merge_suggestions_select on public.merge_suggestions for select
    to authenticated using (public.is_team_member(team_id));

grant select on public.merge_suggestions to authenticated;
grant select, insert, update, delete on public.merge_suggestions to service_role;
select public.close_to_connectors('public.merge_suggestions');

-- A member answers a suggestion: merge the two papers, or say they are not the
-- same. SECURITY DEFINER because merging rewrites rows the member cannot write
-- (the shared paper, other labs' posts); safe because it only ever acts on a
-- pending suggestion for a lab the caller is in, never on ids they choose.
--
-- Any member may merge (Ellen, 2026-10-17). The merge applies to every lab
-- holding either paper, as an automatic merge would.
create function public.decide_merge_suggestion(p_suggestion uuid, p_merge boolean)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
    s public.merge_suggestions;
begin
    select * into s from public.merge_suggestions where id = p_suggestion for update;
    if not found then
        raise exception 'That suggestion no longer exists.' using errcode = 'no_data_found';
    end if;
    if not public.is_team_member(s.team_id) then
        raise exception 'That suggestion is not for your lab.' using errcode = '42501';
    end if;
    if s.status <> 'pending' then
        raise exception 'Someone has already answered that suggestion.' using errcode = '55000';
    end if;

    if not p_merge then
        update public.merge_suggestions
           set status = 'dismissed', decided_by = auth.uid(), decided_at = now()
         where id = p_suggestion;
        return 'dismissed';
    end if;

    perform public.merge_papers(s.preprint_id, s.published_id, 'manual');
    update public.paper_aliases set merged_by = auth.uid() where old_paper_id = s.preprint_id;
    return 'merged';
end;
$$;

revoke execute on function public.decide_merge_suggestion(uuid, boolean) from public;
grant execute on function public.decide_merge_suggestion(uuid, boolean) to authenticated;
