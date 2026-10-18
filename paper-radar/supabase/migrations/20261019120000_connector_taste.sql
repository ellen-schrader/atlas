-- 20261019120000_connector_taste.sql — let the Claude connector recommend the
-- way the app does (api/taste.py): from your profile and followed tags too.
--
-- Those live in public.profiles, which the connector lockdown
-- (20261017150000) closes to connector tokens, and should stay closed: it holds
-- every lab member's profile. Instead, one function returns the caller's OWN
-- recommendation inputs and nothing else, and the gate allows it alongside
-- recommend_tagged (the followed-tags search the app already uses) and
-- window_scores (below, for the digest).
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


-- The digest's "For you" (atlas_mcp/lab.py): every post in a recent window that
-- recommend_papers would consider for you, scored against one of your signals —
-- just the numbers, so ranking stays in Postgres and no embeddings travel. The
-- whole window comes back on purpose: the picks keep each signal's top quarter,
-- which needs the full spread. Exact distances, no index: a window is small.
--
-- Eligibility is recommend_papers' (20261019100000): not your own post, not one
-- in p_exclude (your Teams posts), nothing you've saved, started, reacted to or
-- commented on. security invoker, so RLS scopes it to labs you're in.
create function public.window_scores(
    p_team    uuid,
    p_since   timestamptz,
    p_query   extensions.vector(1024) default null,
    p_exclude uuid[] default '{}'
)
returns table(post_id uuid, paper_id uuid, tags jsonb, similarity real)
language sql
stable
set search_path = public, extensions
as $$
    select pp.id,
           pp.paper_id,
           public.post_tags(pp.tags, p.tags),
           case when p_query is not null and p.embedding is not null
                then (1 - (p.embedding <=> p_query))::real end
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and pp.posted_at >= p_since
      and pp.posted_by is distinct from auth.uid()
      and not (pp.paper_id = any (coalesce(p_exclude, '{}')))
      and not exists (
          select 1 from public.paper_status ps
          where ps.paper_id = p.id and ps.team_id = p_team and ps.user_id = auth.uid()
            and (ps.saved or ps.status <> 'unread')
      )
      and not exists (
          select 1 from public.reactions r
          where r.paper_id = p.id and r.team_id = p_team and r.user_id = auth.uid()
      )
      and not exists (
          select 1 from public.comments c
          where c.paper_id = p.id and c.team_id = p_team and c.author_id = auth.uid()
      )
    order by pp.posted_at desc, pp.id
    limit 500;
$$;

revoke execute on function public.window_scores(uuid, timestamptz, extensions.vector, uuid[])
    from public, anon;
grant execute on function public.window_scores(uuid, timestamptz, extensions.vector, uuid[])
    to authenticated;


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
            '/rpc/recommend_tagged', '/rpc/my_recommendation_inputs', '/rpc/window_scores',
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
