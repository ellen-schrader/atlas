-- British and American spelling find each other (and tags use one of them).
--
-- Typing "tumour" found only "tumour…", and "tumor" missed every UK-spelled
-- abstract (Lancet, BJC, CRUK-funded work). Semantic search already copes;
-- keyword search and the filter menus didn't.
--
--   1. spelling_rules: a curated list of UK <-> US pairs for biomedical text —
--      -our/-or, ae/oe -> e (haem-, oesoph-, oestr-, leukaemia…), -re/-er,
--      doubled l (signalling), a fixed word list for -ise/-isation, and a few
--      others. Hand-picked, not blanket rules: "noise", "precise", "raised",
--      "analysis" and "programmed" must not change. \m anchors a rule to the
--      start of a word, so "imaging" never matches "aging"; the -ise list needs a
--      real -ise ending, so "metabolism" and "organism" stay as they are.
--   2. us_spelling / uk_spelling apply the rules in one direction.
--   3. prefix_tsquery — the query builder behind every keyword search (Papers,
--      the home search box, the Atlas MCP) — matches each word in either
--      spelling: (tumour:* | tumor:*). Ranking and the index are unchanged.
--   4. team_tags / team_venues compare the typed text and the name in US
--      spelling, so "tumour" finds tumor-microenvironment in the filter menus.
--      Authors are names and are left as typed.
--   5. Tags use American spelling: clean_tags folds a tag to US spelling
--      before applying merges, on every write, and existing tags are
--      rewritten (originals saved in tag_merge_backup, batch 'spelling-us').

create or replace function public.spelling_rules()
returns table(uk_re text, us_repl text, us_re text, uk_repl text)
language sql
immutable
as $$
    values
        -- -our / -or
        ('tumour',     'tumor',     'tumor',     'tumour'),
        ('colour',     'color',     'color',     'colour'),
        ('behaviour',  'behavior',  'behavior',  'behaviour'),
        ('favour',     'favor',     'favor',     'favour'),
        ('neighbour',  'neighbor',  'neighbor',  'neighbour'),
        ('\mlabour',   'labor',     '\mlabor\M', 'labour'),
        -- ae / oe -> e
        ('\mhaem',     'hem',       '\mhem',     'haem'),
        ('\manaesth',  'anesth',    '\manesth',  'anaesth'),
        ('aemi',       'emi',       'emi(a|c)',  'aemi\1'),
        ('\moesoph',   'esoph',     '\mesoph',   'oesoph'),
        ('\moestr',    'estr',      '\mestr',    'oestr'),
        ('\moedem',    'edem',      '\medem',    'oedem'),
        ('\mfoet',     'fet',       '\mfet(al|us)', 'foet\1'),
        ('\mfaec',     'fec',       '\mfec(al|es)', 'faec\1'),
        ('paediatr',   'pediatr',   'pediatr',   'paediatr'),
        ('orthopaed',  'orthoped',  'orthoped',  'orthopaed'),
        ('gynaec',     'gynec',     'gynec',     'gynaec'),
        -- -re / -er
        ('centre',     'center',    'center',    'centre'),
        ('fibre',      'fiber',     'fiber',     'fibre'),
        ('litre',      'liter',     'liter',     'litre'),
        -- doubled l
        ('signall',    'signal',    'signal(ing|ed)', 'signall\1'),
        ('modell',     'model',     'model(ing|ed|er)', 'modell\1'),
        ('labell',     'label',     'label(ing|ed)', 'labell\1'),
        -- -ise / -isation: a fixed word list, never a blanket "ise" rule, and only
        -- before a real -ise ending, or metabolism/organism/specialist would change
        ('\m(characteri|normali|optimi|organi|recogni|visuali|utili|minimi|maximi|randomi|immuni|standardi|stabili|mobili|locali|generali|categori|hospitali|personali|prioriti|summari|vectori|tokeni|parameteri|digiti|synchroni|speciali|harmoni|sensiti|desensiti|metaboli|polari|neutrali|sterili)s(e|ed|es|er|ers|ing|ation|ations)',
         '\1z\2',
         '\m(characteri|normali|optimi|organi|recogni|visuali|utili|minimi|maximi|randomi|immuni|standardi|stabili|mobili|locali|generali|categori|hospitali|personali|prioriti|summari|vectori|tokeni|parameteri|digiti|synchroni|speciali|harmoni|sensiti|desensiti|metaboli|polari|neutrali|sterili)z(e|ed|es|er|ers|ing|ation|ations)',
         '\1s\2'),
        -- others ("analyses" is left alone: it is also the plural of analysis)
        ('\manalys(e|ed|ing)\M', 'analyz\1', '\manalyz', 'analys'),
        ('\mprogramme(s?)\M',    'program\1', '\mprogram(s?)\M', 'programme\1'),
        ('\mageing\M',           'aging',     '\maging\M',       'ageing'),
        ('\mgrey\M',             'gray',      '\mgray\M',        'grey'),
        ('sulph',                'sulf',      'sulf',            'sulph')
