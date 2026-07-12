-- 0002_rls.sql — Row-Level Security: lab isolation lives in the database.
-- See docs/MIGRATION_PLAN.md §7.
--
-- The app never hand-filters by team. Every table below is readable/writable
-- only for teams the current user belongs to; `papers` is reachable only via a
-- post in one of the user's labs. Canonical papers / embeddings / trends are
-- written by the Python worker using the service_role key, which bypasses RLS.

-- === membership helpers ====================================================
-- SECURITY DEFINER so they read team_members WITHOUT triggering RLS recursion
-- (a policy on team_members that queried team_members directly would recurse).

create function public.is_team_member(t uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.team_members
        where team_id = t and user_id = auth.uid()
    );
$$;

create function public.user_in_team(u uuid, t uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.team_members
        where team_id = t and user_id = u
    );
$$;

create function public.shares_team_with(other uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.team_members a
        join public.team_members b on a.team_id = b.team_id
        where a.user_id = auth.uid() and b.user_id = other
    );
$$;

-- === grants (RLS still restricts rows) =====================================

grant usage on schema public to authenticated, service_role;

grant select, insert, update            on public.profiles      to authenticated;
grant select, insert                    on public.teams         to authenticated;
grant select, insert, delete            on public.team_members  to authenticated;
grant select                            on public.papers        to authenticated;
grant select, insert, delete            on public.paper_posts   to authenticated;
grant select, insert, delete            on public.comments      to authenticated;
grant select, insert, delete            on public.reactions     to authenticated;
grant select, insert, update, delete    on public.paper_status  to authenticated;
grant select, insert, update            on public.mentions      to authenticated;
grant select                            on public.trends        to authenticated;

-- The worker/ingest service uses service_role for canonical writes.
grant all on all tables in schema public to service_role;

-- === enable RLS ============================================================

alter table public.profiles      enable row level security;
alter table public.teams         enable row level security;
alter table public.team_members  enable row level security;
alter table public.papers        enable row level security;
alter table public.paper_posts   enable row level security;
alter table public.comments      enable row level security;
alter table public.reactions     enable row level security;
alter table public.paper_status  enable row level security;
alter table public.mentions      enable row level security;
alter table public.trends        enable row level security;

-- === policies ==============================================================

-- profiles: read yourself + teammates; edit only yourself; bootstrap yourself.
create policy profiles_select on public.profiles for select
    using (id = auth.uid() or public.shares_team_with(id));
create policy profiles_insert on public.profiles for insert
    with check (id = auth.uid());
create policy profiles_update on public.profiles for update
    using (id = auth.uid()) with check (id = auth.uid());

-- teams: members see their labs; anyone may create a lab (they add themselves
-- to team_members next).
create policy teams_select on public.teams for select
    using (public.is_team_member(id));
create policy teams_insert on public.teams for insert
    with check (created_by = auth.uid());

-- team_members: members see co-members; you may add yourself (create/join a lab).
create policy team_members_select on public.team_members for select
    using (public.is_team_member(team_id));
create policy team_members_insert on public.team_members for insert
    with check (user_id = auth.uid());
create policy team_members_delete on public.team_members for delete
    using (user_id = auth.uid());

-- papers (global): visible only if one of your labs has posted it.
create policy papers_select on public.papers for select
    using (exists (
        select 1 from public.paper_posts p
        where p.paper_id = papers.id and public.is_team_member(p.team_id)
    ));
-- (No insert/update policy => authenticated cannot write papers; worker uses service_role.)

-- paper_posts: the visibility boundary.
create policy paper_posts_select on public.paper_posts for select
    using (public.is_team_member(team_id));
create policy paper_posts_insert on public.paper_posts for insert
    with check (public.is_team_member(team_id) and posted_by = auth.uid());
create policy paper_posts_delete on public.paper_posts for delete
    using (public.is_team_member(team_id) and posted_by = auth.uid());

-- comments: read within the lab; write/delete your own.
create policy comments_select on public.comments for select
    using (public.is_team_member(team_id));
create policy comments_insert on public.comments for insert
    with check (public.is_team_member(team_id) and author_id = auth.uid());
create policy comments_delete on public.comments for delete
    using (author_id = auth.uid());

-- reactions: read within the lab; toggle your own.
create policy reactions_select on public.reactions for select
    using (public.is_team_member(team_id));
create policy reactions_insert on public.reactions for insert
    with check (public.is_team_member(team_id) and user_id = auth.uid());
create policy reactions_delete on public.reactions for delete
    using (public.is_team_member(team_id) and user_id = auth.uid());

-- paper_status: strictly personal (the mention trigger writes others' rows as
-- SECURITY DEFINER, bypassing these policies).
create policy paper_status_select on public.paper_status for select
    using (user_id = auth.uid() and public.is_team_member(team_id));
create policy paper_status_insert on public.paper_status for insert
    with check (user_id = auth.uid() and public.is_team_member(team_id));
create policy paper_status_update on public.paper_status for update
    using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy paper_status_delete on public.paper_status for delete
    using (user_id = auth.uid());

-- mentions: read within the lab; you may @-mention a co-member; only the
-- mentioned user may mark their mention seen.
create policy mentions_select on public.mentions for select
    using (public.is_team_member(team_id));
create policy mentions_insert on public.mentions for insert
    with check (
        public.is_team_member(team_id)
        and mentioned_by = auth.uid()
        and public.user_in_team(mentioned_user, team_id)
    );
create policy mentions_update on public.mentions for update
    using (mentioned_user = auth.uid()) with check (mentioned_user = auth.uid());

-- trends: read within the lab; written by the worker (service_role).
create policy trends_select on public.trends for select
    using (public.is_team_member(team_id));
