-- 20261018210000_cross_lab_leaks_followup.sql — loose ends of
-- 20261018200000_cross_lab_leaks.sql (issue #133), now that the API that read
-- papers.edited_by has been replaced.

-- The column was emptied and no longer written; nothing reads it now.
alter table public.papers drop column edited_by;

-- An editor who deletes their account leaves no id behind, as with
-- paper_aliases.merged_by. Ids with no profile (accounts already gone) are
-- cleared first so the constraint can be added.
update public.paper_editors e set edited_by = null
 where edited_by is not null
   and not exists (select 1 from public.profiles p where p.id = e.edited_by);
alter table public.paper_editors
    add constraint paper_editors_edited_by_fkey
    foreign key (edited_by) references public.profiles (id) on delete set null;

-- A merge snapshot is "the old row as it was", for repairing a merge by hand.
-- With the editor off papers it no longer says who last edited that row, and
-- the row's paper_editors entry goes with it when merge_papers deletes it.
-- Put the editor back into the snapshot as it is written: both merge_papers
-- and promote_to_published insert the alias while the old row still exists.
-- The snapshot is service-role only (20261018200000).
create function public.paper_aliases_snapshot_editor()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    if new.snapshot is not null then
        new.snapshot := new.snapshot || jsonb_build_object('edited_by', (
            select edited_by from public.paper_editors
             where paper_id = coalesce(new.old_paper_id, new.paper_id)
        ));
    end if;
    return new;
end;
$$;

revoke execute on function public.paper_aliases_snapshot_editor() from public;

create trigger paper_aliases_snapshot_editor
    before insert on public.paper_aliases
    for each row execute function public.paper_aliases_snapshot_editor();

-- apply_paper_edit is a definer write to the shared corpus with no
-- authorization of its own: service role only. 20261018200000 replaced it in
-- place, which kept these; stated again so nobody has to know that.
revoke execute on function public.apply_paper_edit(uuid, uuid, text, timestamptz, jsonb, jsonb) from public;
grant execute on function public.apply_paper_edit(uuid, uuid, text, timestamptz, jsonb, jsonb) to service_role;
