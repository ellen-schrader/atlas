-- connector_lockdown_test.sql — a Claude connector (OAuth-client) token may only
-- read papers. Run with `supabase test db`.
--
-- A connector token is an ordinary user JWT plus `client_id`; these tests set that
-- claim (and a `session_id`) directly, the same way rls_isolation_test.sql sets `sub`.

begin;
select plan(20);

-- === seed ====================================================================

insert into auth.users (id, email) values
    ('0c000000-0000-0000-0000-00000000000a', 'connector-ada@lab.test');
insert into public.profiles (id, display_name) values
    ('0c000000-0000-0000-0000-00000000000a', 'Ada')
on conflict (id) do nothing;
insert into public.teams (id, name, slug, created_by) values
    ('0c111111-1111-1111-1111-111111111111', 'Lab C', 'lab-c-connector', '0c000000-0000-0000-0000-00000000000a');
insert into public.team_members (team_id, user_id, role) values
    ('0c111111-1111-1111-1111-111111111111', '0c000000-0000-0000-0000-00000000000a', 'owner');
insert into public.papers (id, url, url_norm, title) values
    ('0c100000-0000-0000-0000-000000000001', 'http://c/1', 'c/1', 'Connector paper');
insert into public.paper_posts (paper_id, team_id, posted_by, source) values
    ('0c100000-0000-0000-0000-000000000001', '0c111111-1111-1111-1111-111111111111',
     '0c000000-0000-0000-0000-00000000000a', 'web');
insert into public.team_visits (team_id, user_id) values
    ('0c111111-1111-1111-1111-111111111111', '0c000000-0000-0000-0000-00000000000a');
-- The connector's live session (revoking the grant deletes this row).
insert into auth.sessions (id, user_id) values
    ('0c5e5510-0000-0000-0000-000000000001', '0c000000-0000-0000-0000-00000000000a');

-- === coverage: nothing is open to connectors by omission ======================

select is(
    (select coalesce(string_agg(c.relname, ', ' order by c.relname), '')
       from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relkind = 'r'
        and c.relname not in ('teams', 'team_members', 'mcp_access', 'paper_posts', 'papers',
                              'paper_status', 'reactions', 'comments', 'mentions', 'mcp_tool_calls')
        and not exists (select 1 from pg_policies p
                         where p.schemaname = 'public' and p.tablename = c.relname
                           and p.policyname = 'connector_no_read' and p.permissive = 'RESTRICTIVE')),
    '',
    'every table outside the connector read-list has a restrictive connector_no_read policy '
    '(new table? select public.close_to_connectors(''public.<table>'') in its migration)'
);

select is(
    (select count(*)::int from pg_policies
      where schemaname = 'storage' and tablename = 'objects'
        and policyname = 'connector_no_storage' and permissive = 'RESTRICTIVE'),
    1, 'storage.objects is closed to connectors');

select ok(
    (select rolconfig::text like '%pgrst.db_pre_request=public.connector_request_guard%'
       from pg_roles where rolname = 'authenticator'),
    'PostgREST runs the connector gate before every request');

-- === layer 1: the pre-request gate ===========================================

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated",'
    '"client_id":"claude","session_id":"0c5e5510-0000-0000-0000-000000000001"}';

set local request.method to 'GET';
set local request.path to '/papers';
select lives_ok('select public.connector_request_guard()', 'connector may read papers');

set local request.path to '/paper_posts';
select lives_ok('select public.connector_request_guard()', 'connector may read lab posts');

set local request.method to 'POST';
set local request.path to '/rpc/search_papers';
select lives_ok('select public.connector_request_guard()', 'connector may search');

set local request.path to '/mcp_tool_calls';
select lives_ok('select public.connector_request_guard()', 'connector may write the audit log');

set local request.method to 'DELETE';
set local request.path to '/paper_posts';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector may not delete posts');

set local request.method to 'PATCH';
set local request.path to '/papers';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector may not edit papers');

set local request.method to 'POST';
set local request.path to '/rpc/set_member_role';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector may not call RLS-bypassing RPCs (set_member_role)');

set local request.path to '/rpc/set_mcp_access';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector may not switch Claude access itself');

set local request.path to '/rpc/graphql';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector may not use GraphQL');

set local request.method to 'GET';
set local request.path to '/team_integrations';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector may not read tables outside its list');

-- A revoked connection (session gone) is refused even for an allowed read.
set local request.path to '/papers';
set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated",'
    '"client_id":"claude","session_id":"0c5e5510-0000-0000-0000-0000000000ff"}';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'a revoked connector session is refused');

set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated","client_id":"claude"}';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'a connector token without a session is refused');

-- The web app's own session is untouched, whatever it asks for.
set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated"}';
set local request.method to 'POST';
set local request.path to '/rpc/set_member_role';
select lives_ok('select public.connector_request_guard()', 'web sessions are not gated');

-- === layer 2: embeds can't reach closed tables ================================

set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated",'
    '"client_id":"claude","session_id":"0c5e5510-0000-0000-0000-000000000001"}';
select is((select count(*)::int from public.paper_posts), 1,
    'connector still sees its lab''s posts (RLS as usual)');
select is((select count(*)::int from public.team_visits), 0,
    'connector reads nothing from a closed table, even its own rows');

set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated"}';
select is((select count(*)::int from public.team_visits), 1,
    'the web session still sees the same rows');

-- === layer 3: storage ========================================================

set local request.jwt.claims to
    '{"sub":"0c000000-0000-0000-0000-00000000000a","role":"authenticated",'
    '"client_id":"claude","session_id":"0c5e5510-0000-0000-0000-000000000001"}';
select throws_ok(
    $$insert into storage.objects (bucket_id, name, owner)
      values ('figures', '0c111111-1111-1111-1111-111111111111/x.png',
              '0c000000-0000-0000-0000-00000000000a')$$,
    '42501', null, 'connector may not upload to Storage');

reset role;
select * from finish();
rollback;
