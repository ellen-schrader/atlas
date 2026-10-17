-- Connector lockdown (docs/CLAUDE_CONNECTOR_PLAN.md, M2).
--
-- The Claude connector signs users in through Supabase's OAuth 2.1 server. The
-- tokens it receives are ordinary user JWTs, plus a `client_id` claim: anywhere they
-- reach, they act with the user's full rights, and Anthropic's servers hold them.
-- The connector only needs to *read papers*, so that is all such a token may do here.
--
-- Three layers, because no single one covers every path:
--
--   1. A PostgREST pre-request gate (default-deny). Every Data API request carrying
--      a connector token must match a short allowlist of reads (plus the audit-log
--      insert). That covers every table, every RPC — including the SECURITY DEFINER
--      ones that bypass RLS (create_team, set_member_role, set_mcp_access, …) —
--      GraphQL (/rpc/graphql), and anything added later. It also refuses a token
--      whose session has been revoked, which a JWT alone would outlive by up to an
--      hour.
--   2. Restrictive SELECT policies on every other table, so a resource embedded in
--      an allowed read (`papers?select=*,paper_edits(*)`) can't pull in a table the
--      gate would have refused at the top level.
--   3. A restrictive policy on storage.objects: Storage is its own service, not
--      behind the gate.
--
-- Ordinary web sessions carry no `client_id` and are untouched by all three.
-- Adding a table? It's closed to connectors automatically at layer 1; add it to
-- layer 2 with public.close_to_connectors() — supabase/tests/connector_lockdown_test.sql
-- fails until you do.

-- Is this request authenticated with a connector (OAuth-client) token?
create or replace function public.is_connector()
returns boolean
language sql
stable
set search_path = ''
as $$
    select (auth.jwt() ->> 'client_id') is not null;
$$;

comment on function public.is_connector() is
    'True when the request uses a token issued to an OAuth client (the Claude connector).';


-- Layer 1. Runs before every PostgREST request, as the request's role.
create or replace function public.connector_request_guard()
returns void
language plpgsql
stable
security definer  -- reads auth.sessions, which the request role cannot
set search_path = ''
as $$
declare
    claims  jsonb := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
    method  text  := current_setting('request.method', true);
    path    text  := current_setting('request.path', true);
    session text;
begin
    if claims is null or claims ->> 'client_id' is null then
        return;  -- not a connector: the web app, anon, service role
    end if;

    -- Revoking the grant deletes the session; the access token would otherwise keep
    -- working until it expires.
    session := claims ->> 'session_id';
    if session is null
       or session !~ '^[0-9a-fA-F-]{36}$'
       or not exists (select 1 from auth.sessions s where s.id = session::uuid) then
        raise sqlstate 'PGRST' using
            message = json_build_object(
                'code', 'ATLAS_CONNECTOR_REVOKED',
                'message', 'This Claude connection has been revoked. Reconnect Atlas in Claude.')::text,
            detail = json_build_object('status', 401, 'headers', json_build_object())::text;
    end if;

    -- What the read-only paper tools use (atlas_mcp/lab.py), and nothing else.
    if (method in ('GET', 'HEAD') and path in (
            '/teams', '/team_members', '/mcp_access',
            '/paper_posts', '/papers', '/paper_status', '/reactions',
            '/comments', '/mentions'))
       or (method = 'POST' and path in (
            '/rpc/search_papers', '/rpc/match_papers', '/rpc/recommend_papers',
            '/mcp_tool_calls'))  -- the lab's audit log of what Claude did
    then
        return;
    end if;

    raise sqlstate 'PGRST' using
        message = json_build_object(
            'code', 'ATLAS_CONNECTOR_FORBIDDEN',
            'message', 'Claude connections can only read papers.')::text,
        detail = json_build_object('status', 403, 'headers', json_build_object())::text;
end;
$$;

comment on function public.connector_request_guard() is
    'PostgREST pre-request gate: connector tokens may only make the reads the paper tools need.';

alter role authenticator set pgrst.db_pre_request = 'public.connector_request_guard';
notify pgrst, 'reload config';


-- Layer 2. Tables a connector may read (layer 1's GET list) plus the audit log,
-- whose insert returns the row it wrote.
create or replace function public.close_to_connectors(t regclass)
returns void
language plpgsql
set search_path = ''
as $$
begin
    execute format(
        'create policy connector_no_read on %s as restrictive for select '
        'to authenticated using (not public.is_connector())',
        t
    );
end;
$$;

revoke execute on function public.close_to_connectors(regclass) from public, anon, authenticated;

do $$
declare
    t regclass;
begin
    for t in
        select c.oid::regclass
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public'
          and c.relkind = 'r'
          and c.relname not in (
              'teams', 'team_members', 'mcp_access', 'paper_posts', 'papers',
              'paper_status', 'reactions', 'comments', 'mentions', 'mcp_tool_calls')
    loop
        perform public.close_to_connectors(t);
    end loop;
end;
$$;


-- Layer 3. Storage (figures, uploads) is off limits to connectors entirely.
create policy connector_no_storage on storage.objects
    as restrictive for all to authenticated
    using (not public.is_connector())
    with check (not public.is_connector());
