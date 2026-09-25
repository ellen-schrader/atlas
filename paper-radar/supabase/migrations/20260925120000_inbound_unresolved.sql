-- 20260925120000_inbound_unresolved.sql — the queue of inbound links Atlas couldn't read.
--
-- An @Atlas mention whose URL the resolver can't turn into a paper is dropped
-- with nothing but a log line, and Fly keeps logs for about a week. Four
-- publisher-shape gaps (Elsevier PIIs, JCI, OUP, Lancet) were each found only
-- because a person noticed a paper missing, sometimes months later — and the
-- links already dropped cannot be recovered, because nothing recorded them.
--
-- So this is a queue, not a log: one row per (team, normalized URL), bumped
-- rather than duplicated when the same link is mentioned again, and closed once
-- the link finally imports. api/retry_unresolved.py re-drives the open rows
-- after the resolver learns a new publisher.

create table public.inbound_unresolved (
    id                bigint generated always as identity primary key,
    team_id           uuid not null references public.teams (id) on delete cascade,
    url               text not null,
    -- The same dedup key papers.url_norm holds, so a retry can tell that the
    -- link has since arrived under a different spelling and close the row.
    url_norm          text not null,
    sender_label      text,
    -- Why it failed — which is what says whether to write code or just retry:
    --   no_identifier          nothing in the URL to look up, and the landing
    --                          page gave nothing: a publisher shape we don't know
    --   identifier_unresolved  an id was found but no registry had it: usually a
    --                          derivation bug, like the OUP suffix truncation
    --   fetch_failed           the import raised (network, DB): transient
    reason            text not null check (
        reason in ('no_identifier', 'identifier_unresolved', 'fetch_failed')
    ),
    first_seen_at     timestamptz not null default now(),
    last_seen_at      timestamptz not null default now(),
    attempts          int not null default 1,
    resolved_at       timestamptz,
    resolved_paper_id uuid references public.papers (id) on delete set null,
    -- One row per link per lab; a re-mention bumps attempts instead of piling up.
    unique (team_id, url_norm)
);

-- Partial: the retry script and the "what is Atlas failing on" view both only
-- ever want the open rows, and closed ones accumulate forever.
create index inbound_unresolved_open_idx
    on public.inbound_unresolved (team_id, last_seen_at desc)
    where resolved_at is null;

alter table public.inbound_unresolved enable row level security;

-- Members can see what their lab posted that Atlas couldn't read. Same reasoning
-- as mcp_tool_calls: a record only the server can read is not visibility.
create policy inbound_unresolved_select on public.inbound_unresolved for select
    to authenticated using (is_team_member(team_id));

-- === grants (RLS still restricts rows) =====================================
-- Read-only for members: a row is a fact about what the resolver did, not user
-- content, so there is no member-facing insert/update. The inbound webhook runs
-- as the service role, which bypasses RLS but still needs table privileges —
-- omitting this is what made public.maps fail with 42501 (see 20260713200000).
grant select on public.inbound_unresolved to authenticated;
grant select, insert, update, delete on public.inbound_unresolved to service_role;
