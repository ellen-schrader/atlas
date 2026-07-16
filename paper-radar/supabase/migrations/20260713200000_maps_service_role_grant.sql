-- 20260713200000_maps_service_role_grant.sql — repair grant for public.maps.
--
-- 20260713170000_maps.sql originally shipped without a service_role grant and
-- was edited in place to add one after prod had already applied it, so prod
-- never ran the added line. The API writes maps.ai_summary via the service
-- role (make_map_summary in api/app.py), which fails with 42501 "permission
-- denied for table maps" without it. Fresh environments get the grant twice
-- (here and in the edited maps migration); GRANT is idempotent, so that's
-- harmless.
--
-- Process note: never edit an already-applied migration — add a new one.

grant select, insert, update, delete on public.maps to service_role;
