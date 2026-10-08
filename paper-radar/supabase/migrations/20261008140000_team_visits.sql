-- 20261008140000_team_visits.sql — "7 new papers in TME Lab since your last visit."
-- (docs/dashboard.md §3.1)
--
-- One row per (user, lab): when that user last looked at the lab's Home. Home
-- reads the count on arrival and stamps the visit after 10 seconds on the page
-- (or when it leaves), so the number shown isn't reset under the reader.
--
-- Your own posts are not "new" to you. A user with no row yet (first visit since
-- this shipped) gets NULL, not a count of the lab's whole history: the client
-- shows its generic subtitle instead.

create table public.team_visits (
    user_id      uuid not null references public.profiles(id) on delete cascade,
    team_id      uuid not null references public.teams(id)    on delete cascade,
    last_seen_at timestamptz not null default now(),
    primary key (user_id, team_id)
);

alter table public.team_visits enable row level security;

-- Only your own rows, and only for labs you belong to.
create policy team_visits_select on public.team_visits for select
    using (user_id = auth.uid() and public.is_team_member(team_id));
create policy team_visits_insert on public.team_visits for insert
    with check (user_id = auth.uid() and public.is_team_member(team_id));
create policy team_visits_update on public.team_visits for update
    using (user_id = auth.uid() and public.is_team_member(team_id))
    with check (user_id = auth.uid() and public.is_team_member(team_id));

grant select, insert, update on public.team_visits to authenticated;

-- Posts shared by someone else since the caller's last visit; NULL before the
-- first one. Security invoker: paper_posts' RLS keeps it to the caller's labs.
create or replace function public.new_since_last_visit(p_team uuid)
returns integer
language sql
stable
set search_path = public
as $$
    select (
        select count(*)::int
        from public.paper_posts pp
        where pp.team_id = p_team
          and pp.posted_at > v.last_seen_at
          and pp.posted_by is distinct from auth.uid()
    )
    from public.team_visits v
    where v.user_id = auth.uid() and v.team_id = p_team;
$$;

-- Stamp the caller's visit to a lab. The insert policy refuses a lab the caller
-- isn't in, so this can't create rows for other people's labs.
create or replace function public.mark_team_visit(p_team uuid)
returns void
language sql
volatile
set search_path = public
as $$
    insert into public.team_visits (user_id, team_id, last_seen_at)
    values (auth.uid(), p_team, now())
    on conflict (user_id, team_id) do update set last_seen_at = excluded.last_seen_at;
$$;

grant execute on function public.new_since_last_visit(uuid) to authenticated;
grant execute on function public.mark_team_visit(uuid)      to authenticated;
