-- 20260711163829_comments_update.sql — let comment authors edit their own comments.

grant update on public.comments to authenticated;

create policy comments_update on public.comments for update
    using (author_id = auth.uid())
    with check (author_id = auth.uid());
