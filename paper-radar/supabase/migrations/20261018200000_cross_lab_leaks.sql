-- 20261018200000_cross_lab_leaks.sql — what a lab can read about another lab's
-- activity on a paper they both hold (issue #133).
--
-- Papers are global, so papers, paper_edits and paper_aliases are readable by
-- every lab holding the paper. That is right for what they say about the
-- *paper* — what the title used to be, where the preprint is — but some columns
-- say who in another lab acted on it:
--
--   papers.edited_by            the last editor's user id. profiles RLS hides the
--   paper_edits.edited_by       name across labs, but the id is still a stable
--                               handle: "the same person corrected these five
--                               papers".
--   paper_aliases.snapshot      the merged-away row, including its edited_by,
--                               edited_at and edited_fields, and the created_at of
--                               a row perhaps only another lab held.
--   paper_aliases.merged_by     who confirmed a merge, which any member of any
--                               lab holding either paper may do.
--   paper_aliases.reason        'manual' says a person did it.
--
-- So members get SELECT on the other columns only. The rows stay as visible as
-- before: an edit's before/after is the point of the history (the person who
-- notices a bad correction is often in another lab), and a preprint link is
-- public bibliographic information. Everything that needs the hidden columns —
-- the API (service role), the merge and promote functions — is untouched.
--
-- Column grants make `select *` (or `papers(*)` in an embed) fail with
-- "permission denied" for members rather than quietly returning less; name the
-- columns. A column added to any of these tables later is hidden from members
-- until a migration grants it, which is the safe default but will surprise:
-- supabase/tests/cross_lab_leaks_test.sql lists what is meant to be hidden and
-- fails on anything else members cannot read.

-- === papers =================================================================

-- Every column but edited_by, read from the catalogue so the grant matches
-- whatever columns exist when this runs.
revoke select on public.papers from authenticated;
do $$
begin
    execute (
        select format('grant select (%s) on public.papers to authenticated',
                      string_agg(quote_ident(attname), ', ' order by attnum))
          from pg_attribute
         where attrelid = 'public.papers'::regclass
           and attnum > 0 and not attisdropped
           and attname <> 'edited_by'
    );
end;
$$;

-- The card's "Edited by Ada · 2 Oct": who last edited the paper, as far as the
-- caller may know. No row when the caller cannot see the paper or no person
-- edited it (a re-resolve by a job). Otherwise is_you, or in_your_lab with the
-- editor's name, or neither: "outside your lab". The same line profiles RLS
-- draws, without handing out the id.
create function public.paper_editor(p_paper uuid)
returns table (is_you boolean, in_your_lab boolean, display_name text)
language sql
stable
security definer
set search_path = public
as $$
    select p.edited_by = auth.uid(),
           p.edited_by <> auth.uid() and public.shares_team_with(p.edited_by),
           case when p.edited_by <> auth.uid() and public.shares_team_with(p.edited_by)
                then pr.display_name end
      from public.papers p
      left join public.profiles pr on pr.id = p.edited_by
     where p.id = p_paper
       and p.edited_by is not null
       and exists (
           select 1 from public.paper_posts pp
            where pp.paper_id = p.id and public.is_team_member(pp.team_id)
       );
$$;

revoke execute on function public.paper_editor(uuid) from public;
grant execute on function public.paper_editor(uuid) to authenticated;

-- === paper_edits ============================================================

-- A history UI that wants "edited by Ada" for an editor in the viewer's own lab
-- should get it the way paper_editor does, not by granting the column back.
revoke select on public.paper_edits from authenticated;
grant select (id, paper_id, kind, edited_at, before, after)
    on public.paper_edits to authenticated;

-- === paper_aliases ==========================================================

revoke select on public.paper_aliases from authenticated;
grant select (id, paper_id, kind, doi, url, url_norm, venue, old_paper_id, created_at)
    on public.paper_aliases to authenticated;
