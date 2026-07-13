-- 20260713140000_bibtex_import.sql — BibTeX import: a real publication date, and a
-- source that says where a post came from.
--
-- Why a new column instead of writing the publication date into `paper_posts.posted_at`:
--
--   `posted_at` means "when your lab shared this". The UI renders it as "Posted by
--   Ellen · 3 days ago". Overwriting it with the publication date would make that
--   line false for every imported paper, turn the Overview's "Shared over time"
--   chart into a duplicate of "Papers by year", and stop a freshly-imported classic
--   from ever appearing in "what's new in my lab this week".
--
--   It also wouldn't fix the thing it's meant to fix. BibTeX usually carries only a
--   year, so every 2015 paper would land on 2015-01-01 — hundreds of exact ties,
--   ordered arbitrarily within each year. The artifact moves; it doesn't go away.
--
-- So: keep `posted_at` honest, store the publication date properly, and let the user
-- sort by whichever they actually mean.

alter table public.papers
    add column published_at date;   -- full date when we can get one; year → YYYY-01-01

comment on column public.papers.published_at is
    'When the paper was published. Distinct from paper_posts.posted_at (when a lab '
    'shared it). Day precision is often absent upstream — treat a Jan-1 date as '
    '"year only".';

-- Sorting a lab's corpus by publication date is the default view after a bulk import,
-- so it needs an index; nulls last, because "no date" is not "oldest".
create index papers_published_at_idx on public.papers (published_at desc nulls last);

-- Backfill from the year we already have, so existing corpora sort sensibly the
-- moment the UI offers the option.
update public.papers
   set published_at = make_date(year, 1, 1)
 where year is not null
   and year between 1500 and 2200      -- guard against junk years from metadata scrapes
   and published_at is null;

-- `source` records how a post got here. 'bibtex' lets the feed treat a 400-paper
-- import as one event rather than 400, and lets us find them again if an import
-- turns out to be wrong.
-- `if exists`: the constraint name is the Postgres default here, but a database
-- restored from a dump can carry a different generated name, and a bare drop would
-- abort the whole migration — including the published_at column the rest depends on.
alter table public.paper_posts
    drop constraint if exists paper_posts_source_check;

alter table public.paper_posts
    add constraint paper_posts_source_check
    check (source in ('web', 'teams_pdf', 'bibtex'));

-- === sort ==================================================================
-- The real fix for "a bulk import makes the ordering meaningless".
--
-- Importing 400 papers stamps 400 identical `posted_at`s, so "recently shared" —
-- the only order the app had — degenerates into an arbitrary tie-break. Rather than
-- corrupt `posted_at` with the publication date to compensate, give the user the sort
-- they actually mean.
--
--   shared    — when your lab posted it (the existing behaviour, still the default
--               for a lab that grows one paper at a time)
--   published — when the paper came out (what you want after importing a
--               back-catalogue)
--
-- Relevance still wins whenever there's a search query; sort only breaks the tie.

create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0,
    p_sort   text default 'shared'
)
returns setof public.paper_posts
language sql
stable
as $$
    select pp.*
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and (p_tag is null or pp.tags ? p_tag)
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      )
    order by
      (case
         when public.prefix_tsquery(p_q) is null then 0
         else ts_rank(
                to_tsvector('english',
                  coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, '')),
                public.prefix_tsquery(p_q)
              )
       end) desc,
      -- nulls last: a paper with no publication date is not the oldest paper.
      (case when p_sort = 'published' then p.published_at end) desc nulls last,
      pp.posted_at desc,
      pp.id desc   -- a total order, so paging can't drop or repeat a row across the
                   -- hundreds of identical posted_at values a bulk import creates
    limit  greatest(coalesce(p_limit, 30), 0)
    offset greatest(coalesce(p_offset, 0), 0);
$$;

-- `create or replace` with an added parameter OVERLOADS rather than replaces, so the
-- old 5-arg signature would linger and silently serve un-sorted results to any caller
-- that didn't pass p_sort. Drop it: there is one search_papers.
drop function if exists public.search_papers(uuid, text, text, int, int);
