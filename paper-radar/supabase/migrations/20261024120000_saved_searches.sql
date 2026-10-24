-- 20261024120000_saved_searches.sql — saved searches and their weekly suggestions
-- (issue #164).
--
-- A member saves a query (their own PubMed string, or plain keywords) and picks
-- the sources to run it on: PubMed, bioRxiv/medRxiv, arXiv. Once a week the job
-- (api/saved_searches_run.py) runs it over what is new and files each paper the
-- lab does not have yet as a suggestion for that member. They import the ones
-- they want into the lab's library, or dismiss the rest.
--
-- Searches and suggestions are personal (Ellen, 2026-10-24): one member follows
-- AI papers, another TLSs, and a paper one dismisses may be the one another
-- wants. What is imported goes to the shared library like any other post.
--
-- Everything goes through the API (api/saved_searches.py), which checks the
-- feature and membership and then acts with the service role, as the trials
-- tools do. So none of these tables has a grant for anon or authenticated, and
-- connectors are closed out like everywhere else.
--
-- Ships dark behind the 'saved_searches' feature (team_features/user_features).

-- === searches =================================================================

create table public.saved_searches (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references public.profiles (id) on delete cascade,
    -- The lab whose library imports go to, and whose papers are left out.
    team_id     uuid not null references public.teams (id) on delete cascade,
    name        text not null check (char_length(name) between 1 and 120),
    query       text not null check (char_length(query) between 1 and 2000),
    sources     text[] not null
                check (cardinality(sources) >= 1
                       and sources <@ array['pubmed', 'biorxiv', 'arxiv']),
    active      boolean not null default true,
    last_run_at timestamptz,
    -- Why the last run failed on a source, for the settings page; null when it ran.
    last_error  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index saved_searches_owner_idx on public.saved_searches (user_id, team_id);
create index saved_searches_due_idx on public.saved_searches (last_run_at) where active;

alter table public.saved_searches enable row level security;
revoke all on public.saved_searches from public, anon, authenticated;
grant select, insert, update, delete on public.saved_searches to service_role;
select public.close_to_connectors('public.saved_searches');

-- === candidates ================================================================
-- A paper a search found, once however many searches and people found it:
-- the metadata as the source gave it, shown in the inbox and used to import.

create table public.search_candidates (
    id           uuid primary key default gen_random_uuid(),
    -- 'doi:<norm_doi>' when there is a DOI, else 'pmid:<pmid>'.
    key          text not null unique,
    source       text not null check (source in ('pubmed', 'biorxiv', 'medrxiv', 'arxiv')),
    doi          text,
    pmid         text,
    url          text not null,
    title        text not null,
    authors      text[] not null default '{}',
    venue        text,
    published_on date,
    abstract     text,
    first_seen_at timestamptz not null default now()
);

alter table public.search_candidates enable row level security;
revoke all on public.search_candidates from public, anon, authenticated;
grant select, insert, update, delete on public.search_candidates to service_role;
select public.close_to_connectors('public.search_candidates');

-- === suggestions ===============================================================
-- One per person, lab and paper. Unique, so a dismissed paper is never offered
-- to that person again -- and only to them: everyone else still gets it.

create table public.search_suggestions (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null references public.profiles (id) on delete cascade,
    team_id         uuid not null references public.teams (id) on delete cascade,
    candidate_id    uuid not null references public.search_candidates (id) on delete cascade,
    -- The search that found it first. A deleted search leaves its suggestions.
    saved_search_id uuid references public.saved_searches (id) on delete set null,
    -- 'in_library': someone added the paper to the lab another way meanwhile.
    status          text not null default 'pending'
                    check (status in ('pending', 'imported', 'dismissed', 'in_library')),
    paper_id        uuid references public.papers (id) on delete set null,
    decided_at      timestamptz,
    created_at      timestamptz not null default now(),
    unique (user_id, team_id, candidate_id)
);

create index search_suggestions_pending_idx
    on public.search_suggestions (user_id, team_id) where status = 'pending';
create index search_suggestions_candidate_idx on public.search_suggestions (candidate_id);

alter table public.search_suggestions enable row level security;
revoke all on public.search_suggestions from public, anon, authenticated;
grant select, insert, update, delete on public.search_suggestions to service_role;
select public.close_to_connectors('public.search_suggestions');

-- === bioRxiv / medRxiv feed ====================================================
-- bioRxiv's API has no keyword search, only "everything posted between two
-- dates" (~2,400 new preprints a week across both servers). The job copies the
-- last few weeks here once a day, and searches match against this copy -- the
-- weekly run and the "Test query" preview alike -- instead of paging the whole
-- week from bioRxiv for every search.

create table public.rxiv_feed (
    doi        text primary key,
    server     text not null check (server in ('biorxiv', 'medrxiv')),
    title      text not null,
    abstract   text,
    authors    text[] not null default '{}',
    category   text,
    posted_on  date not null,
    fetched_at timestamptz not null default now()
);

create index rxiv_feed_posted_idx on public.rxiv_feed (posted_on);

alter table public.rxiv_feed enable row level security;
revoke all on public.rxiv_feed from public, anon, authenticated;
grant select, insert, update, delete on public.rxiv_feed to service_role;
select public.close_to_connectors('public.rxiv_feed');

-- === posts ======================================================================

alter table public.paper_posts
    drop constraint if exists paper_posts_source_check;
alter table public.paper_posts
    add constraint paper_posts_source_check
        check (source in ('web', 'teams_pdf', 'bibtex', 'teams', 'saved_search'));
