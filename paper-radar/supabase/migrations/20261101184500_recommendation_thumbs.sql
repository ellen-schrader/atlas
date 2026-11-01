-- 20261101184500_recommendation_thumbs.sql — 👍 / 👎 on recommendations (#182).
--
-- 20261101130000 gave paper_status a dismissed_at ("Not interested", ✕ on
-- Home's cards). The cards now answer a recommendation with a thumb:
--
--   liked_at      👍 "More like this": a private positive signal (taste.W_LIKED,
--                 between reading and saving) without adding the paper to the
--                 reading list. Not a reaction, which the whole lab sees.
--   dismissed_at  👎 "Not interested", as before.
--
-- Either one answers the recommendation, so seen_by_me() counts both and the
-- paper isn't offered again. A row holds at most one answer: a check
-- constraint, so a write that would set both fails rather than one being
-- dropped quietly. The app writes both columns on every click; merge_papers
-- picks the newest answer of the two copies itself.
--
-- Saving the paper or starting to read it still clears a 👎
-- (paper_status_clear_dismissal, 20261101130000): a saved or read paper is not
-- one you aren't interested in, and un-saving it later puts it back into
-- circulation. Home's card says so: saving clears its 👎, and 👎 is off on a
-- card you've saved. The trigger now fires only when a column it reads changes.
--
-- seen_by_me and merge_papers are copied from 20261101130000 with liked_at added.

alter table public.paper_status add column if not exists liked_at timestamptz;

alter table public.paper_status
    add constraint paper_status_one_answer check (num_nonnulls(liked_at, dismissed_at) <= 1);

drop trigger if exists paper_status_clear_dismissal on public.paper_status;
create trigger paper_status_clear_dismissal
    before insert or update of saved, status, dismissed_at on public.paper_status
    for each row execute function public.paper_status_clear_dismissal();

-- === what counts as "seen" ===================================================

-- The caller has done something with this paper in this lab, so it isn't news to
-- them. A paper_status row has to MEAN something: saved is intent, progress past
-- 'unread' is consumption, liked_at / dismissed_at answer a recommendation. The
-- all-default row un-saving leaves behind says nothing (20261007130000).
-- Reactions and comments count whatever they are. Posting is checked by the
-- callers, on the post row.
create or replace function public.seen_by_me(p_paper uuid, p_team uuid)
returns boolean
language sql
stable
set search_path = public
as $$
    select exists (
               select 1 from public.paper_status ps
               where ps.paper_id = p_paper and ps.team_id = p_team and ps.user_id = auth.uid()
                 and (ps.saved or ps.status <> 'unread'
                      or ps.liked_at is not null or ps.dismissed_at is not null)
           )
        or exists (
               select 1 from public.reactions r
               where r.paper_id = p_paper and r.team_id = p_team and r.user_id = auth.uid()
           )
        or exists (
               select 1 from public.comments c
               where c.paper_id = p_paper and c.team_id = p_team and c.author_id = auth.uid()
           );
$$;

-- === merges keep the newest answer ===========================================

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
        updated_at = greatest(d.updated_at, s.updated_at),
        -- An answer to either copy is an answer about the paper. One answer per
        -- row (paper_status_one_answer), so the newest of the four wins: the
        -- newest 👍 if it is newer than the newest 👎, else the newest 👎.
        -- greatest() skips nulls, so an unanswered copy changes nothing.
        liked_at     = case
                           when greatest(d.liked_at, s.liked_at)
                                > coalesce(greatest(d.dismissed_at, s.dismissed_at), '-infinity')
                           then greatest(d.liked_at, s.liked_at)
                       end,
        dismissed_at = case
                           when greatest(d.dismissed_at, s.dismissed_at)
                                >= coalesce(greatest(d.liked_at, s.liked_at), '-infinity')
                           then greatest(d.dismissed_at, s.dismissed_at)
                       end
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
    -- A person told about both papers keeps the kept paper's notice.
    delete from public.notifications s
     where s.paper_id = p_from
       and exists (
           select 1 from public.notifications d
            where d.paper_id = p_into and d.user_id = s.user_id
              and d.team_id = s.team_id and d.kind = s.kind
       );
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
