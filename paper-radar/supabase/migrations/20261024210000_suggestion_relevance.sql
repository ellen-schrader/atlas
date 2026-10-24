-- 20261024210000_suggestion_relevance.sql — sort suggestions by how well they
-- fit the person (issue #164; plan: docs/suggestions-feedback-plan.md §5).
--
-- The daily job embeds each candidate a search found and someone is waiting
-- on (title + abstract, the same Voyage model as papers.embedding), once
-- however many people it is suggested to. The page then scores each waiting
-- suggestion against the person's taste vector (api/taste.py: their profile
-- blended with what they posted, saved, reacted to and discussed) and sorts
-- each search's papers by it.
--
-- On Voyage's free tier (4 texts a request, 3 requests a minute) the job
-- embeds ~120 a day in a 10-minute budget; tokens are well inside the free
-- allowance, so this costs nothing.

alter table public.search_candidates
    add column embedding extensions.vector(1024),
    add column embedded_at timestamptz;

-- The job's to-do list: newest unembedded first.
create index search_candidates_unembedded_idx
    on public.search_candidates (first_seen_at desc) where embedding is null;

-- pending_suggestions() gains the person's taste vector and returns each
-- suggestion's cosine similarity to it (-1..1; null when either side has no
-- vector). With a vector, each search's window is its best-fitting
-- p_per_search rather than its newest, so a good older paper is not cut.
drop function public.pending_suggestions(uuid, uuid, int);

create function public.pending_suggestions(
    p_user uuid,
    p_team uuid,
    p_per_search int,
    p_taste extensions.vector(1024) default null
)
returns table (id uuid, created_at timestamptz, search_ids uuid[], score real)
language sql
stable
set search_path = public, extensions
as $$
    with pending as (
        select s.id, s.created_at,
               coalesce(array_agg(l.saved_search_id order by l.saved_search_id)
                            filter (where l.saved_search_id is not null),
                        '{}') as search_ids,
               -- A zero vector gives NaN: no score rather than a broken one.
               nullif((1 - (c.embedding <=> p_taste))::real, 'NaN') as score
        from public.search_suggestions s
        join public.search_candidates c on c.id = s.candidate_id
        left join public.search_suggestion_searches l on l.suggestion_id = s.id
        where s.user_id = p_user and s.team_id = p_team and s.status = 'pending'
        group by s.id, c.id  -- c.id is the key: its embedding comes along
    ),
    ranked as (
        select p.id,
               row_number() over (
                   partition by g
                   order by p.score desc nulls last, p.created_at desc, p.id
               ) as rn
        from pending p
        cross join lateral unnest(
            case when cardinality(p.search_ids) = 0 then array[null::uuid] else p.search_ids end
        ) as g
    )
    select p.id, p.created_at, p.search_ids, p.score
    from pending p
    where exists (select 1 from ranked r where r.id = p.id and r.rn <= p_per_search)
    order by p.created_at desc, p.id;
$$;

revoke all on function public.pending_suggestions(uuid, uuid, int, extensions.vector)
    from public, anon, authenticated;
grant execute on function public.pending_suggestions(uuid, uuid, int, extensions.vector)
    to service_role;
