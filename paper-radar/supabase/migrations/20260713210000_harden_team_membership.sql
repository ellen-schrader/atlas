-- 20260713210000_harden_team_membership.sql
-- Security fix (pre-public audit C1 / H1): lock down team membership.
--
-- Before this migration ANY authenticated user could run, from the browser,
--   supabase.from('team_members').insert({team_id: <any lab>, user_id: me, role: 'owner'})
-- and succeed — insert/delete were granted to `authenticated` and the INSERT
-- policy only checked `user_id = auth.uid()` (team_id and role unconstrained).
-- That is a full cross-tenant read/write + lab takeover. Joining was also
-- possible by guessing a lab's name-derived slug via join_team_by_slug.
--
-- Fix: clients can no longer write team_members directly. Every membership
-- change goes through a SECURITY DEFINER RPC that enforces invites and
-- owner-only role changes. The join code becomes a high-entropy, revocable
-- secret stored separately from the (public) display slug.

-- === 1. Revoke direct writes; drop the permissive write policies ============
revoke insert, update, delete on public.team_members from authenticated;

drop policy if exists team_members_insert on public.team_members;
drop policy if exists team_members_delete on public.team_members;
-- team_members_select stays: members may still see their co-members.

-- === 2. High-entropy join code, separate from the (public) display slug ======
create or replace function public.gen_join_code()
returns text
language sql
volatile
set search_path = extensions, public
as $$
    -- 16 random bytes = 128 bits of entropy, hex-encoded.
    select encode(extensions.gen_random_bytes(16), 'hex');
$$;
revoke all on function public.gen_join_code() from public;

alter table public.teams add column if not exists join_code text;

-- Backfill every existing lab with a fresh code. The old slug is no longer a
-- credential, so anyone who previously saw a slug can no longer join with it.
update public.teams set join_code = public.gen_join_code() where join_code is null;

alter table public.teams alter column join_code set not null;
alter table public.teams alter column join_code set default public.gen_join_code();
create unique index if not exists teams_join_code_key on public.teams (join_code);

-- === 3. create_team: mint the invite code server-side ========================
create or replace function public.create_team(p_name text, p_slug text)
returns public.teams
language plpgsql
security definer
set search_path = public
as $$
declare
    t public.teams;
begin
    insert into public.teams (name, slug, created_by, join_code)
    values (p_name, p_slug, auth.uid(), public.gen_join_code())
    returning * into t;

    insert into public.team_members (team_id, user_id, role)
    values (t.id, auth.uid(), 'owner');

    return t;
end;
$$;

-- === 4. Join by the high-entropy code, not the guessable slug ================
create or replace function public.join_team_by_code(p_code text)
returns public.teams
language plpgsql
security definer
set search_path = public
as $$
declare
    t public.teams;
begin
    select * into t from public.teams where join_code = trim(p_code);
    if t.id is null then
        raise exception 'No lab found for that invite code'
            using errcode = 'no_data_found';
    end if;

    insert into public.team_members (team_id, user_id, role)
    values (t.id, auth.uid(), 'member')     -- role is hard-coded; never client-chosen
    on conflict (team_id, user_id) do nothing;

    return t;
end;
$$;

-- Retire the slug-based join path entirely.
drop function if exists public.join_team_by_slug(text);

grant execute on function public.join_team_by_code(text) to authenticated;

-- === 5. regenerate_team_code: rotate the invite code =========================
-- Previously produced 8 hex chars (~32 bits) from non-crypto random() and
-- rotated the *display slug*. Now emits a fresh 128-bit code.
create or replace function public.regenerate_team_code(p_team uuid)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
    new_code text;
begin
    if not is_team_owner(p_team) then
        raise exception 'Only an owner can regenerate the invite code'
            using errcode = '42501';
    end if;
    new_code := public.gen_join_code();
    update teams set join_code = new_code where id = p_team;
    return new_code;
end;
$$;
