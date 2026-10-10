-- Tag hygiene: one spelling per tag, and a place to record merges.
--
-- Until now tags were only lowercased (by the tagger and the web app), so
-- "Spatial transcriptomics", "spatial_transcriptomics" and "spatial-transcriptomics"
-- were three tags, and nothing could say that "tme" means "tumor-microenvironment".
--
--   1. normalise_tag: lowercase, trim, spaces/underscores -> hyphens, no repeated
--      or edge hyphens. The tagger (api/enrichment.py) applies the same rule.
--   2. tag_aliases: alias -> canonical. Filled by a reviewed follow-up migration
--      (proposals come from api/propose_tag_merges.py), never automatically.
--      Flat by construction: a canonical can't itself be an alias, and an alias
--      can't be anyone's canonical. clean_tags applies one hop, so a chain
--      (a -> b, b -> c) would store b, and a cycle would flip tags on each write.
--   3. clean_tags: normalise, map aliases, drop blanks and repeats (first
--      occurrence wins, order kept).
--   4. Triggers run clean_tags on every write to the four tag-holding columns:
--      papers.tags (AI, shared), paper_posts.tags (per lab), profiles.interests
--      (followed tags) and removed_posts.tags (undo archive). The web app writes
--      paper_posts.tags and profiles.interests directly, so this is the only
--      place a rule can hold for every writer.
--   5. apply_tag_cleanup rewrites existing rows; run once here, and again by the
--      merge migration after it inserts aliases.
--
-- figures.tags (mood board) is a separate vocabulary and is left alone.

create or replace function public.normalise_tag(p_tag text)
returns text
language sql
immutable
as $$
    select btrim(
        regexp_replace(
            regexp_replace(lower(btrim(coalesce(p_tag, ''))), '[\s_]+', '-', 'g'),
            '-{2,}', '-', 'g'),
        '-');
$$;

create table if not exists public.tag_aliases (
    alias      text primary key check (alias = public.normalise_tag(alias) and alias <> ''),
    canonical  text not null    check (canonical = public.normalise_tag(canonical) and canonical <> ''),
    created_at timestamptz not null default now(),
    check (alias <> canonical)
);

comment on table public.tag_aliases is
    'Tag merges: alias -> canonical. Applied by clean_tags on every write; see 20261010140000_tag_hygiene.sql.';

-- Service role only: the tagger and migrations read it; no client needs it.
alter table public.tag_aliases enable row level security;
-- Tables here get no default grants (see 20260713200000_maps_service_role_grant.sql),
-- so the tagger's service-role read needs one spelled out.
grant select, insert, update, delete on public.tag_aliases to service_role;

create or replace function public.tag_aliases_flat()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    if exists (select 1 from public.tag_aliases where alias = new.canonical) then
        raise exception 'tag_aliases: "%" is itself merged into another tag; point "%" at that tag instead',
            new.canonical, new.alias using errcode = 'check_violation';
    end if;
    if exists (select 1 from public.tag_aliases where canonical = new.alias and alias <> new.alias) then
        raise exception 'tag_aliases: "%" is the kept tag of other merges and can''t be merged away',
            new.alias using errcode = 'check_violation';
    end if;
    return new;
end;
$$;

drop trigger if exists tag_aliases_flat on public.tag_aliases;
create trigger tag_aliases_flat before insert or update on public.tag_aliases
    for each row execute function public.tag_aliases_flat();

-- Security definer so the alias lookup works when the trigger fires for a
-- signed-in user (the web app writing paper_posts.tags): tag_aliases has RLS on
-- and no policies, so as the caller it would read as empty and merges would
-- silently not apply. It only reads tag_aliases and returns a value.
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
        cross join lateral (select public.normalise_tag(e.raw) as tag) n
        left join public.tag_aliases a on a.alias = n.tag
        where n.tag <> ''
        group by 1
    ) s;
$$;

