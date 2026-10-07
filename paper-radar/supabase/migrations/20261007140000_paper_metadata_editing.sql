-- 20261007140000_paper_metadata_editing.sql — let a person correct a paper's metadata.
--
-- `papers` is global and deduped: one row serves every lab holding that paper,
-- so an edit is an edit for everyone. Members still get no UPDATE grant. Both
-- writes (fix-by-hand and re-resolve) go through the API, which decides who may
-- edit with can_edit_paper() — run as the caller — and writes with
-- apply_paper_edit() as the service role. See docs/paper-metadata-editing-plan.md.

-- Who last touched the row, when, and which fields a human now holds.
--
-- `edited_fields` is per field rather than one flag on purpose: a boolean would
-- opt the whole row out of backfill, so a hand-fixed title would also stop the
-- abstract Crossref publishes next month from ever arriving. The backfill drops
-- exactly these keys from its patch and still writes the rest.
--
-- `edited_at` doubles as the optimistic-concurrency token. Both kinds of write
-- move it, so a Re-resolve racing a hand edit is caught as surely as two edits.
alter table public.papers
    add column edited_by     uuid,
    add column edited_at     timestamptz,
    add column edited_fields jsonb not null default '[]'::jsonb
        check (jsonb_typeof(edited_fields) = 'array');

-- What each edit changed, for the person who notices a bad one later — who may
-- be in a different lab from whoever made it, with no other way to learn what
-- the title said before. Only the keys the edit touched. An undo is a matter of
-- writing `before` back; the button for it is not built yet, but an edit made
-- before this table existed would be gone for good.
create table public.paper_edits (
    id         uuid primary key default gen_random_uuid(),
    paper_id   uuid not null references public.papers (id) on delete cascade,
    -- 'edit' (fix by hand) or 'resolve' (fetched again from the publisher). A
    -- re-resolve is the one write that can discard a hand correction, so it is
    -- the last thing that should go unrecorded.
    kind       text not null check (kind in ('edit', 'resolve')),
    edited_by  uuid,
    edited_at  timestamptz not null default now(),
    before     jsonb not null,
    after      jsonb not null
);

create index paper_edits_paper_idx on public.paper_edits (paper_id, edited_at desc);

alter table public.paper_edits enable row level security;

-- Readable by anyone who can see the paper — the same predicate as papers_select.
-- Written only by apply_paper_edit, so there is no member-facing write policy.
create policy paper_edits_select on public.paper_edits for select
    to authenticated using (exists (
        select 1 from public.paper_posts p
        where p.paper_id = paper_edits.paper_id and public.is_team_member(p.team_id)
    ));

grant select on public.paper_edits to authenticated;
grant select, insert, update, delete on public.paper_edits to service_role;

-- May the caller correct this paper? In some lab that holds it, they posted it
-- or own that lab — the same rule as removing a post (paper_posts_delete), so
-- there is one mental model for acting on a record other people share.
--
-- Deliberately not "any member": with several labs that would let any member of
-- any lab holding a paper rewrite the row every other lab sees. Relaxing it is
-- dropping the last clause, once the history above has earned that.
--
-- Lives here rather than in Python because it is phrased in auth.uid(): the API
-- calls it with the caller's JWT, and the same function can back a policy later.
create function public.can_edit_paper(p_paper uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.paper_posts pp
         where pp.paper_id = p_paper
           and public.is_team_member(pp.team_id)
           and (pp.posted_by = auth.uid() or public.is_team_owner(pp.team_id))
    );
$$;

-- Apply one edit atomically: check the concurrency token, write the row, stamp
-- who and when, and record the history — all or nothing. Doing these as separate
-- PostgREST calls would let a write land with no history behind it.
--
-- Service role only. It trusts its caller on authorization (the API has already
-- asked can_edit_paper as the user) but not on which columns it may touch: the
-- dedup keys `url`/`url_norm` and everything derived are refused outright.
-- `doi` is accepted because Re-resolve writes the real DOI of a rendition row;
-- the API's collision guard has dropped it from the patch when another row holds it.
create function public.apply_paper_edit(
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
        edited_by       = p_editor,
        edited_at       = stamp
    where id = p_paper;

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
-- the shared corpus with no authorization of its own.
revoke execute on function public.can_edit_paper(uuid) from public;
revoke execute on function public.apply_paper_edit(uuid, uuid, text, timestamptz, jsonb, jsonb) from public;

grant execute on function public.can_edit_paper(uuid) to authenticated;
grant execute on function public.apply_paper_edit(uuid, uuid, text, timestamptz, jsonb, jsonb) to service_role;
