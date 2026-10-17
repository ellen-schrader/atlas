-- 20261017130000_preprint_venues.sql — name the server on preprints with no venue.
--
-- Crossref files a preprint as "posted-content" with the server under
-- "institution", and the resolver only read "container-title", so most stored
-- preprints have no venue and show as a bare year. The resolver now reads the
-- server name (paper_radar/ingest/metadata.py: parse_crossref, preprint_server);
-- this gives existing rows the same, from what the row already holds. The web
-- app labels a paper "Preprint" from its venue (web/src/lib/preprint.ts).
--
-- The host decides first: bioRxiv and medRxiv share their DOI prefixes, so a
-- 10.1101 DOI alone cannot say which. Those rows are left for
-- api/merge_preprints.py, which asks Crossref. A venue someone set by hand
-- (edited_fields) is never touched, and edited_at does not move: this is not a
-- person's edit.

update public.papers p set venue = v.server
  from (
      select id,
             case
                 when url ~* '^https?://([a-z0-9-]+\.)*biorxiv\.org/'          then 'bioRxiv'
                 when url ~* '^https?://([a-z0-9-]+\.)*medrxiv\.org/'          then 'medRxiv'
                 when url ~* '^https?://([a-z0-9-]+\.)*arxiv\.org/'            then 'arXiv'
                 when url ~* '^https?://([a-z0-9-]+\.)*researchsquare\.com/'   then 'Research Square'
                 when url ~* '^https?://([a-z0-9-]+\.)*ssrn\.com/'             then 'SSRN'
                 when url ~* '^https?://([a-z0-9-]+\.)*preprints\.org/'        then 'Preprints.org'
                 when url ~* '^https?://([a-z0-9-]+\.)*osf\.io/'               then 'OSF Preprints'
                 when url ~* '^https?://([a-z0-9-]+\.)*authorea\.com/'         then 'Authorea'
                 when lower(doi) like '10.48550/%' then 'arXiv'
                 when lower(doi) like '10.21203/%' then 'Research Square'
                 when lower(doi) like '10.2139/%'  then 'SSRN'
                 when lower(doi) like '10.20944/%' then 'Preprints.org'
                 when lower(doi) like '10.31219/%' then 'OSF Preprints'
                 when lower(doi) like '10.22541/%' then 'Authorea'
             end as server
        from public.papers
       where nullif(btrim(venue), '') is null
         and not edited_fields ? 'venue'
  ) v
 where p.id = v.id and v.server is not null;
