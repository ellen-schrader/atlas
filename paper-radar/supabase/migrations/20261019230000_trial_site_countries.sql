-- Where a lab's trials have sites: for each trial on the lab's list, the
-- countries in its stored registry record and how many sites each has. Counted
-- here so the app gets a few bytes per trial instead of every site's address
-- (a location list can run to 100 kB). Sites, not participants: the registry
-- doesn't say how many each enrolled. Withdrawn sites (never opened) don't
-- count. web/src/lib/trials.ts siteCountries() counts one record the same way.
--
-- As the caller (security invoker), so trial_posts' and trials' policies
-- apply: only labs with the feature, only trials the caller can read.

create function public.trial_site_countries(p_team uuid)
returns table (trial_id uuid, country text, sites integer)
language sql
stable
security invoker
set search_path = public
as $$
    select tp.trial_id, btrim(loc->>'country'), count(*)::integer
      from public.trial_posts tp
      join public.trials t on t.id = tp.trial_id
     cross join lateral jsonb_array_elements(
           case when jsonb_typeof(t.registry->'contactsLocationsModule'->'locations') = 'array'
                then t.registry->'contactsLocationsModule'->'locations'
                else '[]'::jsonb end
       ) loc
     where tp.team_id = p_team
       and jsonb_typeof(loc) = 'object'
       and coalesce(loc->>'status', '') <> 'WITHDRAWN'
       and btrim(coalesce(loc->>'country', '')) <> ''
     group by tp.trial_id, btrim(loc->>'country')
$$;
revoke execute on function public.trial_site_countries(uuid) from public, anon;
grant execute on function public.trial_site_countries(uuid) to authenticated;
