-- 20260713090000_mcp_access.sql — owner-controlled MCP access, and an audit log.
--
-- Connecting Claude to a lab is not a personal decision: the MCP server reads the
-- lab's shared corpus (papers, post notes, who posted them, the mood board) and,
-- since `post_paper`, can WRITE into it — a paper plus a comment that @-mentions a
-- teammate. One member wiring up a model on their laptop therefore acts on behalf
-- of everyone in the lab.
--
-- So: an owner turns it on, and every call is logged where the whole lab can see it.
--
-- Note on scope: the server does NOT read `comments` or `reactions` (see
-- PAPER_COLUMNS / POST_COLUMNS in atlas_mcp/lab.py — the comments table appears
-- only in the write path). There is deliberately no "hide my engagement" flag here,
-- because there is nothing for it to hide.

create table public.mcp_access (
    team_id    uuid primary key references public.teams (id) on delete cascade,
    enabled    boolean     not null default false,
    enabled_by uuid        references public.profiles (id) on delete set null,
    updated_at timestamptz not null default now()
);

-- Every tool call the MCP server makes, attributed to the member whose credentials
-- it ran under. The point is that a lab can *see* what Claude looked at.
create table public.mcp_tool_calls (
    id        bigint generated always as identity primary key,
    team_id   uuid        not null references public.teams (id) on delete cascade,
    user_id   uuid        references public.profiles (id) on delete set null,
    tool      text        not null,
    ok        boolean     not null default true,
    called_at timestamptz not null default now()
);
create index mcp_tool_calls_team_idx on public.mcp_tool_calls (team_id, called_at desc);

alter table public.mcp_access     enable row level security;
alter table public.mcp_tool_calls enable row level security;

-- Any member can see whether MCP is on, and what Claude has been doing. That
-- visibility is the whole point — a log only the connector can read is not a check.
create policy mcp_access_select on public.mcp_access for select
    to authenticated using (is_team_member(team_id));

create policy mcp_tool_calls_select on public.mcp_tool_calls for select
    to authenticated using (is_team_member(team_id));

-- Members write their own call log rows (the server runs as the member).
-- They may not rewrite history: no update, no delete policy exists.
create policy mcp_tool_calls_insert on public.mcp_tool_calls for insert
    to authenticated with check (is_team_member(team_id) and user_id = auth.uid());

-- === grants (RLS still restricts rows) =====================================
-- Deliberately narrow: the log is append-only to everyone, so nobody — not even an
-- owner — can quietly edit or delete what Claude did. `mcp_access` is read-only at
-- the table level; the only way to change it is the owner-guarded RPC below.
grant select         on public.mcp_access     to authenticated;
grant select, insert on public.mcp_tool_calls to authenticated;

-- Enabling/disabling is owner-only, via an RPC rather than a table policy so the
-- refusal is a clear error instead of a silently-filtered zero-row write.
create function public.set_mcp_access(p_team uuid, p_enabled boolean)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
    if not is_team_owner(p_team) then
        raise exception 'Only an owner can change Claude access for this lab'
            using errcode = '42501';
    end if;

    insert into public.mcp_access (team_id, enabled, enabled_by, updated_at)
    values (p_team, p_enabled, auth.uid(), now())
    on conflict (team_id) do update
        set enabled    = excluded.enabled,
            enabled_by = excluded.enabled_by,
            updated_at = now();

    return p_enabled;
end;
$$;

grant execute on function public.set_mcp_access(uuid, boolean) to authenticated;
