-- 20261007120000_undo_paper_removal.sql — make removing a paper undoable.
--
-- Removing a paper takes it away from everyone in the lab, and until now it was
-- final. A client-side undo is not possible: paper_posts_insert requires
-- `posted_by = auth.uid()`, so re-inserting could only ever claim the restorer
-- as the sharer — and most posts in practice come from the Teams PDF importer
-- with `posted_by = null`, which nobody can satisfy. An undo that rewrites who
-- shared a paper is worse than none.
--
-- So the row is kept rather than reconstructed. A delete trigger copies it into
-- a tombstone, and restore_post() puts it back exactly as it was. The client
-- names a removal; it never supplies the contents, so attribution cannot be
-- forged by replaying the call with different values.
--
-- The tombstone doubles as the record of who removed what, which is the other
-- half of the problem: a paper vanishing for the whole lab with no trace of who
-- did it leaves everyone else guessing.

create table public.removed_posts (
    -- The original paper_posts.id, so a restore is recognisably the same post.
    id              uuid primary key,
    -- Deliberately NOT foreign keys. Deleting a paper or a team cascades into
    -- paper_posts, which fires the trigger below *during* that delete; a FK here
    -- would then reference a row on its way out. restore_post re-checks that the
    -- paper still exists instead.
    paper_id        uuid not null,
    team_id         uuid not null,
    posted_by       uuid,
    posted_by_label text,
    posted_at       timestamptz not null,
    source          text not null,
    source_pdf      text,
    page            int,
    via             text,
    note            text,
    tags            jsonb not null default '[]'::jsonb,
    removed_by      uuid,
    removed_at      timestamptz not null default now()
);

create index removed_posts_team_idx on public.removed_posts (team_id, removed_at desc);

-- AFTER DELETE, so a removal that is rolled back leaves no tombstone.
create function public.capture_removed_post()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.removed_posts (
        id, paper_id, team_id, posted_by, posted_by_label, posted_at,
        source, source_pdf, page, via, note, tags, removed_by
    )
    values (
        old.id, old.paper_id, old.team_id, old.posted_by, old.posted_by_label, old.posted_at,
        old.source, old.source_pdf, old.page, old.via, old.note, old.tags, auth.uid()
    )
    -- A paper removed, restored and removed again reuses its id.
    on conflict (id) do update set removed_by = excluded.removed_by, removed_at = now();
    return old;
end;
$$;

create trigger on_paper_post_deleted
after delete on public.paper_posts
for each row execute function public.capture_removed_post();

-- Put a removed paper back, exactly as it was. SECURITY DEFINER because the
-- whole point is to write a `posted_by` the caller could not write themselves —
-- which is safe only because every value comes from the tombstone, never from
-- the caller. The caller supplies one id and must be in that lab.
create function public.restore_post(p_post uuid)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    r public.removed_posts;
begin
    select * into r from public.removed_posts where id = p_post;
    if not found then
        raise exception 'That removal can no longer be undone.' using errcode = 'no_data_found';
    end if;
    if not public.is_team_member(r.team_id) then
        raise exception 'That paper is not in one of your labs.' using errcode = '42501';
    end if;
    if not exists (select 1 from public.papers where id = r.paper_id) then
        raise exception 'That paper no longer exists.' using errcode = 'no_data_found';
    end if;

    insert into public.paper_posts (
        id, paper_id, team_id, posted_by, posted_by_label, posted_at,
        source, source_pdf, page, via, note, tags
    )
    values (
        r.id, r.paper_id, r.team_id, r.posted_by, r.posted_by_label, r.posted_at,
        r.source, r.source_pdf, r.page, r.via, r.note, r.tags
    )
    -- Someone may have re-added it by hand in the meantime; the paper being back
    -- is what was asked for either way.
    on conflict (paper_id, team_id) do nothing;

    delete from public.removed_posts where id = p_post;
    return r.paper_id;
end;
$$;

alter table public.removed_posts enable row level security;

-- Members can see what has been removed from their own labs, and by whom. The
-- table is written only by the trigger and cleared only by restore_post, both
-- of which run as definer, so there is no member-facing insert/update/delete.
create policy removed_posts_select on public.removed_posts for select
    to authenticated using (is_team_member(team_id));

grant select on public.removed_posts to authenticated;
grant select, insert, update, delete on public.removed_posts to service_role;
grant execute on function public.restore_post(uuid) to authenticated;
