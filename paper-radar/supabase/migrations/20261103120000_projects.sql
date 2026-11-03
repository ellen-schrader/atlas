-- 20261103120000_projects.sql — projects (docs/PROJECTS_PLAN.md, PR 1).
--
-- A project is a name, a one-line description and a set of the lab's papers,
-- seen by its owner, the whole lab or chosen people. It replaces topic maps
-- (retired in #186) and the reading-list projects of #181. Adding a paper to a
-- project does not save it to the reading list.
--
-- Ships dark behind the 'projects' feature (20261019150000): every policy and
-- function below checks has_feature(team, 'projects'), so a lab without the
-- switch reads and writes nothing, even straight from PostgREST.
--
-- Existing maps are carried over at the end: same id, the seed phrase becomes
-- the description (its embedding too, so nothing is re-embedded), pinned papers
-- go in, excluded papers are dismissed. The maps table itself stays until
-- projects are open to every lab.

-- === tables =================================================================

create table public.projects (
    id                    uuid primary key default gen_random_uuid(),
    team_id               uuid not null references public.teams (id) on delete cascade,
    -- Null once the owner has deleted their account (delete_account removes
    -- their private projects; shared ones stay for the people using them).
    owner_id              uuid references public.profiles (id) on delete set null,
    name                  text not null check (char_length(btrim(name)) between 1 and 120),
    description           text not null default '' check (char_length(description) <= 400),
    -- Embedded by the API (the Voyage key is server-side). Stands in for the
    -- papers while a project has fewer than three.
    description_embedding extensions.vector(1024),
    visibility            text not null default 'private'
                          check (visibility in ('private', 'lab', 'people')),
    -- Fewer / Balanced / More on the closeness chart: how far down to suggest.
    suggest_level         text not null default 'balanced'
                          check (suggest_level in ('fewer', 'balanced', 'more')),
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now()
);
create index projects_team_idx on public.projects (team_id);
create index projects_owner_idx on public.projects (owner_id);

-- Who can see a 'people' project, besides its owner. Ignored for other
-- visibilities, so switching back and forth keeps the list.
create table public.project_people (
    project_id uuid not null references public.projects (id) on delete cascade,
    user_id    uuid not null references public.profiles (id) on delete cascade,
    primary key (project_id, user_id)
);
create index project_people_user_idx on public.project_people (user_id);

-- A paper is in a project, or was dismissed from its suggestions ("Not
-- relevant"), which keeps it from being suggested again.
create table public.project_papers (
    project_id uuid not null references public.projects (id) on delete cascade,
    paper_id   uuid not null references public.papers (id) on delete cascade,
    state      text not null default 'in' check (state in ('in', 'dismissed')),
    added_by   uuid references public.profiles (id) on delete set null,
    added_at   timestamptz not null default now(),
    primary key (project_id, paper_id)
);
create index project_papers_paper_idx on public.project_papers (paper_id);
create index project_papers_added_by_idx on public.project_papers (added_by);

-- When each person last opened a project: "N new suggested" counts suggestions
-- the lab posted after it.
create table public.project_views (
    project_id     uuid not null references public.projects (id) on delete cascade,
    user_id        uuid not null references public.profiles (id) on delete cascade,
    last_viewed_at timestamptz not null default now(),
    primary key (project_id, user_id)
);
create index project_views_user_idx on public.project_views (user_id);

-- Tags and labs (last authors) a project follows: their papers in the related
-- pool are suggested even below the line.
create table public.project_follows (
    project_id uuid not null references public.projects (id) on delete cascade,
    kind       text not null check (kind in ('tag', 'lab')),
    value      text not null check (char_length(btrim(value)) between 1 and 200),
    created_at timestamptz not null default now(),
    primary key (project_id, kind, value)
);

-- === who can see a project ==================================================

-- The caller can see project `p`: the feature is on for them in its lab (which
-- includes being a member), and they own it, or it is shared with the lab, or
-- with them. SECURITY DEFINER so the policies on projects and project_people
-- can ask without recursing into each other.
create function public.can_see_project(p uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.projects pj
        where pj.id = p
          and public.has_feature(pj.team_id, 'projects')
          and (
              pj.owner_id = auth.uid()
              or pj.visibility = 'lab'
              or (pj.visibility = 'people' and exists (
                     select 1 from public.project_people pe
                     where pe.project_id = pj.id and pe.user_id = auth.uid()))
          )
    );
$$;

-- The caller owns project `p` and still has the feature in its lab.
create function public.owns_project(p uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.projects pj
        where pj.id = p
          and pj.owner_id = auth.uid()
          and public.has_feature(pj.team_id, 'projects')
    );
$$;

-- `paper` is in the library of project `p`'s lab: a project only holds the
-- lab's own papers.
create function public.in_project_lab(p uuid, paper uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.projects pj
        join public.paper_posts po on po.team_id = pj.team_id
        where pj.id = p and po.paper_id = paper
    );
$$;

-- `u` belongs to project `p`'s lab: a project is only shared within it.
create function public.in_project_team(p uuid, u uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.projects pj
        join public.team_members m on m.team_id = pj.team_id
        where pj.id = p and m.user_id = u
    );
$$;

revoke execute on function public.can_see_project(uuid) from public, anon;
revoke execute on function public.owns_project(uuid) from public, anon;
revoke execute on function public.in_project_lab(uuid, uuid) from public, anon;
revoke execute on function public.in_project_team(uuid, uuid) from public, anon;
grant execute on function public.can_see_project(uuid) to authenticated, service_role;
grant execute on function public.owns_project(uuid) to authenticated, service_role;
grant execute on function public.in_project_lab(uuid, uuid) to authenticated, service_role;
grant execute on function public.in_project_team(uuid, uuid) to authenticated, service_role;

-- === row level security =====================================================

alter table public.projects enable row level security;
alter table public.project_people enable row level security;
alter table public.project_papers enable row level security;
alter table public.project_views enable row level security;
alter table public.project_follows enable row level security;

-- Projects: anyone who can see one reads it; you create them in your own labs,
-- as yourself; only the owner renames, re-describes, shares or deletes. The
-- lab's owners may delete a shared project whose owner has left Atlas, which
-- nobody else could ever remove.
-- Spelled out rather than can_see_project(id): that function reads the table
-- in its own snapshot, which doesn't hold a row being inserted, so INSERT ...
-- RETURNING would fail its own select check.
create policy projects_select on public.projects for select
    to authenticated using (
        public.has_feature(team_id, 'projects')
        and (
            owner_id = auth.uid()
            or visibility = 'lab'
            or (visibility = 'people' and exists (
                   select 1 from public.project_people pe
                   where pe.project_id = projects.id and pe.user_id = auth.uid()))
        )
    );
create policy projects_insert on public.projects for insert
    to authenticated with check (
        owner_id = auth.uid() and public.has_feature(team_id, 'projects'));
create policy projects_update on public.projects for update
    to authenticated
    using (owner_id = auth.uid() and public.has_feature(team_id, 'projects'))
    with check (owner_id = auth.uid() and public.has_feature(team_id, 'projects'));
create policy projects_delete on public.projects for delete
    to authenticated using (owner_id = auth.uid() and public.has_feature(team_id, 'projects'));
create policy projects_delete_orphan on public.projects for delete
    to authenticated using (
        owner_id is null and public.is_team_owner(team_id)
        and public.has_feature(team_id, 'projects'));

-- The people list: seen by everyone who sees the project, kept by the owner,
-- and only ever lab members.
create policy project_people_select on public.project_people for select
    to authenticated using (public.can_see_project(project_id));
create policy project_people_insert on public.project_people for insert
    to authenticated with check (
        public.owns_project(project_id) and public.in_project_team(project_id, user_id));
create policy project_people_delete on public.project_people for delete
    to authenticated using (public.owns_project(project_id));

-- Papers and follows: everyone who can see a project can change them.
create policy project_papers_select on public.project_papers for select
    to authenticated using (public.can_see_project(project_id));
create policy project_papers_insert on public.project_papers for insert
    to authenticated with check (
        public.can_see_project(project_id)
        and public.in_project_lab(project_id, paper_id)
        and added_by = auth.uid());
create policy project_papers_update on public.project_papers for update
    to authenticated
    using (public.can_see_project(project_id))
    with check (public.can_see_project(project_id) and added_by = auth.uid());
create policy project_papers_delete on public.project_papers for delete
    to authenticated using (public.can_see_project(project_id));

create policy project_follows_select on public.project_follows for select
    to authenticated using (public.can_see_project(project_id));
create policy project_follows_insert on public.project_follows for insert
    to authenticated with check (public.can_see_project(project_id));
create policy project_follows_delete on public.project_follows for delete
    to authenticated using (public.can_see_project(project_id));

-- Views: your own row only.
create policy project_views_select on public.project_views for select
    to authenticated using (user_id = auth.uid() and public.can_see_project(project_id));
create policy project_views_insert on public.project_views for insert
    to authenticated with check (user_id = auth.uid() and public.can_see_project(project_id));
create policy project_views_update on public.project_views for update
    to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid() and public.can_see_project(project_id));

-- The lab and the owner never change after creation; a project moves nowhere.
grant select, insert, delete on public.projects to authenticated;
grant update (name, description, description_embedding, visibility, suggest_level, updated_at)
    on public.projects to authenticated;
grant select, insert, delete on public.project_people to authenticated;
grant select, insert, delete on public.project_papers to authenticated;
grant update (state, added_by, added_at) on public.project_papers to authenticated;
grant select, insert, delete on public.project_follows to authenticated;
grant select, insert on public.project_views to authenticated;
grant update (last_viewed_at) on public.project_views to authenticated;
grant select, insert, update, delete on
    public.projects, public.project_people, public.project_papers,
    public.project_views, public.project_follows
    to service_role;

-- Not for Claude connectors yet, like every table outside their read-list.
select public.close_to_connectors('public.projects');
select public.close_to_connectors('public.project_people');
select public.close_to_connectors('public.project_papers');
select public.close_to_connectors('public.project_views');
select public.close_to_connectors('public.project_follows');

-- === closeness ==============================================================

-- The last author who is a person, not a trial group: the "lab" of a paper, as
-- on Home's Labs board (trending_labs, 20261101120000).
create function public.last_person_author(authors jsonb)
returns text
language sql
immutable
set search_path = public
as $$
    select btrim(a.name)
    from jsonb_array_elements_text(
             case when jsonb_typeof(authors) = 'array' then authors else '[]'::jsonb end
         ) with ordinality as a(name, i)
    where btrim(a.name) <> ''
      and not public.is_group_author(a.name)
    order by a.i desc
    limit 1;
$$;

-- How close every paper in the project's lab is to the project, for the
-- closeness chart, the Suggested list and "Around this project".
--
--   similarity  cosine similarity to the closest paper in the project (for a
--               paper in it: the closest OTHER one), or to the description
--               while the project has fewer than three papers. Nearest paper
--               rather than the centroid, so a project with two strands isn't
--               suggested papers from the empty middle between them.
--   nearest_id  that closest paper; null when it was the description.
--   related     in the related pool: the 120 closest papers, plus the
--               project's own. "Around this project" counts over it.
--   suggested   'close' above the line; 'tag' or 'lab' for a related paper
--               from a tag or lab the project follows (`via` names it); null
--               for papers in the project or dismissed from it.
--   cutoff      the line. With three or more papers it is a percentile of the
--               project's own similarities (Fewer: the median, Balanced: the
--               25th, More: the 10th), so it adapts to how tight the project
--               is; before that, a fixed similarity to the description.
--
-- Every library paper with an embedding comes back (the chart draws the rest
-- faintly). One pass over the lab's papers against the project's papers: for
-- a few thousand papers and a few dozen in the project, a few hundred thousand
-- distances, computed in Postgres.
--
-- SECURITY INVOKER: a caller who can't see the project gets no project row and
-- so no papers.
create function public.project_closeness(p_project uuid)
returns table(
    paper_id   uuid,
    post_id    uuid,
    year       int,
    posted_at  timestamptz,
    similarity real,
    nearest_id uuid,
    state      text,
    related    boolean,
    suggested  text,
    via        text,
    cutoff     real
)
language sql
stable
set search_path = public, extensions
as $$
    with pr as materialized (
        select pj.id, pj.team_id, pj.description_embedding, pj.suggest_level
        from public.projects pj
        where pj.id = p_project
    ),
    members as materialized (
        select pp.paper_id, pp.state
        from public.project_papers pp
        where pp.project_id = (select id from pr)
    ),
    lib as materialized (
        select po.paper_id, po.id as post_id, p.year, po.posted_at, p.embedding,
               public.post_tags(po.tags, p.tags) as tags,
               public.last_person_author(p.authors) as lab
        from public.paper_posts po
        join public.papers p on p.id = po.paper_id
        where po.team_id = (select team_id from pr)
          and p.embedding is not null
    ),
    anchors as materialized (
        select l.paper_id, l.embedding
        from lib l
        join members m on m.paper_id = l.paper_id and m.state = 'in'
        union all
        select null, pr.description_embedding
        from pr
        where pr.description_embedding is not null
          and (select count(*) from lib l join members m
                 on m.paper_id = l.paper_id and m.state = 'in') < 3
    ),
    scored as materialized (
        select l.paper_id, l.post_id, l.year, l.posted_at, l.tags, l.lab,
               best.similarity, best.nearest_id, m.state
        from lib l
        left join members m on m.paper_id = l.paper_id
        left join lateral (
            select (1 - (l.embedding <=> a.embedding))::real as similarity,
                   a.paper_id as nearest_id
            from anchors a
            where a.paper_id is distinct from l.paper_id
            order by l.embedding <=> a.embedding
            limit 1
        ) best on true
    ),
    cut as (
        select (case
                    when count(*) >= 3 then percentile_cont(
                        case (select suggest_level from pr)
                            when 'fewer' then 0.5 when 'more' then 0.1 else 0.25 end
                    ) within group (order by s.similarity)
                    else case (select suggest_level from pr)
                             when 'fewer' then 0.5 when 'more' then 0.4 else 0.45 end
                end)::real as cutoff
        from scored s
        where s.state = 'in' and s.similarity is not null and s.nearest_id is not null
    ),
    ranked as (
        select s.*,
               (s.state = 'in'
                or row_number() over (order by s.similarity desc nulls last) <= 120) as related
        from scored s
    ),
    follows as materialized (
        select f.kind, f.value
        from public.project_follows f
        where f.project_id = (select id from pr)
    )
    select r.paper_id, r.post_id, r.year, r.posted_at, r.similarity, r.nearest_id,
           r.state, coalesce(r.related, false),
           case
               when r.state is not null or r.similarity is null then null
               when r.similarity >= c.cutoff then 'close'
               when r.related and ft.value is not null then 'tag'
               when r.related and fl.value is not null then 'lab'
           end as suggested,
           case
               when r.state is not null or r.similarity is null or r.similarity >= c.cutoff then null
               when r.related then coalesce(ft.value, fl.value)
           end as via,
           c.cutoff
    from ranked r
    cross join cut c
    left join lateral (
        select f.value from follows f
        where f.kind = 'tag' and r.tags ? f.value
        order by f.value limit 1
    ) ft on true
    left join lateral (
        select f.value from follows f
        where f.kind = 'lab' and f.value = r.lab
        limit 1
    ) fl on true
    order by r.similarity desc nulls last, r.paper_id;
