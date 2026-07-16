-- Allow paper_posts ingested live from a Microsoft Teams channel
-- (docs/teams-integration-plan.md). 'teams_pdf' stays for the legacy
-- exported-PDF importer; 'teams' marks live channel ingestion and is the
-- loop guard for the outbound mirror (source='teams' is never echoed back).

alter table public.paper_posts
    drop constraint paper_posts_source_check;
alter table public.paper_posts
    add constraint paper_posts_source_check
        check (source in ('web', 'teams_pdf', 'teams'));
