-- 20260712120000_mood_board.sql — the mood board: a lab-scoped, Pinterest-style
-- board of inspirational publication figures, with comments + reactions that
-- mirror the paper engagement pattern exactly.
--
-- Design notes (see also docs/MIGRATION_PLAN.md and 0001/0002 for the pattern):
--   * `figures` are lab-scoped from birth (unlike `papers`, which are a global
--     corpus surfaced per-lab via `paper_posts`). A figure carries its own
--     `team_id`, so RLS is the same `is_team_member(team_id)` shape as comments.
--   * Engagement uses PARALLEL tables (`figure_comments`, `figure_reactions`)
--     rather than making `comments.paper_id` / `reactions.paper_id` nullable —
--     that would break the reactions unique constraint (NULLs) and the paper-bound
--     `mentions` trigger. Figure mentions are intentionally out of scope for v1.
--   * `category` is FREE TEXT and lab-defined: the app suggests broad defaults
--     (web/src/lib/figures.ts) and the lab's already-used categories
--     (figure_categories RPC), and members can add their own — no fixed taxonomy.
--   * Images live in a PRIVATE Storage bucket `figures`, laid out as
--     `{team_id}/{figure_id}.{ext}`; the app serves them via short-lived signed
--     URLs so lab isolation stays enforced in the database, not by URL secrecy.
--   * Future: a `figures.embedding extensions.vector(N)` column + similarity RPCs
--     will power semantic / multi-modal search (describe-a-figure, more-like-this).
--     Deliberately NOT added now — the dimension depends on the chosen model, and
--     the column is a cheap nullable back-fill later (as the paper embeddings were).
--   * Orphaned Storage objects (tab dies between upload and row insert) are
--     accepted for v1; a future service-role sweep can list objects with no
--     matching `figures.storage_path`.

-- === tables ================================================================

create table public.figures (
    id           uuid primary key default gen_random_uuid(),
    team_id      uuid not null references public.teams (id) on delete cascade,
    uploaded_by  uuid references public.profiles (id) on delete set null,
    storage_path text not null unique,             -- '{team_id}/{figure_id}.{ext}' in bucket 'figures'
    title        text not null default '',
    caption      text not null default '',
    -- Free-text, LAB-DEFINED category. The app offers broad defaults
    -- (web/src/lib/figures.ts) plus whatever categories the lab has already used
    -- (public.figure_categories RPC below), and lets members coin their own — so
    -- no fixed check constraint. Empty string means "uncategorised".
    category     text not null default '',
    paper_id     uuid references public.papers (id) on delete set null,  -- optional link to a paper
    tags         jsonb not null default '[]'::jsonb,
    width        int not null check (width > 0),    -- natural px, for stable masonry layout
    height       int not null check (height > 0),
    mime_type    text not null,
    file_size    int,
    created_at   timestamptz not null default now()
);
create index figures_team_idx  on public.figures (team_id, created_at desc);
create index figures_cat_idx   on public.figures (team_id, category);
create index figures_paper_idx on public.figures (paper_id);

create table public.figure_comments (
    id         uuid primary key default gen_random_uuid(),
    figure_id  uuid not null references public.figures (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    author_id  uuid not null references public.profiles (id) on delete cascade,
    body       text not null,
    created_at timestamptz not null default now()
);
create index figure_comments_fig_idx on public.figure_comments (figure_id, team_id);

create table public.figure_reactions (
    id         uuid primary key default gen_random_uuid(),
    figure_id  uuid not null references public.figures (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    user_id    uuid not null references public.profiles (id) on delete cascade,
    emoji      text not null,
    created_at timestamptz not null default now(),
    unique (figure_id, team_id, user_id, emoji)
);
create index figure_reactions_fig_idx on public.figure_reactions (figure_id, team_id);

-- === grants (RLS still restricts rows) =====================================

grant select, insert, update, delete on public.figures          to authenticated;
grant select, insert, update, delete on public.figure_comments  to authenticated;
grant select, insert, delete         on public.figure_reactions to authenticated;
grant all on public.figures, public.figure_comments, public.figure_reactions to service_role;

-- === RLS (mirrors 0002_rls.sql: read within the lab; write/delete your own) =

alter table public.figures          enable row level security;
alter table public.figure_comments  enable row level security;
alter table public.figure_reactions enable row level security;

-- figures: any lab member sees them; you may add a figure to your lab as
-- yourself; only the uploader may edit (re-caption / re-link / re-categorise)
-- or delete it.
create policy figures_select on public.figures for select
    using (public.is_team_member(team_id));
create policy figures_insert on public.figures for insert
    with check (public.is_team_member(team_id) and uploaded_by = auth.uid());
create policy figures_update on public.figures for update
    using (uploaded_by = auth.uid()) with check (uploaded_by = auth.uid());
create policy figures_delete on public.figures for delete
    using (uploaded_by = auth.uid());

-- figure_comments: read within the lab; write/delete your own.
create policy figure_comments_select on public.figure_comments for select
    using (public.is_team_member(team_id));
create policy figure_comments_insert on public.figure_comments for insert
    with check (public.is_team_member(team_id) and author_id = auth.uid());
create policy figure_comments_update on public.figure_comments for update
    using (author_id = auth.uid()) with check (author_id = auth.uid());
create policy figure_comments_delete on public.figure_comments for delete
    using (author_id = auth.uid());

-- figure_reactions: read within the lab; toggle your own.
create policy figure_reactions_select on public.figure_reactions for select
    using (public.is_team_member(team_id));
create policy figure_reactions_insert on public.figure_reactions for insert
    with check (public.is_team_member(team_id) and user_id = auth.uid());
create policy figure_reactions_delete on public.figure_reactions for delete
    using (public.is_team_member(team_id) and user_id = auth.uid());

-- === storage: private bucket + team-folder policies ========================
-- The first path segment is the team_id; membership in that team gates read and
-- write. `owner` (the uploading user) gates delete. If a hosted project blocks
-- `create policy on storage.objects` from a migration (storage-admin ownership),
-- create these three policies via the dashboard — the bucket insert is safe.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('figures', 'figures', false, 10485760,
        array['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
on conflict (id) do nothing;

create policy figures_objects_select on storage.objects for select to authenticated
    using (
        bucket_id = 'figures'
        and public.is_team_member(((storage.foldername(name))[1])::uuid)
    );
create policy figures_objects_insert on storage.objects for insert to authenticated
    with check (
        bucket_id = 'figures'
        and public.is_team_member(((storage.foldername(name))[1])::uuid)
    );
create policy figures_objects_delete on storage.objects for delete to authenticated
    using (bucket_id = 'figures' and owner = auth.uid());

-- === category facets =======================================================
-- Distinct non-empty categories a lab has actually used, with counts — for the
-- board filter chips and the "existing categories" suggestions in the upload /
-- edit chooser. SECURITY INVOKER (default), so the caller's RLS scopes it to
-- their lab; mirrors public.team_tags for paper tags.
create or replace function public.figure_categories(p_team uuid)
returns table(category text, n int)
language sql
stable
as $$
    select f.category, count(*)::int as n
    from public.figures f
    where f.team_id = p_team
      and f.category <> ''
    group by f.category
    order by n desc, f.category;
$$;

grant execute on function public.figure_categories(uuid) to authenticated;
