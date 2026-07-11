-- 20260711163830_post_tags.sql — lab-scoped custom tags on a post.
--
-- papers.tags/keywords are the canonical (LLM/metadata) tags on the global paper.
-- These are tags a lab adds itself, editable by any member of that lab.

alter table public.paper_posts add column tags jsonb not null default '[]'::jsonb;

grant update on public.paper_posts to authenticated;

create policy paper_posts_update on public.paper_posts for update
    using (public.is_team_member(team_id))
    with check (public.is_team_member(team_id));
