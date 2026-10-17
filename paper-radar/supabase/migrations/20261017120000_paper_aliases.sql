-- 20261017120000_paper_aliases.sql — merge a preprint into its published paper.
--
-- A preprint and the paper it became are one piece of work, but they carry
-- different DOIs and URLs, so `papers` held them as two rows: a lab that posted
-- the bioRxiv link in spring and the journal link in autumn saw the paper twice,
-- with its comments and reading status split between the two. The same machinery
-- also folds the DOI-capitalisation duplicates 20260725100000 had to skip.
--
-- merge_papers() moves everything that hangs off the old row onto the kept one
-- and deletes the old row. What the old row *was* survives as a paper_aliases
-- row, which does three jobs:
--   1. ingest looks up its DOI and url_norm, so the preprint posted again lands
--      on the published paper instead of coming back as a new row;
--   2. old_paper_id redirects /papers/<old id> links (Teams cards, bookmarks);
--   3. the card shows "Preprint" with a link, for whatever the journal cut.
-- An alias can also exist without a merge: a preprint posted when its published
-- version is already known is stored as the published paper straight away.
-- See docs/preprint-dedup-plan.md.

create table public.paper_aliases (
    id           uuid primary key default gen_random_uuid(),
    paper_id     uuid not null references public.papers (id) on delete cascade,
    -- 'preprint': an earlier version of the paper, shown on its card.
    -- 'duplicate': the same record held twice (DOI capitalisation); never shown.
    kind         text not null check (kind in ('preprint', 'duplicate')),
    -- What linked the two: Crossref's is-preprint-of / has-preprint relation,
    -- bioRxiv's publication API, arXiv's journal DOI, or a person.
    reason       text not null check (reason in ('crossref', 'biorxiv', 'arxiv', 'manual', 'doi_case')),
    doi          text,             -- normalised (lowercase, no resolver prefix)
    url          text,
    url_norm     text,
    venue        text,             -- "bioRxiv", "arXiv": the card's link label
    -- The row merge_papers() deleted, if this alias came from a merge. Unique so
    -- a redirect has exactly one target.
    old_paper_id uuid unique,
    -- The old row as it was, minus the embedding: enough to repair a bad merge
    -- by hand. There is no unmerge; see the plan.
    snapshot     jsonb,
    created_at   timestamptz not null default now()
);

-- Ingest's lookup keys. Unique, because one DOI or URL resolving to two papers
-- is the very duplicate this table exists to end.
create unique index paper_aliases_doi_key on public.paper_aliases (doi) where doi is not null;
create unique index paper_aliases_url_norm_key on public.paper_aliases (url_norm) where url_norm is not null;
create index paper_aliases_paper_idx on public.paper_aliases (paper_id);

alter table public.paper_aliases enable row level security;

-- Readable by anyone who can see the paper — the same predicate as papers_select.
-- Written only by the service role (ingest and merge_papers).
create policy paper_aliases_select on public.paper_aliases for select
    to authenticated using (exists (
        select 1 from public.paper_posts p
        where p.paper_id = paper_aliases.paper_id and public.is_team_member(p.team_id)
    ));

grant select on public.paper_aliases to authenticated;
grant select, insert, update, delete on public.paper_aliases to service_role;

-- Replace one id in a jsonb array of ids, dropping the duplicate if the array
-- already held the other. For maps.config pinned/excluded, maps.ai_summary
-- cited_ids and trends.paper_ids, which hold paper ids without a foreign key.
create function public.jsonb_swap_id(arr jsonb, old_id uuid, new_id uuid)
returns jsonb
language sql
immutable
as $$
    select coalesce(jsonb_agg(v order by first_pos), '[]'::jsonb)
      from (
          select v, min(pos) as first_pos
            from (
                select case when e = to_jsonb(old_id::text) then to_jsonb(new_id::text) else e end as v,
                       pos
                  from jsonb_array_elements(arr) with ordinality as t(e, pos)
            ) swapped
           group by v
      ) deduped;
$$;

-- Fold paper p_from into paper p_into and delete p_from, all or nothing.
--
-- p_into keeps its own bibliographic record: it is the published version. It
-- gains a title, authors, year, abstract, code/data link or keywords only where
-- it has none, and never a field a person has edited (edited_fields) — an empty
-- field someone cleared on purpose stays empty. Venue, DOI and dates are never
-- taken from the old row: a preprint's would be wrong for the journal version.
--
-- Rows unique per paper collide when a lab touched both versions, and are
-- combined rather than dropped:
--   paper_posts (paper, lab): one post, tags combined, the earlier share kept
--     whole (who, when and where from), so attribution matches its source
--   reactions (paper, lab, user, emoji): the duplicate is dropped
--   paper_status (user, paper, lab): saved if either was, the further progress
-- Everything else just moves.
--
-- Service role only. Returns the paper_aliases id.
create function public.merge_papers(p_from uuid, p_into uuid, p_reason text)
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

-- Postgres grants EXECUTE to PUBLIC on a new function; revoke first.
revoke execute on function public.merge_papers(uuid, uuid, text) from public;
grant execute on function public.merge_papers(uuid, uuid, text) to service_role;
