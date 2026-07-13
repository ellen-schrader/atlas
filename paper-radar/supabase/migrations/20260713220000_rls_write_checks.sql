-- 20260713220000_rls_write_checks.sql
-- Security fix (pre-public audit, medium/low RLS gaps):
--   * UPDATE policies whose WITH CHECK omitted the team predicate let a user
--     stamp a foreign team_id onto a row they own — cross-tenant injection
--     (figures) or a dangling personal row (paper_status, mentions).
--   * Membership helper functions defaulted to EXECUTE by PUBLIC, so
--     user_in_team(u, t) answered arbitrary (user, team) membership questions
--     for any caller, including anon.

-- === figures: re-assert membership on UPDATE (mirror maps_update) ============
-- Without this, a user can move their own figure into another lab by rewriting
-- team_id, and it then shows up on the victim lab's mood board.
drop policy if exists figures_update on public.figures;
create policy figures_update on public.figures for update
    using (uploaded_by = auth.uid())
    with check (uploaded_by = auth.uid() and public.is_team_member(team_id));

-- === paper_status / mentions: forbid stamping a foreign team_id =============
drop policy if exists paper_status_update on public.paper_status;
create policy paper_status_update on public.paper_status for update
    using (user_id = auth.uid())
    with check (user_id = auth.uid() and public.is_team_member(team_id));

drop policy if exists mentions_update on public.mentions;
create policy mentions_update on public.mentions for update
    using (mentioned_user = auth.uid())
    with check (mentioned_user = auth.uid() and public.is_team_member(team_id));

-- === close the membership oracle ============================================
-- These are SECURITY DEFINER and are referenced by RLS policies, so keep them
-- executable by `authenticated` (policies evaluate as the querying role) but
-- drop the blanket PUBLIC grant that also exposed them to `anon`.
revoke execute on function public.user_in_team(uuid, uuid) from public;
revoke execute on function public.is_team_member(uuid)     from public;
revoke execute on function public.shares_team_with(uuid)   from public;
grant  execute on function public.user_in_team(uuid, uuid) to authenticated;
grant  execute on function public.is_team_member(uuid)     to authenticated;
grant  execute on function public.shares_team_with(uuid)   to authenticated;
