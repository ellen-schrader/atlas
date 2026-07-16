-- 20260716150000_team_integrations.sql — per-lab Teams webhook, self-service.
--
-- Replaces the operator-only TEAMS_WEBHOOK_URLS env map (kept as a fallback):
-- lab owners paste their Power Automate "Workflows" webhook URL in Settings.
--
-- Security posture:
--   * The webhook URL is a bearer capability — anyone holding it can post cards
--     into the lab's Teams channel. RLS is owner-only on ALL verbs (members
--     cannot even read it), mirroring the owner-only lab-management RPCs.
--   * The server POSTs to this URL, so a stored value is an SSRF vector. The
--     API layer validates on save AND on send (api/teams_integration.py); this
--     CHECK is defense in depth so a direct PostgREST write can't store
--     anything but an https Power Automate host on the default port.
--     Charset: no '@' (credentials), no '/' before the host match ends, and
--     lowercase-only (the API normalizes; uppercase host tricks are rejected,
--     not smuggled).

create table public.team_integrations (
    team_id     uuid primary key references public.teams (id) on delete cascade,
    webhook_url text not null,
    enabled     boolean not null default true,
    created_by  uuid references public.profiles (id) on delete set null,
    updated_at  timestamptz not null default now(),
    constraint team_integrations_webhook_len
        check (char_length(webhook_url) <= 2048),
    constraint team_integrations_webhook_host
        check (webhook_url ~ '^https://[a-z0-9][a-z0-9.-]*\.(logic\.azure\.com|api\.powerplatform\.com)(:443)?/')
);

alter table public.team_integrations enable row level security;

create policy team_integrations_select on public.team_integrations for select
    using (public.is_team_owner(team_id));
create policy team_integrations_insert on public.team_integrations for insert
    with check (public.is_team_owner(team_id));
create policy team_integrations_update on public.team_integrations for update
    using (public.is_team_owner(team_id))
    with check (public.is_team_owner(team_id));
create policy team_integrations_delete on public.team_integrations for delete
    using (public.is_team_owner(team_id));

-- Table privileges (RLS still restricts rows). `authenticated` needs them for the
-- owner-managed Settings panel; `service_role` for the outbound send path's read.
-- The one-time blanket grant in rls.sql predates this table, so grant explicitly.
grant select, insert, update, delete on public.team_integrations to authenticated;
grant all                            on public.team_integrations to service_role;
