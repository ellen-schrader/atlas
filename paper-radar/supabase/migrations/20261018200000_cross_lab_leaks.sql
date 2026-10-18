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
-- So members lose those columns; the rows stay as visible as before: an edit's
-- before/after is the point of the history (the person who notices a bad
-- correction is often in another lab), and a preprint link is public
-- bibliographic information. Everything that needs the hidden values — the API
-- (service role), the edit, merge and promote functions — still has them.
--
-- On paper_edits and paper_aliases members get SELECT on the other columns
-- only. That makes `select *` (or `paper_aliases(*)` in an embed) fail with
-- "permission denied" rather than quietly return less — name the columns — and
-- a column added to either table later is hidden from members until a
-- migration grants it. supabase/tests/cross_lab_leaks_test.sql lists what is
-- meant to be hidden and fails on anything else.

-- === papers.edited_by → paper_editors ======================================

-- papers gains a column most weeks, so it keeps its table-wide grant; the one
-- column that says who moves to a table only the service role and definer
-- functions read. papers.edited_by is emptied and no longer written, but stays
-- for now: the API deployed when this runs still selects it (deploy.yml pushes
-- migrations before the new API is up). Drop it in a later migration.
create table public.paper_editors (
    paper_id  uuid primary key references public.papers (id) on delete cascade,
    edited_by uuid
);

alter table public.paper_editors enable row level security;
revoke all on public.paper_editors from anon, authenticated;
grant select, insert, update, delete on public.paper_editors to service_role;
select public.close_to_connectors('public.paper_editors');

insert into public.paper_editors (paper_id, edited_by)
select id, edited_by from public.papers where edited_by is not null;
update public.papers set edited_by = null where edited_by is not null;

-- As in 20261007140000, but the editor goes to paper_editors.
create or replace function public.apply_paper_edit(
    p_paper    uuid,
    p_editor   uuid,
    p_kind     text,
    p_expected timestamptz,
    p_patch    jsonb,
    p_held     jsonb
)
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
    -- Columns whose change is worth a line of history.
    content  constant text[] := array[
        'title', 'authors', 'venue', 'year', 'abstract', 'code_url', 'data_url',
        'published_at', 'doi', 'keywords'
    ];
    -- Plus the bookkeeping an edit moves along with them.
    writable constant text[] := content || array['metadata_source', 'embedded_at', 'enriched_at'];
    cur     public.papers;
    nxt     public.papers;
    touched text[];
    stamp   timestamptz := now();
    bad     text;
begin
    select k into bad from jsonb_object_keys(p_patch) k where k <> all (writable) limit 1;
    if bad is not null then
        raise exception 'Not an editable paper field: %', bad using errcode = '22023';
    end if;

    select * into cur from public.papers where id = p_paper for update;
    if not found then
        raise exception 'That paper no longer exists.' using errcode = 'no_data_found';
    end if;
    -- `is distinct from`, so a null token ("never edited when I loaded it") is a
    -- claim that gets checked too, not a pass.
    if cur.edited_at is distinct from p_expected then
        raise exception 'Someone else changed this paper since you opened it.'
            using errcode = '40001';
    end if;

    nxt := jsonb_populate_record(cur, p_patch);
    update public.papers set
        title           = nxt.title,
        authors         = nxt.authors,
        venue           = nxt.venue,
        year            = nxt.year,
        abstract        = nxt.abstract,
        code_url        = nxt.code_url,
        data_url        = nxt.data_url,
        published_at    = nxt.published_at,
        doi             = nxt.doi,
        keywords        = nxt.keywords,
        metadata_source = nxt.metadata_source,
        embedded_at     = nxt.embedded_at,
        enriched_at     = nxt.enriched_at,
        edited_fields   = coalesce(p_held, '[]'::jsonb),
        edited_at       = stamp
    where id = p_paper;

    -- Who, where members cannot read it (was papers.edited_by).
    insert into public.paper_editors (paper_id, edited_by) values (p_paper, p_editor)
    on conflict (paper_id) do update set edited_by = excluded.edited_by;

    select array_agg(k) into touched
      from jsonb_object_keys(p_patch) k where k = any (content);
    if touched is not null then
        insert into public.paper_edits (paper_id, kind, edited_by, edited_at, before, after)
        values (
            p_paper, p_kind, p_editor, stamp,
            (select jsonb_object_agg(k, to_jsonb(cur) -> k) from unnest(touched) k),
            (select jsonb_object_agg(k, to_jsonb(nxt) -> k) from unnest(touched) k)
        );
        -- Pruned on write, like removed_posts, so there is no cron to own — but by
        -- count per paper, not by age. Age would eventually delete the only record
        -- of the edit that is still live on the row, which is the one most worth
        -- keeping.
        delete from public.paper_edits
         where paper_id = p_paper
           and id not in (
               select id from public.paper_edits
                where paper_id = p_paper
                order by edited_at desc
                limit 50
           );
    end if;

    return stamp;
end;
$$;

-- Postgres grants EXECUTE to PUBLIC on a new function; revoke first, or the
-- grants below add nothing. apply_paper_edit in particular is a definer write to

-- The card's "Edited by Ada · 2 Oct": who last edited the paper, as far as the
-- caller may know. No row when the caller cannot see the paper or no person
-- edited it. Otherwise is_you, or in_your_lab with the editor's name, or
-- neither: "outside your lab". The same line profiles RLS draws (current
-- membership, so an editor who has left the lab counts as outside it), without
-- handing out the id.
create function public.paper_editor(p_paper uuid)
returns table (is_you boolean, in_your_lab boolean, display_name text)
language sql
stable
security definer
set search_path = public
as $$
    select e.edited_by = auth.uid(),
           e.edited_by <> auth.uid() and public.shares_team_with(e.edited_by),
           case when e.edited_by <> auth.uid() and public.shares_team_with(e.edited_by)
                then pr.display_name end
      from public.paper_editors e
      left join public.profiles pr on pr.id = e.edited_by
     where e.paper_id = p_paper
       and e.edited_by is not null
       and exists (
           select 1 from public.paper_posts pp
            where pp.paper_id = e.paper_id and public.is_team_member(pp.team_id)
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