$$;

-- One row per project the caller can see in a lab, for the projects index:
-- how many papers are in it, how many are suggested, and how many of those the
-- lab posted since the caller last opened it (all of them, if never).
create function public.project_summaries(p_team uuid)
returns table(project_id uuid, n_in int, n_suggested int, n_new int)
language sql
stable
set search_path = public, extensions
as $$
    select pj.id,
           count(*) filter (where c.state = 'in')::int,
           count(*) filter (where c.suggested is not null)::int,
           count(*) filter (
               where c.suggested is not null
                 and c.posted_at > coalesce(v.last_viewed_at, '-infinity'))::int
    from public.projects pj
    left join public.project_views v on v.project_id = pj.id and v.user_id = auth.uid()
    left join lateral public.project_closeness(pj.id) c on true
    where pj.team_id = p_team
    group by pj.id;
$$;

-- The caller has opened project `p` now: what the index's "N new" counts from.
-- An upsert PostgREST can't express with update granted on one column only.
create function public.mark_project_viewed(p uuid)
returns void
language sql
set search_path = public
as $$
    insert into public.project_views (project_id, user_id, last_viewed_at)
    values (p, auth.uid(), now())
    on conflict (project_id, user_id) do update set last_viewed_at = excluded.last_viewed_at;
$$;

