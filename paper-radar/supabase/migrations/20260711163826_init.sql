-- 0001_init.sql — core schema for the hosted paper-radar app.
-- See docs/MIGRATION_PLAN.md §5 (data model) and §6 (ingest).
--
-- Design notes:
--   * `papers` is a single GLOBAL, deduped corpus. A lab's visibility is
--     mediated entirely by `paper_posts` (see 0002_rls.sql) — the app never
--     browses `papers` directly.
--   * Embedding columns are vector(1024) as a swappable placeholder; the real
--     dimension is set once the embedding model is chosen (plan §13.1). They are
--     nullable and empty at first, so ALTERing the dimension later is cheap.
--   * User-owned engagement cascades on profile deletion; canonical papers do not.

-- Supabase keeps extensions in the `extensions` schema; install + reference there
-- so this applies cleanly on a hosted project. (If you already enabled pgvector in
-- a different schema, adjust these two lines and the `extensions.vector*` refs.)
create extension if not exists pgcrypto with schema extensions;   -- gen_random_uuid()
create extension if not exists vector   with schema extensions;   -- pgvector

-- === identity ==============================================================

create table public.profiles (
    id           uuid primary key references auth.users (id) on delete cascade,
    display_name text not null,
    interests    jsonb not null default '[]'::jsonb,   -- optional explicit interest tags
    profile_md   text not null default '',             -- editable free-text self-description ("USER.md")
    profile_vec  extensions.vector(1024),               -- embedding of profile_md; cold-start taste vector
    created_at   timestamptz not null default now()
);

create table public.teams (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    slug       text not null unique,
    created_by uuid references public.profiles (id) on delete set null,
    created_at timestamptz not null default now()
);

create table public.team_members (
    team_id  uuid not null references public.teams (id) on delete cascade,
    user_id  uuid not null references public.profiles (id) on delete cascade,
    role     text not null default 'member' check (role in ('owner', 'member')),
    joined_at timestamptz not null default now(),
    primary key (team_id, user_id)
);
create index team_members_user_idx on public.team_members (user_id);

-- === papers (global, deduped) =============================================

create table public.papers (
    id              uuid primary key default gen_random_uuid(),
    doi             text unique,                       -- preferred dedup key when present
    url             text not null,                     -- canonical (untruncated) URL as found
    url_norm        text not null unique,              -- normalized dedup key (pdf_extract._normalize_key)
    title           text,
    authors         jsonb not null default '[]'::jsonb,
    abstract        text,
    venue           text,
    year            int,
    keywords        jsonb not null default '[]'::jsonb, -- from metadata (author kw / MeSH / subjects)
    tags            jsonb not null default '[]'::jsonb, -- from LLM enrichment
    code_url        text,
    data_url        text,
    metadata_source text,                               -- arxiv|crossref|pubmed|europepmc|citation_meta|unknown
    embedding       extensions.vector(1024),
    enriched_at     timestamptz,                        -- null = enrichment pending
    embedded_at     timestamptz,
    created_at      timestamptz not null default now()
);

-- Semantic search (populated later; safe to build on an empty table).
create index papers_embedding_idx on public.papers using hnsw (embedding extensions.vector_cosine_ops);
-- Full-text search over title + abstract (phase 5).
create index papers_fts_idx on public.papers
    using gin (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, '')));

-- A paper posted INTO a lab. This is the visibility boundary.
create table public.paper_posts (
    id              uuid primary key default gen_random_uuid(),
    paper_id        uuid not null references public.papers (id) on delete cascade,
    team_id         uuid not null references public.teams (id) on delete cascade,
    posted_by       uuid references public.profiles (id) on delete set null,  -- in-app posts
    posted_by_label text,                               -- free-text name from a Teams export
    posted_at       timestamptz not null default now(),
    source          text not null check (source in ('web', 'teams_pdf')),
    source_pdf      text,
    page            int,
    via             text,                               -- 'annotation' | 'text'
    note            text,
    unique (paper_id, team_id)                          -- a lab posts a given paper at most once
);
create index paper_posts_team_idx on public.paper_posts (team_id);
create index paper_posts_paper_idx on public.paper_posts (paper_id);

-- === engagement (lab-scoped) ==============================================

create table public.comments (
    id         uuid primary key default gen_random_uuid(),
    paper_id   uuid not null references public.papers (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    author_id  uuid not null references public.profiles (id) on delete cascade,
    body       text not null,
    created_at timestamptz not null default now()
);
create index comments_paper_team_idx on public.comments (paper_id, team_id);

create table public.reactions (
    id         uuid primary key default gen_random_uuid(),
    paper_id   uuid not null references public.papers (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    user_id    uuid not null references public.profiles (id) on delete cascade,
    emoji      text not null,
    created_at timestamptz not null default now(),
    unique (paper_id, team_id, user_id, emoji)
);
create index reactions_paper_team_idx on public.reactions (paper_id, team_id);

-- Per-user read state; powers the to-be-read list.
create table public.paper_status (
    user_id    uuid not null references public.profiles (id) on delete cascade,
    paper_id   uuid not null references public.papers (id) on delete cascade,
    team_id    uuid not null references public.teams (id) on delete cascade,
    status     text not null check (status in ('to_read', 'reading', 'read')),
    updated_at timestamptz not null default now(),
    primary key (user_id, paper_id, team_id)
);

-- @-mention of a lab member on a paper. Notifies them (dashboard + auto-TBR).
create table public.mentions (
    id             uuid primary key default gen_random_uuid(),
    paper_id       uuid not null references public.papers (id) on delete cascade,
    team_id        uuid not null references public.teams (id) on delete cascade,
    mentioned_user uuid not null references public.profiles (id) on delete cascade,
    mentioned_by   uuid references public.profiles (id) on delete set null,
    comment_id     uuid references public.comments (id) on delete cascade,
    created_at     timestamptz not null default now(),
    seen_at        timestamptz
);
create index mentions_inbox_idx on public.mentions (mentioned_user, seen_at);

-- Per-lab trend clusters, computed by the worker on a schedule.
create table public.trends (
    id          uuid primary key default gen_random_uuid(),
    team_id     uuid not null references public.teams (id) on delete cascade,
    label       text not null,
    description text,
    paper_ids   jsonb not null default '[]'::jsonb,
    computed_at timestamptz not null default now()
);
create index trends_team_idx on public.trends (team_id);

-- === triggers ==============================================================

-- Auto-create a profile row when a new auth user signs up (profile bootstrap).
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, display_name)
    values (
        new.id,
        coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1))
    )
    on conflict (id) do nothing;
    return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

-- A mention auto-adds the paper to the mentioned user's TBR — but only if they
-- have no status yet, so it never overwrites 'reading' / 'read'. Enforced here
-- (not in app code) so a client can't bypass the invariant.
create function public.handle_mention_tbr()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.paper_status (user_id, paper_id, team_id, status)
    values (new.mentioned_user, new.paper_id, new.team_id, 'to_read')
    on conflict (user_id, paper_id, team_id) do nothing;
    return new;
end;
$$;

create trigger on_mention_created
after insert on public.mentions
for each row execute function public.handle_mention_tbr();
