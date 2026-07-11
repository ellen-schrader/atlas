-- 20260711163828_team_rpcs.sql — onboarding RPCs.
--
-- Why RPCs (SECURITY DEFINER) rather than plain client inserts:
--   * create_team must insert a team AND the owner's membership atomically.
--   * join_team_by_slug must look a lab up by slug — but RLS deliberately hides
--     labs you're not a member of, so a client SELECT can't find it. The slug
--     acts as a lightweight join code here; replace with real invites later.

create function public.create_team(p_name text, p_slug text)
returns public.teams
language plpgsql
security definer
set search_path = public
as $$
declare
    t public.teams;
begin
    insert into public.teams (name, slug, created_by)
    values (p_name, p_slug, auth.uid())
    returning * into t;

    insert into public.team_members (team_id, user_id, role)
    values (t.id, auth.uid(), 'owner');

    return t;
end;
$$;

create function public.join_team_by_slug(p_slug text)
returns public.teams
language plpgsql
security definer
set search_path = public
as $$
declare
    t public.teams;
begin
    select * into t from public.teams where slug = p_slug;
    if t.id is null then
        raise exception 'No lab found with code "%"', p_slug using errcode = 'no_data_found';
    end if;

    insert into public.team_members (team_id, user_id, role)
    values (t.id, auth.uid(), 'member')
    on conflict (team_id, user_id) do nothing;

    return t;
end;
$$;

grant execute on function public.create_team(text, text) to authenticated;
grant execute on function public.join_team_by_slug(text) to authenticated;
