-- 20260712130000_paper_search.sql — two improvements to paper search, shared by
-- the Papers page and the mood board's "link a paper" picker (both call
-- search_papers). Supersedes the title/abstract-only, whole-word version in
-- 20260712101500_search_rpcs.sql.
--
--   1. Author names are searchable. `authors` is a jsonb array of names; casting
--      it to text is IMMUTABLE, so it can join the indexed tsvector. Typing an
--      author surfaces their papers. We rebuild papers_fts_idx to match the new
--      tsvector expression exactly, keeping search index-backed.
--
--   2. Prefix (type-ahead) matching. websearch_to_tsquery matches whole lexemes,
--      so "fibro" would not find "Fibroblast" (different stems). prefix_tsquery
--      turns each typed token into `token:*` AND-ed together, so partial words
--      match as you type. It also sanitises input (splits on non-alphanumerics,
--      feeds only bare tokens to to_tsquery) so arbitrary text can't raise a
--      syntax error — the reason websearch_to_tsquery was used originally. Empty
--      / all-symbol input yields NULL, which callers treat as "no filter".

drop index if exists public.papers_fts_idx;
create index papers_fts_idx on public.papers
    using gin (to_tsvector(
        'english',
        coalesce(title, '') || ' ' || coalesce(abstract, '') || ' ' || coalesce(authors::text, '')
    ));

create or replace function public.prefix_tsquery(p_q text)
returns tsquery
language sql
immutable
as $$
    select to_tsquery(
        'english',
        (select string_agg(tok || ':*', ' & ')
         from unnest(regexp_split_to_array(lower(coalesce(p_q, '')), '[^a-z0-9]+')) as tok
         where tok <> '')
    );
$$;

grant execute on function public.prefix_tsquery(text) to authenticated;

-- Full-text search over a lab's posts (title + abstract + authors), prefix-matched
-- and ranked by relevance then recency. Returns `setof paper_posts` so the client
-- can embed the paper: supabase.rpc('search_papers', {...}).select('*, papers(*)')
create or replace function public.search_papers(
    p_team   uuid,
    p_q      text default '',
    p_tag    text default null,
    p_limit  int  default 30,
    p_offset int  default 0
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
      pp.posted_at desc
    limit  greatest(coalesce(p_limit, 30), 0)
    offset greatest(coalesce(p_offset, 0), 0);
$$;

-- Total matches for the same filters (for the "N results" label + paging end).
create or replace function public.search_papers_count(
    p_team uuid,
    p_q    text default '',
    p_tag  text default null
)
returns integer
language sql
stable
as $$
    select count(*)::int
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and (p_tag is null or pp.tags ? p_tag)
      and (
        public.prefix_tsquery(p_q) is null
        or to_tsvector('english',
             coalesce(p.title, '') || ' ' || coalesce(p.abstract, '') || ' ' || coalesce(p.authors::text, ''))
           @@ public.prefix_tsquery(p_q)
      );
$$;
