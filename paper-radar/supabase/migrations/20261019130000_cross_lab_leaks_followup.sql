-- 20261019130000_cross_lab_leaks_followup.sql — loose ends of
-- 20261018200000_cross_lab_leaks.sql (issue #133), now that the API that read
-- papers.edited_by has been replaced.

-- The column was emptied and no longer written; nothing reads it now.
alter table public.papers drop column edited_by;

-- When an editor deletes their account, the card stops pointing at them, as
-- with paper_aliases.merged_by. (Their id stays in paper_edits.edited_by and in
-- merge snapshots, as it always has: both are history, service role only.)
-- Rows for accounts already gone are deleted first so the constraint can be
-- added; a row without an editor means nothing to paper_editor().
delete from public.paper_editors e
 where edited_by is null
    or not exists (select 1 from public.profiles p where p.id = e.edited_by);
alter table public.paper_editors
    add constraint paper_editors_edited_by_fkey
    foreign key (edited_by) references public.profiles (id) on delete set null;
-- For the set-null when a profile is deleted.
create index paper_editors_edited_by_idx on public.paper_editors (edited_by);

-- A merge snapshot is "the old row as it was", for repairing a merge by hand.
-- With the editor off papers it no longer says who last edited that row, and
-- the row's paper_editors entry goes with it when merge_papers deletes it.
-- Put the editor back into the snapshot as it is written: both merge_papers
-- and promote_to_published insert the alias while the old row still exists.
-- An edited_by the inserter supplied wins (a hand repair). The snapshot is
-- service-role only (20261018200000).
create function public.paper_aliases_snapshot_editor()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    if new.snapshot is not null then
        new.snapshot := jsonb_build_object('edited_by', (
            select edited_by from public.paper_editors
             where paper_id = coalesce(new.old_paper_id, new.paper_id)
        )) || new.snapshot;
    end if;
    return new;
end;
$$;

revoke execute on function public.paper_aliases_snapshot_editor() from public, anon, authenticated;

create trigger paper_aliases_snapshot_editor
    before insert on public.paper_aliases
    for each row execute function public.paper_aliases_snapshot_editor();

-- apply_paper_edit is a definer write to the shared corpus with no
-- authorization of its own: service role only. 20261018200000 replaced it in
-- place, which kept its grants; stated again so nobody has to know that. Named
-- roles too, as in 20261010140000: a project's default privileges can grant
-- anon and authenticated EXECUTE directly, which revoking from public misses.
revoke execute on function public.apply_paper_edit(uuid, uuid, text, timestamptz, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.apply_paper_edit(uuid, uuid, text, timestamptz, jsonb, jsonb) to service_role;

-- Likewise paper_editor(): members only.
revoke execute on function public.paper_editor(uuid) from anon;

-- 20261018200000 took table-wide SELECT on these from authenticated only. anon
-- has none locally (and no policy admits it), but a project with older default
-- privileges grants it directly; take it here too, so the hidden columns are
-- hidden from every role but the service role.
revoke select on public.paper_edits, public.paper_aliases from anon;
