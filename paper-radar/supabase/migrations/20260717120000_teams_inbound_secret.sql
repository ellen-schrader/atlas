-- 20260717120000_teams_inbound_secret.sql — inbound Teams ingestion (M2, papers).
--
-- Adds the HMAC secret for a lab's Teams *Outgoing Webhook* (distinct from the
-- outbound Workflows webhook_url). When someone writes "@Atlas <link>" in the
-- channel, Teams POSTs the message to the public /integrations/teams/inbound/
-- endpoint signed with this token; the server verifies the HMAC and imports the
-- paper (source='teams').
--
-- Security: this is a bearer secret (it authenticates inbound requests). It
-- lives on the same owner-only-RLS row as webhook_url, so members can't read it,
-- and the API never returns it to the browser (only whether it is configured).

alter table public.team_integrations
    add column inbound_secret text;

alter table public.team_integrations
    add constraint team_integrations_inbound_secret_len
        check (inbound_secret is null or char_length(inbound_secret) <= 1024);
