-- 20261006120000_reading_status_two_axes.sql — split reading status into two axes.
--
-- paper_status.status crammed two independent questions into one field
-- (to_read | reading | read), which forced "save" and "finish" to be mutually
-- exclusive. Marking a saved paper read silently dropped it off the reading
-- list, and marking it unread afterwards deleted the save as well — verified
-- against the live table, not inferred.
--
-- They are not one question. "Do I want this?" is intent, and it is also how a
-- user flags a paper as central to their project — it should survive being
-- read, permanently. "Have I consumed it?" is progress. So:
--
--   saved  boolean → mine: on my list, and the strongest taste signal there is.
--   status text    → progress: 'unread' | 'reading' | 'read'.
--
-- Nothing leaves the saved set except by un-saving. Progress decides which VIEW
-- of the list a paper appears in, never whether it is still yours.
--
-- A row is meaningful iff (saved or status <> 'unread'); the app deletes an
-- all-default row rather than letting it linger, because recommend_v2 excludes
-- every paper that has ANY paper_status row — a stray unread/unsaved row would
-- silently hide an untouched paper from Discover.

alter table public.paper_status
    add column if not exists saved boolean not null default false;

-- Repurpose status to progress-only. The old 'to_read' means exactly "saved and
-- not started", which is the two-axis pair below.
alter table public.paper_status drop constraint if exists paper_status_status_check;

update public.paper_status
   set saved = true, status = 'unread'
 where status = 'to_read';

alter table public.paper_status alter column status set default 'unread';

alter table public.paper_status
    add constraint paper_status_status_check check (status in ('unread', 'reading', 'read'));

-- The saved lookup (reading list, taste weighting) runs on every page load.
create index if not exists paper_status_saved_idx
    on public.paper_status (user_id, team_id) where saved;

-- === the mention auto-add ==================================================
-- An @mention adds the paper to the mentioned user's list without touching
-- progress, so a paper they have already started or finished stays where it is
-- instead of being silently reset to unread. `do nothing` was wrong for the same
-- reason in reverse: a paper they had read but not saved never got saved.
create or replace function public.handle_mention_tbr()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.paper_status (user_id, paper_id, team_id, saved, status)
    values (new.mentioned_user, new.paper_id, new.team_id, true, 'unread')
    -- updated_at too: it has no trigger and its default only fires on INSERT,
    -- so being mentioned on a paper you read months ago would leave the save
    -- dated to the read rather than to the mention.
    on conflict (user_id, paper_id, team_id) do update set saved = true, updated_at = now();
    return new;
end;
$$;

-- === the filter RPCs =======================================================
-- p_status was 'unread' | 'to_read' | 'reading' | 'read' — one list mixing a
-- progress value with a membership one. It is now progress ('unread' |
-- 'reading' | 'read') plus 'saved', which asks the other axis. Both functions
-- must agree exactly or the "N results" label contradicts the list and infinite
-- scroll stops at the wrong place.
create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0,
    p_sort   text default 'shared',
    p_venue  text default null,
    p_status text default null   -- 'unread' | 'reading' | 'read' | 'saved'
)
returns setof public.paper_posts
language sql
stable
as $$
    select pp.*
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    left join public.paper_status ps
           on ps.paper_id = pp.paper_id
          and ps.team_id  = pp.team_id
          and ps.user_id  = auth.uid()
    where pp.team_id = p_team
      and (p_tag is null or pp.tags ? p_tag)
      and (p_venue is null or p.venue = p_venue)
      and (
        p_status is null
        -- "saved" asks the membership axis, independently of progress: a paper
        -- central to your project stays saved after you have read it.
        or (p_status = 'saved' and coalesce(ps.saved, false))
        -- No row at all is unread: never opened, never saved.
        or (p_status = 'unread' and (ps.status is null or ps.status = 'unread'))
        or (p_status in ('reading', 'read') and ps.status = p_status)
      )
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      )
    -- Identical to 20260713160000's ordering. Only the status predicate changes
    -- here; relevance and sort must not drift because this function was reissued.
    order by
      (case
         when public.prefix_tsquery(p_q) is null then 0
         else ts_rank(
                to_tsvector('english',
                  coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, '')),
                public.prefix_tsquery(p_q)
              )
       end) desc,
      (case when p_sort = 'published' then p.published_at end) desc nulls last,
      pp.posted_at desc,
      pp.id desc
    limit  greatest(coalesce(p_limit, 30), 0)
    offset greatest(coalesce(p_offset, 0), 0);
$$;

create or replace function public.search_papers_count(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_venue  text default null,
    p_status text default null
)
returns integer
language sql
stable
as $$
    select count(*)::int
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    left join public.paper_status ps
           on ps.paper_id = pp.paper_id
          and ps.team_id  = pp.team_id
          and ps.user_id  = auth.uid()
    where pp.team_id = p_team
      and (p_tag is null or pp.tags ? p_tag)
      and (p_venue is null or p.venue = p_venue)
      and (
        p_status is null
        or (p_status = 'saved' and coalesce(ps.saved, false))
        or (p_status = 'unread' and (ps.status is null or ps.status = 'unread'))
        or (p_status in ('reading', 'read') and ps.status = p_status)
      )
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      );
$$;
