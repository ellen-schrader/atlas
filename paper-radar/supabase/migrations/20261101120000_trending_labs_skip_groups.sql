-- 20261101120000_trending_labs_skip_groups.sql — trial groups aren't labs.
--
-- Trial papers end with a group ("KEYNOTE-522 Investigators", "CLEOPATRA Study
-- Group"), so the last-author proxy in trending_labs (20261008150000) put trial
-- groups on Home's Labs board. Two fixes:
--
-- 1. Repair author lists the BibTeX import split. It cut "{(IMpassion031 Trial
--    and Investigators)}" at the "and" into "(IMpassion031 Trial" and
--    "Investigators)", and kept the brackets round whole group names. Pieces
--    with an unclosed "(" are rejoined with " and " up to the piece that closes
--    it, and brackets wrapping a whole name go. Only lists holding a bracket
--    are touched. (paper_radar/ingest/bibtex.py no longer splits them.)
-- 2. trending_labs takes the last author that is a person: is_group_author()
--    skips group names, names wholly in brackets and split pieces. It is the
--    same rule as api/app.py _is_group_author; keep the two in step.

create or replace function pg_temp.rejoin_authors(a jsonb)
returns jsonb
language plpgsql
immutable
as $$
declare
    out_   jsonb := '[]'::jsonb;
    name_  text;
    held   text := null;
    pieces jsonb := '[]'::jsonb;  -- what `held` was built from
begin
    for name_ in select value from jsonb_array_elements_text(a) loop
        if held is not null then
            held := held || ' and ' || btrim(name_);
            pieces := pieces || to_jsonb(btrim(name_));
            if name_ like '%)%' then
                out_ := out_ || to_jsonb(held);
                held := null;
            end if;
        elsif name_ like '%(%' and name_ not like '%)%' then
            held := btrim(name_);
            pieces := jsonb_build_array(held);
        else
            out_ := out_ || to_jsonb(btrim(name_));
        end if;
    end loop;
    if held is not null then  -- never closed: keep the pieces as they were
        out_ := out_ || pieces;
    end if;
    -- "(KEYNOTE-522 Investigators)" -> "KEYNOTE-522 Investigators"
    return (
        select coalesce(jsonb_agg(
                   case when n ~ '^\(.*\)$' then btrim(substr(n, 2, length(n) - 2)) else n end
                   order by i), '[]'::jsonb)
        from jsonb_array_elements_text(out_) with ordinality as t(n, i)
    );
end;
$$;

update public.papers p
set authors = f.fixed
from (
    select id, pg_temp.rejoin_authors(authors) as fixed
    from public.papers
    where jsonb_typeof(authors) = 'array'
      and authors::text ~ '[()]'
) f
where p.id = f.id
  and p.authors is distinct from f.fixed;

-- A trial group or consortium, a name wholly in brackets, or a split piece of
-- one ("Investigators)"): not a person, so not a lab.
create or replace function public.is_group_author(name text)
returns boolean
language sql
immutable
set search_path = public
as $$
    select name ~* '\m(investigators?|group|consortium|collaborat\w*|committee|trialists|network|working party|on behalf of)\M'
        or btrim(name) ~ '^\(.*\)$'
        or (strpos(name, '(') > 0) <> (strpos(name, ')') > 0);
$$;

create or replace function public.trending_labs(
    p_team  uuid,
    p_days  int default 30,
    p_limit int default 5
)
returns table(lab text, n int, sharers int)
language sql
stable
set search_path = public
as $$
    select l.lab,
           count(distinct pp.paper_id)::int as n,
           count(distinct coalesce(pp.posted_by::text, pp.posted_by_label))::int as sharers
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    -- The last author who isn't a trial group or consortium.
    cross join lateral (
        select btrim(a.name) as lab
        from jsonb_array_elements_text(p.authors) with ordinality as a(name, i)
        where btrim(a.name) <> ''
          and not public.is_group_author(a.name)
        order by a.i desc
        limit 1
    ) l
    where pp.team_id = p_team
      and pp.posted_at >= now() - make_interval(days => p_days)
      and jsonb_typeof(p.authors) = 'array'
    group by 1
    order by n desc, sharers desc, lab
    limit greatest(coalesce(p_limit, 5), 0);
$$;
