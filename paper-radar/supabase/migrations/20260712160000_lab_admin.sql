-- 20260712160000_lab_admin.sql — owner-only lab management RPCs.
--
-- All are SECURITY DEFINER and enforce owner-only access internally; each guards
-- against orphaning the lab (a lab must always keep at least one owner).

create or replace function public.rename_team(p_team uuid, p_name text)
returns void
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not is_team_owner(p_team) then
    raise exception 'Only an owner can rename the lab' using errcode = '42501';
  end if;
  if coalesce(trim(p_name), '') = '' then
    raise exception 'Lab name is required';
  end if;
  update teams set name = trim(p_name) where id = p_team;
end;
$$;

create or replace function public.regenerate_team_code(p_team uuid)
returns text
language plpgsql
security definer
set search_path to 'public'
as $$
declare
  new_slug text;
begin
  if not is_team_owner(p_team) then
    raise exception 'Only an owner can regenerate the join code' using errcode = '42501';
  end if;
  loop
    new_slug := substr(md5(random()::text || clock_timestamp()::text), 1, 8);
    exit when not exists (select 1 from teams where slug = new_slug);
  end loop;
  update teams set slug = new_slug where id = p_team;
  return new_slug;
end;
$$;

create or replace function public.remove_member(p_team uuid, p_user uuid)
returns void
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not is_team_owner(p_team) then
    raise exception 'Only an owner can remove members' using errcode = '42501';
  end if;
  if (select role from team_members where team_id = p_team and user_id = p_user) = 'owner'
     and (select count(*) from team_members where team_id = p_team and role = 'owner') <= 1 then
    raise exception 'Cannot remove the last owner';
  end if;
  delete from team_members where team_id = p_team and user_id = p_user;
end;
$$;

create or replace function public.set_member_role(p_team uuid, p_user uuid, p_role text)
returns void
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if not is_team_owner(p_team) then
    raise exception 'Only an owner can change roles' using errcode = '42501';
  end if;
  if p_role not in ('owner', 'member') then
    raise exception 'Invalid role';
  end if;
  if p_role = 'member'
     and (select role from team_members where team_id = p_team and user_id = p_user) = 'owner'
     and (select count(*) from team_members where team_id = p_team and role = 'owner') <= 1 then
    raise exception 'Cannot demote the last owner';
  end if;
  update team_members set role = p_role where team_id = p_team and user_id = p_user;
end;
$$;

create or replace function public.leave_team(p_team uuid)
returns void
language plpgsql
security definer
set search_path to 'public'
as $$
begin
  if (select role from team_members where team_id = p_team and user_id = auth.uid()) = 'owner'
     and (select count(*) from team_members where team_id = p_team and role = 'owner') <= 1 then
    raise exception 'Promote another owner before leaving the lab';
  end if;
  delete from team_members where team_id = p_team and user_id = auth.uid();
end;
$$;

grant execute on function public.rename_team(uuid, text) to authenticated;
grant execute on function public.regenerate_team_code(uuid) to authenticated;
grant execute on function public.remove_member(uuid, uuid) to authenticated;
grant execute on function public.set_member_role(uuid, uuid, text) to authenticated;
grant execute on function public.leave_team(uuid) to authenticated;