revoke execute on function public.project_closeness(uuid) from public, anon;
revoke execute on function public.mark_project_viewed(uuid) from public, anon;
revoke execute on function public.project_summaries(uuid) from public, anon;
grant execute on function public.last_person_author(jsonb) to authenticated, service_role;
grant execute on function public.project_closeness(uuid) to authenticated, service_role;
grant execute on function public.project_summaries(uuid) to authenticated, service_role;
grant execute on function public.mark_project_viewed(uuid) to authenticated;

-- === maps become projects ===================================================

insert into public.projects
    (id, team_id, owner_id, name, description, description_embedding, visibility,
     created_at, updated_at)
select m.id, m.team_id, m.created_by,
       coalesce(nullif(left(btrim(m.name), 120), ''), 'Untitled project'),
       left(m.seed, 400), m.seed_embedding, m.visibility, m.created_at, m.updated_at
from public.maps m;

insert into public.project_papers (project_id, paper_id, state, added_by, added_at)
select m.id, p.id, 'in', m.created_by, m.updated_at
from public.maps m
cross join lateral jsonb_array_elements_text(
    case when jsonb_typeof(m.config -> 'pinned') = 'array' then m.config -> 'pinned' else '[]'::jsonb end
) x(pid)
join public.papers p on p.id::text = x.pid
on conflict do nothing;

