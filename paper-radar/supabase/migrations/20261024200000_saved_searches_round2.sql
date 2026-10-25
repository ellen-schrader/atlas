-- 20261024200000_saved_searches_round2.sql — saved searches after a week of use
-- (issue #164; plan: docs/suggestions-feedback-plan.md).
--
--   1. position: the person's own order for their searches, highest priority
--      first. The Suggestions page groups papers by search in this order.
--   2. arxiv_categories: arXiv subjects a search keeps to on arXiv ("q-bio" =
--      all of quantitative biology, cross-lists included; "cs.LG" = one
--      subcategory); empty = all of arXiv. "flow matching" finds ~450 arXiv
--      papers a month, 9 of them in q-bio. New searches default to q-bio (in
--      the API); existing ones keep all of arXiv.
--   3. search_suggestion_searches: every search that found a suggestion, not
--      just the first (search_suggestions.saved_search_id, kept for that). A
--      paper two searches find shows under both, and is still one suggestion:
--      adding or dismissing it answers it everywhere.
--   4. pending_suggestions(): the person's waiting suggestions, the newest
--      few per search, so one noisy search cannot crowd the others out of the
--      page. pending_counts(): how many each search has waiting, counted here
--      rather than over rows PostgREST would cap at 1,000.
--   5. reorder_saved_searches(): the person's new order, in one statement.

-- === searches =================================================================

alter table public.saved_searches
    add column position smallint not null default 0,
    add column arxiv_categories text[] not null default '{}'
        check (cardinality(arxiv_categories) <= 20);

update public.saved_searches s
set position = r.n
from (
    select id, row_number() over (partition by user_id, team_id order by created_at) - 1 as n
    from public.saved_searches
) r
where r.id = s.id;

-- === which searches found a suggestion ========================================

create table public.search_suggestion_searches (
    suggestion_id   uuid not null references public.search_suggestions (id) on delete cascade,
    saved_search_id uuid not null references public.saved_searches (id) on delete cascade,
    primary key (suggestion_id, saved_search_id)
);

create index search_suggestion_searches_search_idx
    on public.search_suggestion_searches (saved_search_id);

alter table public.search_suggestion_searches enable row level security;
revoke all on public.search_suggestion_searches from public, anon, authenticated;
grant select, insert, update, delete on public.search_suggestion_searches to service_role;
select public.close_to_connectors('public.search_suggestion_searches');

insert into public.search_suggestion_searches (suggestion_id, saved_search_id)
select id, saved_search_id from public.search_suggestions where saved_search_id is not null;

-- === the page's list ===========================================================
-- Each waiting suggestion with the searches that found it, keeping those among
-- the newest p_per_search of at least one search (or of the suggestions no
-- remaining search found). Newest first.

create function public.pending_suggestions(p_user uuid, p_team uuid, p_per_search int)
returns table (id uuid, created_at timestamptz, search_ids uuid[])
language sql
stable
set search_path = ''
as $$
    with pending as (
        select s.id, s.created_at,
               coalesce(array_agg(l.saved_search_id order by l.saved_search_id)
                            filter (where l.saved_search_id is not null),
                        '{}') as search_ids
        from public.search_suggestions s
        left join public.search_suggestion_searches l on l.suggestion_id = s.id
        where s.user_id = p_user and s.team_id = p_team and s.status = 'pending'
        group by s.id
    ),
    ranked as (
        select p.id,
               row_number() over (partition by g order by p.created_at desc, p.id) as rn
        from pending p
        cross join lateral unnest(
            case when cardinality(p.search_ids) = 0 then array[null::uuid] else p.search_ids end
        ) as g
    )
    select p.id, p.created_at, p.search_ids
    from pending p
    where exists (select 1 from ranked r where r.id = p.id and r.rn <= p_per_search)
    order by p.created_at desc, p.id;
$$;

revoke all on function public.pending_suggestions(uuid, uuid, int) from public, anon, authenticated;
grant execute on function public.pending_suggestions(uuid, uuid, int) to service_role;

create function public.pending_counts(p_user uuid, p_team uuid)
returns table (saved_search_id uuid, pending bigint)
language sql
stable
set search_path = ''
as $$
    select l.saved_search_id, count(*)
    from public.search_suggestion_searches l
    join public.search_suggestions s on s.id = l.suggestion_id
    where s.user_id = p_user and s.team_id = p_team and s.status = 'pending'
    group by l.saved_search_id;
$$;

revoke all on function public.pending_counts(uuid, uuid) from public, anon, authenticated;
grant execute on function public.pending_counts(uuid, uuid) to service_role;

-- Positions 0.. in the order of p_ids, which must be exactly the person's
-- searches in the lab, each once. Returns false (and changes nothing) if not.
-- One statement, so two quick reorders cannot interleave into a mixed order.
create function public.reorder_saved_searches(p_user uuid, p_team uuid, p_ids uuid[])
returns boolean
language plpgsql
set search_path = ''
as $$
begin
    if cardinality(p_ids) <> (select count(distinct x) from unnest(p_ids) x)
       or (select array_agg(id order by id) from public.saved_searches
           where user_id = p_user and team_id = p_team)
          is distinct from (select array_agg(x order by x) from unnest(p_ids) x) then
        return false;
    end if;
    update public.saved_searches s
    set position = o.n - 1, updated_at = now()
    from unnest(p_ids) with ordinality as o(id, n)
    where s.id = o.id and s.user_id = p_user and s.team_id = p_team;
    return true;
end;
$$;

revoke all on function public.reorder_saved_searches(uuid, uuid, uuid[])
    from public, anon, authenticated;
grant execute on function public.reorder_saved_searches(uuid, uuid, uuid[]) to service_role;
