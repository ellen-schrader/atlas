-- 20260712150000_paper_delete.sql — let a lab owner delete any post in their lab.
--
-- Deleting a paper_post removes the paper from that lab only; the global,
-- deduped `papers` row stays (other labs may reference it). Reclaiming orphaned
-- global papers is a separate, coordinated cleanup — not done here.

create or replace function public.is_team_owner(t uuid)
returns boolean
language sql
stable
security definer
set search_path to 'public'
as $$
    select exists (
        select 1 from public.team_members
        where team_id = t and user_id = auth.uid() and role = 'owner'
    );
$$;

grant execute on function public.is_team_owner(uuid) to authenticated;

-- Widen delete: the poster OR a lab owner may delete a post (was poster-only).
drop policy if exists paper_posts_delete on public.paper_posts;
create policy paper_posts_delete on public.paper_posts
    for delete
    using (is_team_member(team_id) and (posted_by = auth.uid() or is_team_owner(team_id)));