insert into public.project_papers (project_id, paper_id, state, added_by, added_at)
select m.id, p.id, 'dismissed', m.created_by, m.updated_at
from public.maps m
cross join lateral jsonb_array_elements_text(
    case when jsonb_typeof(m.config -> 'excluded') = 'array' then m.config -> 'excluded' else '[]'::jsonb end
) x(pid)
join public.papers p on p.id::text = x.pid
on conflict do nothing;  -- pinned and excluded both: pinned wins

-- === papers merged, accounts deleted ========================================

-- merge_papers is copied from 20261101184500_recommendation_thumbs.sql with
-- step 4b added: project_papers cascades on the paper, so without it a merge
-- would drop the old copy from every project. Same signature, so grants stay.
create or replace function public.merge_papers(p_from uuid, p_into uuid, p_reason text)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
    src   public.papers;
    dst   public.papers;
    held  jsonb;
    alias  uuid;
    folded uuid[];
begin
    if p_from = p_into then
        raise exception 'Cannot merge a paper into itself.' using errcode = '22023';
    end if;

    -- Lock in id order, so two merges touching the same pair cannot deadlock.
    perform 1 from public.papers where id in (p_from, p_into) order by id for update;
    select * into src from public.papers where id = p_from;
    if not found then
        raise exception 'Paper % no longer exists.', p_from using errcode = 'no_data_found';
    end if;
    select * into dst from public.papers where id = p_into;
    if not found then
        raise exception 'Paper % no longer exists.', p_into using errcode = 'no_data_found';
    end if;

    -- 1. Lab posts. Where a lab holds both, fold the old post into the kept one
    --    and delete it; the rest move. The delete fires capture_removed_post(),
    --    whose tombstone would offer "undo" for a removal nobody made, so it is
    --    deleted straight after.
    update public.paper_posts d set
        tags            = (select coalesce(jsonb_agg(distinct t), '[]'::jsonb)
                             from jsonb_array_elements(d.tags || s.tags) t),
        note            = case
                              when nullif(btrim(s.note), '') is null or s.note = d.note then d.note
                              when nullif(btrim(d.note), '') is null then s.note
                              else d.note || E'\n\n' || s.note
                          end,
        posted_at       = least(d.posted_at, s.posted_at),
        posted_by       = case when s.posted_at < d.posted_at then s.posted_by else d.posted_by end,
        posted_by_label = case when s.posted_at < d.posted_at then s.posted_by_label else d.posted_by_label end,
        source          = case when s.posted_at < d.posted_at then s.source else d.source end,
        source_pdf      = case when s.posted_at < d.posted_at then s.source_pdf else d.source_pdf end,
        page            = case when s.posted_at < d.posted_at then s.page else d.page end,
        via             = case when s.posted_at < d.posted_at then s.via else d.via end
      from public.paper_posts s
     where s.paper_id = p_from and d.paper_id = p_into and d.team_id = s.team_id;

    -- Two statements, not one with a CTE: the trigger is AFTER, so it only
    -- writes the tombstone once the delete statement has finished.
    with gone as (
        delete from public.paper_posts s
         where s.paper_id = p_from
           and exists (select 1 from public.paper_posts d where d.paper_id = p_into and d.team_id = s.team_id)
        returning s.id
    )
    select coalesce(array_agg(id), '{}') into folded from gone;
    delete from public.removed_posts where id = any (folded);

    update public.paper_posts set paper_id = p_into where paper_id = p_from;

    -- 2. Reactions: move what doesn't already exist on the kept paper.
    delete from public.reactions s
     where s.paper_id = p_from
       and exists (
           select 1 from public.reactions d
            where d.paper_id = p_into and d.team_id = s.team_id
              and d.user_id = s.user_id and d.emoji = s.emoji
       );
    update public.reactions set paper_id = p_into where paper_id = p_from;

    -- 3. Reading status: saved on either axis stays saved; progress takes the
    --    further of the two (unread < reading < read).
    update public.paper_status d set
        saved      = d.saved or s.saved,
        status     = case
                         when 'read' in (d.status, s.status) then 'read'
                         when 'reading' in (d.status, s.status) then 'reading'
                         else 'unread'
                     end,
        updated_at = greatest(d.updated_at, s.updated_at),
        -- An answer to either copy is an answer about the paper. One answer per
        -- row (paper_status_one_answer), so the newest of the four wins: the
        -- newest 👍 if it is newer than the newest 👎, else the newest 👎.
        -- greatest() skips nulls, so an unanswered copy changes nothing.
        liked_at     = case
                           when greatest(d.liked_at, s.liked_at)
                                > coalesce(greatest(d.dismissed_at, s.dismissed_at), '-infinity')
                           then greatest(d.liked_at, s.liked_at)
                       end,
        dismissed_at = case
                           when greatest(d.dismissed_at, s.dismissed_at)
                                >= coalesce(greatest(d.liked_at, s.liked_at), '-infinity')
                           then greatest(d.dismissed_at, s.dismissed_at)
                       end
      from public.paper_status s
     where s.paper_id = p_from and d.paper_id = p_into
       and d.user_id = s.user_id and d.team_id = s.team_id;
    delete from public.paper_status s
     where s.paper_id = p_from
       and exists (
           select 1 from public.paper_status d
            where d.paper_id = p_into and d.user_id = s.user_id and d.team_id = s.team_id
       );
    update public.paper_status set paper_id = p_into where paper_id = p_from;

    -- 4. No uniqueness on the paper: these just move.
    update public.comments           set paper_id = p_into where paper_id = p_from;
    update public.mentions           set paper_id = p_into where paper_id = p_from;
    update public.figures            set paper_id = p_into where paper_id = p_from;
    update public.paper_edits        set paper_id = p_into where paper_id = p_from;
    update public.removed_posts      set paper_id = p_into where paper_id = p_from;
    update public.inbound_unresolved set resolved_paper_id = p_into where resolved_paper_id = p_from;
    update public.paper_aliases      set paper_id = p_into where paper_id = p_from;
    -- A person told about both papers keeps the kept paper's notice.
    delete from public.notifications s
     where s.paper_id = p_from
       and exists (
           select 1 from public.notifications d
            where d.paper_id = p_into and d.user_id = s.user_id
              and d.team_id = s.team_id and d.kind = s.kind
       );
    update public.notifications      set paper_id = p_into where paper_id = p_from;

    -- 4b. Projects: where a project holds both, keep one row, in the project
    --     if either copy was; the rest move.
    update public.project_papers d set
        state    = case when 'in' in (d.state, s.state) then 'in' else 'dismissed' end,
        added_at = least(d.added_at, s.added_at)
      from public.project_papers s
     where s.paper_id = p_from and d.paper_id = p_into and d.project_id = s.project_id;
    delete from public.project_papers s
     where s.paper_id = p_from
       and exists (
           select 1 from public.project_papers d
            where d.paper_id = p_into and d.project_id = s.project_id
       );
    update public.project_papers set paper_id = p_into where paper_id = p_from;

    -- 5. Paper ids held in jsonb, without a foreign key to cascade.
    update public.maps set config = jsonb_set(config, '{pinned}', public.jsonb_swap_id(config -> 'pinned', p_from, p_into))
     where config -> 'pinned' ? p_from::text;
    update public.maps set config = jsonb_set(config, '{excluded}', public.jsonb_swap_id(config -> 'excluded', p_from, p_into))
     where config -> 'excluded' ? p_from::text;
    update public.maps set ai_summary = jsonb_set(ai_summary, '{cited_ids}', public.jsonb_swap_id(ai_summary -> 'cited_ids', p_from, p_into))
     where ai_summary -> 'cited_ids' ? p_from::text;
    update public.trends set paper_ids = public.jsonb_swap_id(paper_ids, p_from, p_into)
     where paper_ids ? p_from::text;

    -- 6. Fill what the kept paper lacks. A new title or abstract changes what the
    --    embedding and tags were computed from, so both are queued again.
    held := dst.edited_fields;
    update public.papers set
        title       = case when nullif(btrim(dst.title), '') is null and not held ? 'title'
                           then coalesce(src.title, dst.title) else dst.title end,
        authors     = case when dst.authors = '[]'::jsonb and not held ? 'authors'
                           then src.authors else dst.authors end,
        year        = case when dst.year is null and not held ? 'year'
                           then src.year else dst.year end,
        abstract    = case when nullif(btrim(dst.abstract), '') is null and not held ? 'abstract'
                           then coalesce(src.abstract, dst.abstract) else dst.abstract end,
        code_url    = case when dst.code_url is null and not held ? 'code_url'
                           then src.code_url else dst.code_url end,
        data_url    = case when dst.data_url is null and not held ? 'data_url'
                           then src.data_url else dst.data_url end,
        keywords    = case when dst.keywords = '[]'::jsonb and not held ? 'keywords'
                           then src.keywords else dst.keywords end,
        tags        = (select coalesce(jsonb_agg(distinct t), '[]'::jsonb)
                         from jsonb_array_elements(dst.tags || src.tags) t)
     where id = p_into;
    update public.papers set embedded_at = null, enriched_at = null
     where id = p_into
       and (title, abstract) is distinct from (dst.title, dst.abstract);

    -- 7. Remember the old row, then delete it. Nothing references it any more,
    --    so the cascade has nothing left to do. Its DOI or url_norm can already
    --    be an alias key — a third copy of one DOI, or a merged preprint posted
    --    again before ingest read aliases — and those keys already lead to a
    --    paper, so this alias goes without them rather than failing the merge.
    insert into public.paper_aliases (paper_id, kind, reason, doi, url, url_norm, venue, old_paper_id, snapshot)
    values (
        p_into,
        case when p_reason = 'doi_case' then 'duplicate' else 'preprint' end,
        p_reason,
        case when exists (select 1 from public.paper_aliases where doi = lower(src.doi))
             then null else lower(src.doi) end,
        src.url,
        case when exists (select 1 from public.paper_aliases where url_norm = src.url_norm)
             then null else src.url_norm end,
        src.venue,
        src.id,
        to_jsonb(src) - 'embedding'
    )
    returning id into alias;

    delete from public.papers where id = p_from;
    return alias;
