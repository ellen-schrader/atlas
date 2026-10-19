-- 20261019150000_feature_flags.sql — per-lab and per-person feature switches.
--
-- Atlas had no feature flags: "Beta" is only a label in the sidebar. Clinical
-- trials (docs/CLINICAL_TRIALS_PLAN.md) ships dark: merged to main, hidden from
-- everyone until it is switched on, first for one person, then for one lab.
--
--   * team_features: everyone in the lab gets the feature.
--   * user_features: only that person gets it, in every lab they belong to.
--     The data stays the lab's (rows are keyed by team_id); the switch only
--     decides who can see it.
--
-- Switching is done by the service role (a migration, or a script run by hand
-- locally). Nobody can switch a feature on for themselves: neither table has a
-- policy or a grant for anon or authenticated.

create table public.team_features (
    team_id    uuid not null references public.teams (id) on delete cascade,
    feature    text not null check (feature ~ '^[a-z][a-z0-9_]*$'),
    enabled_at timestamptz not null default now(),
    primary key (team_id, feature)
);

create table public.user_features (
    user_id    uuid not null references public.profiles (id) on delete cascade,
    feature    text not null check (feature ~ '^[a-z][a-z0-9_]*$'),
    enabled_at timestamptz not null default now(),
    primary key (user_id, feature)
);

alter table public.team_features enable row level security;
alter table public.user_features enable row level security;
revoke all on public.team_features, public.user_features from public, anon, authenticated;
grant select, insert, update, delete on public.team_features, public.user_features to service_role;
-- And to Claude connectors, like every table outside their read-list.
select public.close_to_connectors('public.team_features');
select public.close_to_connectors('public.user_features');

-- Whether the caller may use `f` in lab `t`: a member of the lab, and the
-- feature is on for the lab or for them. RLS on a feature's tables calls this,
-- so a lab without the switch reads nothing even straight from PostgREST.
create function public.has_feature(t uuid, f text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.is_team_member(t)
       and (
           exists (select 1 from public.team_features where team_id = t and feature = f)
        or exists (select 1 from public.user_features where user_id = auth.uid() and feature = f)
       );
$$;

-- The features the caller has in lab `t` (empty when not a member), for the
-- web app to decide what to show. It only ever answers for the caller.
create function public.my_features(t uuid)
returns text[]
language sql
stable
security definer
set search_path = public
as $$
    select coalesce(array_agg(distinct feature order by feature), '{}')
      from (
          select feature from public.team_features where team_id = t
          union
          select feature from public.user_features where user_id = auth.uid()
      ) f
     where public.is_team_member(t);
$$;

-- The labs where `f` is in use for anyone: switched on for the lab, or for one
-- of its members. Background jobs (linking papers to trials) run for these
-- labs only. Service role only: it lists labs and who is trying what.
create function public.feature_teams(f text)
returns setof uuid
language sql
stable
security definer
set search_path = public
as $$
    select team_id from public.team_features where feature = f
    union
    select m.team_id
      from public.user_features u
      join public.team_members m on m.user_id = u.user_id
     where u.feature = f;
$$;

-- Named roles too, as in 20261010140000: default privileges can grant anon and
-- authenticated EXECUTE directly, which revoking from public misses.
revoke execute on function public.has_feature(uuid, text) from public, anon;
revoke execute on function public.my_features(uuid) from public, anon;
revoke execute on function public.feature_teams(text) from public, anon, authenticated;
grant execute on function public.has_feature(uuid, text) to authenticated, service_role;
grant execute on function public.my_features(uuid) to authenticated, service_role;
grant execute on function public.feature_teams(text) to service_role;