$$;

create or replace function public.us_spelling(p_text text)
returns text
language plpgsql
immutable
as $$
declare
    r record;
    t text := p_text;
begin
    if t is null or t = '' then
        return t;
    end if;
    for r in select uk_re, us_repl from public.spelling_rules() loop
        t := regexp_replace(t, r.uk_re, r.us_repl, 'g');
    end loop;
    return t;
end;
$$;

create or replace function public.uk_spelling(p_text text)
returns text
language plpgsql
immutable
as $$
declare
    r record;
    t text := p_text;
begin
    if t is null or t = '' then
        return t;
    end if;
    for r in select us_re, uk_repl from public.spelling_rules() loop
        t := regexp_replace(t, r.us_re, r.uk_repl, 'g');
    end loop;
    return t;
end;
$$;

-- Reissued from 20260712130000_paper_search.sql: each word now matches in its
-- typed, US and UK spelling. A word with no variant gives the same tsquery as
-- before.
create or replace function public.prefix_tsquery(p_q text)
returns tsquery
language sql
immutable
as $$
    select to_tsquery(
        'english',
        (select string_agg(
                    '(' || (select string_agg(v || ':*', ' | ')
                            from (select distinct v
                                  from unnest(array[tok, public.us_spelling(tok), public.uk_spelling(tok)]) as v
                                  where v <> '') vs)
                    || ')',
                    ' & ')
         from unnest(regexp_split_to_array(lower(coalesce(p_q, '')), '[^a-z0-9]+')) as tok
         where tok <> '')
    );
$$;

-- Reissued from 20261010120000_author_filter.sql; only the p_q match changes.
create or replace function public.team_tags(
    p_team  uuid,
    p_q     text default null,
    p_limit int  default null
)
returns table(tag text, n int)
language sql
stable
as $$
    select t.tag, count(*)::int as n
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    cross join lateral jsonb_array_elements_text(public.post_tags(pp.tags, p.tags)) as t(tag)
    where pp.team_id = p_team
      and (coalesce(p_q, '') = ''
           or position(public.us_spelling(lower(p_q)) in public.us_spelling(lower(t.tag))) > 0)
    group by t.tag
    order by n desc, t.tag
    limit p_limit;
$$;

create or replace function public.team_venues(
    p_team  uuid,
    p_q     text default null,
    p_limit int  default null
)
returns table (venue text, count bigint)
language sql
stable
as $$
    select p.venue, count(*) as count
    from public.paper_posts pp
    join public.papers p on p.id = pp.paper_id
    where pp.team_id = p_team
      and p.venue is not null
      and p.venue <> ''
      and (coalesce(p_q, '') = ''
           or position(public.us_spelling(lower(p_q)) in public.us_spelling(lower(p.venue))) > 0)
    group by p.venue
    order by count(*) desc, p.venue
    limit p_limit;
$$;

-- Reissued from 20261010140000_tag_hygiene.sql: a tag is folded to US spelling
-- after normalising and before merges are applied, so tag_aliases only ever
-- needs the US form.
create or replace function public.clean_tags(p_tags jsonb)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
    select coalesce(jsonb_agg(s.tag order by s.first_pos), '[]'::jsonb)
    from (
        select coalesce(a.canonical, n.tag) as tag, min(e.ord) as first_pos
        from jsonb_array_elements_text(
                 case when jsonb_typeof(p_tags) = 'array' then p_tags else '[]'::jsonb end
             ) with ordinality as e(raw, ord)
        cross join lateral (select public.us_spelling(public.normalise_tag(e.raw)) as tag) n
        left join public.tag_aliases a on a.alias = n.tag
        where n.tag <> ''
        group by 1
    ) s;
$$;

-- Rewrite UK-spelled tags already stored, saving the originals first.
insert into public.tag_merge_backup (batch, tbl, row_id, old_tags)
select 'spelling-us', 'papers', id, tags from public.papers
 where tags is distinct from public.clean_tags(tags)
union all
select 'spelling-us', 'paper_posts', id, tags from public.paper_posts
 where tags is distinct from public.clean_tags(tags)
union all
select 'spelling-us', 'removed_posts', id, tags from public.removed_posts
 where tags is distinct from public.clean_tags(tags)
union all
select 'spelling-us', 'profiles', id, interests from public.profiles
 where interests is distinct from public.clean_tags(interests);

select * from public.apply_tag_cleanup();
