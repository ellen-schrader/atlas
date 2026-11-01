-- 20261101130000_dismiss_recommendations.sql — "Not interested" (#182).
--
-- Until now the only way to clear a recommendation you didn't want was to mark
-- it read, which told the taste vector you had read it. paper_status gets a
-- dismissed_at: the paper leaves Discover, the Claude connector's
-- recommend_reading and the digest's "For you", and nothing else changes. A
-- dismissed row is unsaved and unread, so taste.engagement_weights already
-- skips it as a signal.
--
-- Saving the paper or starting to read it later clears the dismissal (trigger
-- below), so un-saving it afterwards puts it back into circulation, as
-- un-saving always has.
--
-- The three functions are copied verbatim from 20261019100000_recommend_exclude.sql
-- and 20261019120000_connector_taste.sql; the only change is the dismissed_at
-- test in the paper_status exclusion. Same signatures, so grants are kept.

alter table public.paper_status add column if not exists dismissed_at timestamptz;

create or replace function public.paper_status_clear_dismissal()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    if new.saved or new.status <> 'unread' then
        new.dismissed_at := null;
    end if;
    return new;
end;
$$;

drop trigger if exists paper_status_clear_dismissal on public.paper_status;
create trigger paper_status_clear_dismissal
    before insert or update on public.paper_status
    for each row execute function public.paper_status_clear_dismissal();

create or replace function public.recommend_papers(
    p_team    uuid,
    p_query   extensions.vector(1024),
    p_limit   int default 12,
    p_exclude uuid[] default '{}'
)
returns table(post_id uuid, paper_id uuid, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    with candidates as (
        select
            pp.id       as post_id,
            pp.paper_id as paper_id,
            pp.posted_at,
            (1 - (p.embedding <=> p_query))::real as similarity
        from public.paper_posts pp
        join public.papers p on p.id = pp.paper_id
        where pp.team_id = p_team
          and p.embedding is not null
          and pp.posted_by is distinct from auth.uid()  -- not one you posted
          and not (pp.paper_id = any (coalesce(p_exclude, '{}')))
          and not exists (
              select 1 from public.paper_status ps
              where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
                -- The row has to MEAN something. Saved is intent; any progress
                -- other than 'unread' is consumption. Neither is true of the
                -- all-default row left by un-saving.
                and (ps.saved or ps.status <> 'unread' or ps.dismissed_at is not null)
          )
          and not exists (
              select 1 from public.reactions r
              where r.paper_id = p.id and r.team_id = p_team and r.user_id = auth.uid()
          )
          and not exists (
              select 1 from public.comments c
              where c.paper_id = p.id and c.team_id = p_team and c.author_id = auth.uid()
          )
        order by p.embedding <=> p_query          -- HNSW index serves this
        limit greatest(coalesce(p_limit, 12), 0) * 5
    )
    select post_id, paper_id, similarity
    from candidates
    order by
        similarity
        + 0.06 * exp(- extract(epoch from (now() - posted_at)) / (86400.0 * 30)) desc
    limit greatest(coalesce(p_limit, 12), 0);
$$;

create or replace function public.recommend_tagged(
    p_team    uuid,
    p_tags    text[],
    p_query   extensions.vector(1024) default null,
    p_limit   int default 12,
    p_exclude uuid[] default '{}'
)
returns table(post_id uuid, paper_id uuid, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    select pp.id,
           pp.paper_id,
           case when p_query is not null and p.embedding is not null
                then (1 - (p.embedding <=> p_query))::real end as similarity
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and cardinality(coalesce(p_tags, '{}')) > 0
      and public.post_tags(pp.tags, p.tags) ?| p_tags
      and pp.posted_by is distinct from auth.uid()
      and not (pp.paper_id = any (coalesce(p_exclude, '{}')))
      and not exists (
          select 1 from public.paper_status ps
          where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
            and (ps.saved or ps.status <> 'unread' or ps.dismissed_at is not null)
      )
      and not exists (
          select 1 from public.reactions r
          where r.paper_id = p.id and r.team_id = p_team and r.user_id = auth.uid()
      )
      and not exists (
          select 1 from public.comments c
          where c.paper_id = p.id and c.team_id = p_team and c.author_id = auth.uid()
      )
    order by
      -- Nearest first when there is a vector; papers without an embedding (or
      -- every paper, on cold start) follow, newest first.
      (case when p_query is not null and p.embedding is not null
            then p.embedding <=> p_query end) asc nulls last,
      pp.posted_at desc,
      pp.id desc
    limit greatest(coalesce(p_limit, 12), 0);
$$;

create or replace function public.window_scores(
    p_team    uuid,
    p_since   timestamptz,
    p_query   extensions.vector(1024) default null,
    p_exclude uuid[] default '{}'
)
returns table(post_id uuid, paper_id uuid, tags jsonb, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    select pp.id,
           pp.paper_id,
           public.post_tags(pp.tags, p.tags),
           case when p_query is not null and p.embedding is not null
                then (1 - (p.embedding <=> p_query))::real end
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and pp.posted_at >= p_since
      and pp.posted_by is distinct from auth.uid()
      and not (pp.paper_id = any (coalesce(p_exclude, '{}')))
      and not exists (
          select 1 from public.paper_status ps
          where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
            and (ps.saved or ps.status <> 'unread' or ps.dismissed_at is not null)
      )
      and not exists (
          select 1 from public.reactions r
          where r.paper_id = p.id and r.team_id = p_team and r.user_id = auth.uid()
      )
      and not exists (
          select 1 from public.comments c
          where c.paper_id = p.id and c.team_id = p_team and c.author_id = auth.uid()
      )
    order by pp.posted_at desc, pp.id
    limit 500;
$$;
