-- connector_taste_test.sql — the Claude connector may read the caller's OWN
-- recommendation inputs (20261019120000_connector_taste.sql), and nothing more of
-- profiles. Run with `supabase test db`.

begin;
select plan(7);

insert into auth.users (id, email) values
    ('0d000000-0000-0000-0000-00000000000a', 'taste-ada@lab.test'),
    ('0d000000-0000-0000-0000-00000000000b', 'taste-bo@lab.test');
insert into public.profiles (id, display_name) values
    ('0d000000-0000-0000-0000-00000000000a', 'Ada Lovelace'),
    ('0d000000-0000-0000-0000-00000000000b', 'Bo Chen')
on conflict (id) do update set display_name = excluded.display_name;
update public.profiles
   set profile_md = 'Tumour microenvironment', interests = '["spatial-omics"]'
 where id = '0d000000-0000-0000-0000-00000000000a';
update public.profiles
   set profile_md = 'Bo''s private research notes'
 where id = '0d000000-0000-0000-0000-00000000000b';
insert into auth.sessions (id, user_id) values
    ('0d5e5510-0000-0000-0000-000000000001', '0d000000-0000-0000-0000-00000000000a');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"0d000000-0000-0000-0000-00000000000a","role":"authenticated",'
    '"client_id":"claude","session_id":"0d5e5510-0000-0000-0000-000000000001"}';

-- The gate lets the two new reads through, and still nothing else.
set local request.method to 'POST';
set local request.path to '/rpc/my_recommendation_inputs';
select lives_ok('select public.connector_request_guard()',
    'connector may read its own recommendation inputs');

set local request.path to '/rpc/recommend_tagged';
select lives_ok('select public.connector_request_guard()',
    'connector may search followed tags');

set local request.method to 'GET';
set local request.path to '/profiles';
select throws_ok('select public.connector_request_guard()', 'PGRST', null,
    'connector still may not read the profiles table');

-- The function returns the caller's row, and only it.
select is((select count(*)::int from public.my_recommendation_inputs()), 1,
    'one row: the caller''s');
select is((select display_name from public.my_recommendation_inputs()), 'Ada Lovelace',
    'it is the caller''s own profile');
select is((select interests from public.my_recommendation_inputs()), '["spatial-omics"]'::jsonb,
    'with the tags they follow');

-- Layer 2 still keeps the table itself shut to a connector token.
select is((select count(*)::int from public.profiles), 0,
    'a connector token selects no profile rows directly');

reset role;
select * from finish();
rollback;
