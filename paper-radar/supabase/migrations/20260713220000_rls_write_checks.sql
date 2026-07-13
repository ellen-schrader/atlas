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
-- team_id, and it then shows up on the victim lab's mood board. (paper_status and
-- mentions were intentionally NOT given the same treatment: their only "foreign
-- team_id" risk is a non-exploitable self-inflicted data-integrity nit on the
-- user's own row, and adding is_team_member to their WITH CHECK would break a
-- legitimate self-update on a row for a lab the user has since left — e.g. the
-- blind cross-lab "mark all mentions seen" would abort on a stale row.)
drop policy if exists figures_update on public.figures;
create policy figures_update on public.figures for update
    using (uploaded_by = auth.uid())
    with check (uploaded_by = auth.uid() and public.is_team_member(team_id));

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
