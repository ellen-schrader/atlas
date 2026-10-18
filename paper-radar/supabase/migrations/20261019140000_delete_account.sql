-- Self-service account deletion (docs/ACCOUNT_DELETION_PLAN.md).
--
-- Before this, deleting an auth user failed for anyone who had made a map
-- (maps.created_by had no ON DELETE), and otherwise cascaded their comments out
-- of lab discussions. The agreed behaviour: what a person contributed to a lab
-- stays, without their name; their personal data goes; a last owner can't
-- leave other members ownerless; a lab they're alone in goes with them.

-- === contributions stay, anonymised =========================================
alter table public.comments alter column author_id drop not null;
alter table public.comments drop constraint comments_author_id_fkey;
alter table public.comments add constraint comments_author_id_fkey
    foreign key (author_id) references public.profiles (id) on delete set null;

alter table public.figure_comments alter column author_id drop not null;
alter table public.figure_comments drop constraint figure_comments_author_id_fkey;
alter table public.figure_comments add constraint figure_comments_author_id_fkey
    foreign key (author_id) references public.profiles (id) on delete set null;

alter table public.maps alter column created_by drop not null;
alter table public.maps drop constraint maps_created_by_fkey;
alter table public.maps add constraint maps_created_by_fkey
    foreign key (created_by) references public.profiles (id) on delete set null;

-- Every SET NULL above (and the older ones on figures and posts) is applied by
-- scanning for the user's rows; index them so a deletion doesn't scan whole
-- tables inside its transaction (as paper_editors_edited_by_idx already does).
create index if not exists comments_author_idx on public.comments (author_id);
create index if not exists figure_comments_author_idx on public.figure_comments (author_id);
create index if not exists maps_created_by_idx on public.maps (created_by);
create index if not exists figures_uploaded_by_idx on public.figures (uploaded_by);
create index if not exists paper_posts_posted_by_idx on public.paper_posts (posted_by);

-- === orphans stay manageable ================================================
-- Comments, figures and maps whose author is gone could otherwise never be
-- removed by anyone: their policies all key on the author. A lab owner may
-- remove them. Only remove: editing someone else's words or images isn't
-- needed, and an update could move a row away from its storage folder.
-- (Posts already have an owner delete policy.)
create policy comments_delete_orphan on public.comments for delete
    to authenticated using (author_id is null and public.is_team_owner(team_id));
create policy figure_comments_delete_orphan on public.figure_comments for delete
    to authenticated using (author_id is null and public.is_team_owner(team_id));
create policy figures_delete_orphan on public.figures for delete
    to authenticated using (uploaded_by is null and public.is_team_owner(team_id));
create policy maps_delete_orphan on public.maps for delete
    to authenticated using (created_by is null and public.is_team_owner(team_id));

-- The file of an orphaned figure, and only that: a lab owner may not delete a
-- current member's upload.
create policy figures_objects_delete_orphan on storage.objects for delete to authenticated
    using (
        bucket_id = 'figures'
        and exists (
            select 1 from public.figures f
            where f.storage_path = storage.objects.name
              and f.uploaded_by is null
              and public.is_team_owner(f.team_id)
        )
    );

-- === delete_account =========================================================
-- Run by the API (POST /account/delete) with the service role, for the user id
-- it has verified from the caller's token: not callable by users or connector
-- tokens, so the API's follow-up (removing the solo labs' figure files) can't be
-- skipped. One transaction: a refusal leaves everything as it was.
--
-- Returns the ids of the labs deleted with the account, for that file cleanup.
create or replace function public.delete_account(p_user uuid, p_confirm_email text)
returns uuid[]
language plpgsql
security definer
set search_path = public
as $$
declare
    v_email text;
    v_teams uuid[];
    v_blocking text;
    v_solo uuid[];
begin
    select email into v_email from auth.users where id = p_user;
    if v_email is null then
        raise exception 'No such account' using errcode = '42704';
    end if;
    if lower(trim(coalesce(p_confirm_email, ''))) <> lower(v_email) then
        raise exception 'The email doesn''t match this account' using errcode = '22023';
    end if;

    -- Lock the user's labs first. Joining a lab inserts a member row whose
    -- foreign key takes a KEY SHARE lock on the team, which FOR UPDATE blocks;
    -- a co-owner deleting at the same moment waits here too. So the checks
    -- below can't be overtaken by a join or by another deletion.
    select coalesce(array_agg(t.id), '{}') into v_teams
    from (
        select t.id from public.teams t
        join public.team_members me on me.team_id = t.id and me.user_id = p_user
        order by t.id
        for update of t
    ) t;

    -- Last owner of a lab that still has other members: refuse, naming the labs,
    -- as leave_team does for one lab.
    select string_agg(t.name, ', ' order by t.name) into v_blocking
    from public.team_members me
    join public.teams t on t.id = me.team_id
    where me.user_id = p_user
      and me.role = 'owner'
      and not exists (
          select 1 from public.team_members o
          where o.team_id = me.team_id and o.role = 'owner' and o.user_id <> p_user)
      and exists (
          select 1 from public.team_members m
          where m.team_id = me.team_id and m.user_id <> p_user);
    if v_blocking is not null then
        raise exception 'Make someone else an owner of % first', v_blocking
            using errcode = 'P0001';
    end if;

    -- Labs they're alone in go with them. Their posts cascade, and the removal
    -- trigger turns each into a removed_posts tombstone; those go too, since the
    -- lab they'd be restored into no longer exists.
    select coalesce(array_agg(me.team_id), '{}') into v_solo
    from public.team_members me
    where me.team_id = any (v_teams)
      and me.user_id = p_user
      and not exists (
          select 1 from public.team_members m
          where m.team_id = me.team_id and m.user_id <> p_user);
    delete from public.teams where id = any (v_solo);
    delete from public.removed_posts where team_id = any (v_solo);

    -- Tombstones in labs that stay: drop the user's id (not a foreign key, so
    -- nothing else will), which also keeps restore_post working, since it
    -- copies posted_by back into paper_posts.
    update public.removed_posts set posted_by = null where posted_by = p_user;
    update public.removed_posts set removed_by = null where removed_by = p_user;

    -- Private maps are theirs alone; lab maps stay, without their name.
    delete from public.maps where created_by = p_user and visibility = 'private';

    -- Everything else follows from the auth user: the profile cascades, and with
    -- it memberships, reactions, reading list, notifications, sessions and Claude
    -- grants; posts, comments, figures and lab maps keep their rows with a null
    -- author.
    delete from auth.users where id = p_user;

    return v_solo;
end;
$$;

revoke all on function public.delete_account(uuid, text) from public, anon, authenticated;
grant execute on function public.delete_account(uuid, text) to service_role;

comment on function public.delete_account(uuid, text) is
    'Deletes an account (docs/ACCOUNT_DELETION_PLAN.md). Service role only: POST /account/delete calls it for the user verified from the token. Refuses on a wrong confirmation email or if the user is the last owner of a lab with other members. Returns the ids of the solo labs deleted with it.';
