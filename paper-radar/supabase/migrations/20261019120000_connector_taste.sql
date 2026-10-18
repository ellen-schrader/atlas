-- 20261019120000_connector_taste.sql — let the Claude connector recommend the
-- way the app does (api/taste.py): from your profile and followed tags too.
--
-- Those live in public.profiles, which the connector lockdown
-- (20261017150000) closes to connector tokens, and should stay closed: it holds
-- every lab member's profile. Instead, one function returns the caller's OWN
-- recommendation inputs and nothing else, and the gate allows it alongside
-- recommend_tagged (the followed-tags search the app already uses).
--
-- security definer, because layer 2 of the lockdown denies a connector any
-- select on profiles; `where id = auth.uid()` is what keeps it to one row, the
-- caller's. No arguments, so there is no id to swap for someone else's.

create function public.my_recommendation_inputs()
returns table(
    display_name  text,
    profile_vec   extensions.vector(1024),
    profile_md    text,
    profile_md_us text,
    interests     jsonb
)
language sql
stable
security definer
set search_path = ''
as $$
    select p.display_name, p.profile_vec, p.profile_md, public.profile_md_us(p), p.interests
    from public.profiles p
    where p.id = auth.uid();
$$;

comment on function public.my_recommendation_inputs() is
    'The caller''s own profile inputs for recommendations (api/taste.py), for the Claude connector.';

revoke execute on function public.my_recommendation_inputs() from public, anon;
grant execute on function public.my_recommendation_inputs() to authenticated;


-- The gate, as in 20261017150000 with two more RPCs on the allowlist.
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
       or session !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
       or not exists (select 1 from auth.sessions s where s.id = session::uuid) then
        raise sqlstate 'PGRST' using
            message = json_build_object(
                'code', 'ATLAS_CONNECTOR_REVOKED',
                'message', 'This Claude connection has been revoked. Reconnect Atlas in Claude.')::text,
            detail = json_build_object('status', 401, 'headers', json_build_object())::text;
    end if;

    -- What the read-only paper tools use (atlas_mcp/lab.py), and nothing else.
    if (method in ('GET', 'HEAD')
        and ltrim(path, '/') = any (public.connector_readable_tables()))
       or (method = 'POST' and path in (
            '/rpc/search_papers', '/rpc/match_papers', '/rpc/recommend_papers',
            '/rpc/recommend_tagged', '/rpc/my_recommendation_inputs',
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

notify pgrst, 'reload config';