create or replace function public.clean_tags_trigger()
returns trigger
language plpgsql
set search_path = public
as $$
begin
    -- TG_ARGV[0] names the column, so one function serves all four tables.
    if TG_ARGV[0] = 'interests' then
        new.interests := public.clean_tags(new.interests);
    else
        new.tags := public.clean_tags(new.tags);
    end if;
    return new;
end;
$$;

drop trigger if exists clean_tags on public.papers;
create trigger clean_tags before insert or update of tags on public.papers
    for each row execute function public.clean_tags_trigger('tags');

drop trigger if exists clean_tags on public.paper_posts;
create trigger clean_tags before insert or update of tags on public.paper_posts
    for each row execute function public.clean_tags_trigger('tags');

drop trigger if exists clean_tags on public.removed_posts;
create trigger clean_tags before insert or update of tags on public.removed_posts
    for each row execute function public.clean_tags_trigger('tags');

drop trigger if exists clean_tags on public.profiles;
create trigger clean_tags before insert or update of interests on public.profiles
    for each row execute function public.clean_tags_trigger('interests');

-- Rewrite every stored tag through clean_tags. Only rows that change are
-- touched, so a re-run after adding aliases is cheap. Returns rows changed.
create or replace function public.apply_tag_cleanup()
returns table(tbl text, changed int)
language plpgsql
set search_path = public
as $$
declare
    n int;
begin
    update public.papers set tags = clean_tags(tags) where tags is distinct from clean_tags(tags);
    get diagnostics n = row_count;
    tbl := 'papers'; changed := n; return next;

    update public.paper_posts set tags = clean_tags(tags) where tags is distinct from clean_tags(tags);
    get diagnostics n = row_count;
    tbl := 'paper_posts'; changed := n; return next;

    update public.removed_posts set tags = clean_tags(tags) where tags is distinct from clean_tags(tags);
    get diagnostics n = row_count;
    tbl := 'removed_posts'; changed := n; return next;

    update public.profiles set interests = clean_tags(interests)
     where interests is distinct from clean_tags(interests);
    get diagnostics n = row_count;
    tbl := 'profiles'; changed := n; return next;
end;
$$;

-- The tagger's vocabulary: the AI tags already in use, most-used first. Over
-- papers.tags only (shared across labs, like the papers themselves); a lab's
-- hand-added tags stay that lab's. Service role only — it spans every lab.
create or replace function public.tag_vocabulary(p_limit int default 300)
returns table(tag text, n int)
language sql
stable
set search_path = public
as $$
    select t.tag, count(*)::int as n
    from public.papers p
    cross join lateral jsonb_array_elements_text(coalesce(p.tags, '[]'::jsonb)) as t(tag)
    group by t.tag
    order by n desc, t.tag
    limit greatest(coalesce(p_limit, 300), 0);
$$;

-- Which of p_tags are already AI tags on some paper. The tagger shows Claude
-- only the top of the vocabulary, so it asks this about the rest of a reply
-- before treating a tag as new. Service role only, like tag_vocabulary.
create or replace function public.existing_tags(p_tags text[])
returns setof text
language sql
stable
set search_path = public
as $$
    select distinct t.tag
    from public.papers p
    cross join lateral jsonb_array_elements_text(p.tags) as t(tag)
    where p.tags ?| p_tags
      and t.tag = any(p_tags);
$$;

-- Lets existing_tags' ?| find the papers by index rather than reading them all.
create index if not exists papers_tags_idx on public.papers using gin (tags);

revoke execute on function public.apply_tag_cleanup()      from public, anon, authenticated;
revoke execute on function public.tag_vocabulary(int)      from public, anon, authenticated;
revoke execute on function public.existing_tags(text[])    from public, anon, authenticated;
grant  execute on function public.apply_tag_cleanup()      to service_role;
grant  execute on function public.tag_vocabulary(int)      to service_role;
grant  execute on function public.existing_tags(text[])    to service_role;

select * from public.apply_tag_cleanup();
