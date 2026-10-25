-- 20261025120000_delete_search_suggestions.sql — deleting a saved search takes
-- its waiting suggestions with it (issue #164).
--
-- Until now a deleted search's suggestions stayed on the Suggestions page under
-- "Deleted searches". Ellen (2026-10-25) deleted a search and expected them
-- gone. Now they go, except a paper another of the person's searches also
-- found, which stays under that one. Added and dismissed suggestions stay: they
-- are the record that stops a paper being suggested twice.

-- Deletes the person's search and, in the same transaction, its waiting
-- suggestions that no other search found. False (and nothing changed) if the
-- search is not theirs.
create function public.delete_saved_search(p_user uuid, p_team uuid, p_id uuid)
returns boolean
language plpgsql
set search_path = ''
as $$
begin
    if not exists (
        select 1 from public.saved_searches
        where id = p_id and user_id = p_user and team_id = p_team
    ) then
        return false;
    end if;
    delete from public.search_suggestions s
    where s.user_id = p_user and s.team_id = p_team and s.status = 'pending'
      and exists (select 1 from public.search_suggestion_searches l
                  where l.suggestion_id = s.id and l.saved_search_id = p_id)
      and not exists (select 1 from public.search_suggestion_searches l
                      where l.suggestion_id = s.id and l.saved_search_id <> p_id);
    delete from public.saved_searches
    where id = p_id and user_id = p_user and team_id = p_team;
    return true;
end;
$$;

revoke all on function public.delete_saved_search(uuid, uuid, uuid)
    from public, anon, authenticated;
grant execute on function public.delete_saved_search(uuid, uuid, uuid) to service_role;

-- The ones already waiting under "Deleted searches": every suggestion is
-- linked to the searches that found it (backfilled in 20261024200000), so a
-- waiting one with no link is left from a deleted search.
delete from public.search_suggestions s
where s.status = 'pending'
  and not exists (select 1 from public.search_suggestion_searches l
                  where l.suggestion_id = s.id);