end;
$$;

-- delete_account is copied from 20261019140000_delete_account.sql with the
-- private projects removed alongside the private maps. Same signature, so the
-- grants (service role only) stay.
create or replace function public.delete_account(p_user uuid, p_confirm_email text)
returns uuid[]
language plpgsql
security definer
set search_path = public
as $$
declare
    v_email text;
    v_teams uuid[];
    v_blocking text;
    v_solo uuid[];
begin
    select email into v_email from auth.users where id = p_user;
    if v_email is null then
        raise exception 'No such account' using errcode = '42704';
    end if;
    if lower(trim(coalesce(p_confirm_email, ''))) <> lower(v_email) then
        raise exception 'The email doesn''t match this account' using errcode = '22023';
    end if;

    -- Lock the user's labs first. Joining a lab inserts a member row whose
    -- foreign key takes a KEY SHARE lock on the team, which FOR UPDATE blocks;
    -- a co-owner deleting at the same moment waits here too. So the checks
    -- below can't be overtaken by a join or by another deletion.
    select coalesce(array_agg(t.id), '{}') into v_teams
    from (
        select t.id from public.teams t
        join public.team_members me on me.team_id = t.id and me.user_id = p_user
        order by t.id
        for update of t
    ) t;

    -- Last owner of a lab that still has other members: refuse, naming the labs,
    -- as leave_team does for one lab.
    select string_agg(t.name, ', ' order by t.name) into v_blocking
    from public.team_members me
    join public.teams t on t.id = me.team_id
    where me.user_id = p_user
      and me.role = 'owner'
      and not exists (
          select 1 from public.team_members o
          where o.team_id = me.team_id and o.role = 'owner' and o.user_id <> p_user)
      and exists (
          select 1 from public.team_members m
          where m.team_id = me.team_id and m.user_id <> p_user);
    if v_blocking is not null then
        raise exception 'Make someone else an owner of % first', v_blocking
            using errcode = 'P0001';
    end if;

    -- Labs they're alone in go with them. Their posts cascade, and the removal
    -- trigger turns each into a removed_posts tombstone; those go too, since the
    -- lab they'd be restored into no longer exists.
    select coalesce(array_agg(me.team_id), '{}') into v_solo
    from public.team_members me
    where me.team_id = any (v_teams)
      and me.user_id = p_user
      and not exists (
          select 1 from public.team_members m
          where m.team_id = me.team_id and m.user_id <> p_user);
    delete from public.teams where id = any (v_solo);
    delete from public.removed_posts where team_id = any (v_solo);

    -- Tombstones in labs that stay: drop the user's id (not a foreign key, so
    -- nothing else will), which also keeps restore_post working, since it
    -- copies posted_by back into paper_posts.
    update public.removed_posts set posted_by = null where posted_by = p_user;
    update public.removed_posts set removed_by = null where removed_by = p_user;

    -- Private maps are theirs alone; lab maps stay, without their name.
    delete from public.maps where created_by = p_user and visibility = 'private';
    -- Private projects too; shared ones stay, without an owner, for the
    -- people using them (a lab owner can delete them).
    delete from public.projects where owner_id = p_user and visibility = 'private';

    -- Everything else follows from the auth user: the profile cascades, and with
    -- it memberships, reactions, reading list, notifications, sessions and Claude
    -- grants; posts, comments, figures, lab maps and shared projects keep their
    -- rows with a null author.
    delete from auth.users where id = p_user;

    return v_solo;
end;
$$;
