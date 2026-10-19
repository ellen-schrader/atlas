-- 20261019190500_trial_sources_storage.sql — the private bucket for the PDFs
-- (and full-text XML) behind a lab's trials. Its own migration for the reason
-- 20260712121000_mood_board_storage.sql gives: on some hosted projects the
-- migration role can't create policies on storage.objects, and this must not
-- roll the tables in 20261019190000 back with it. Same fallback if push fails
-- here: create the bucket and policies in the Dashboard, then
-- `supabase migration repair --status applied 20261019190500`.
--
-- Path: `{team_id}/{trial_id}/{file}`. The first segment names the lab, and
-- every policy asks has_feature for it, so a lab without the switch (and
-- every other lab) can't read a byte. Never public: the app signs short URLs.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('trial-sources', 'trial-sources', false, 25165824,  -- 24 MB: base64 in a 32 MB request
        array['application/pdf', 'application/xml'])
on conflict (id) do nothing;

create policy trial_sources_objects_select on storage.objects for select to authenticated
    using (
        bucket_id = 'trial-sources'
        and public.has_feature(((storage.foldername(name))[1])::uuid, 'clinical_trials')
    );
-- Members upload PDFs only; XML comes from Europe PMC via the service role.
create policy trial_sources_objects_insert on storage.objects for insert to authenticated
    with check (
        bucket_id = 'trial-sources'
        and public.has_feature(((storage.foldername(name))[1])::uuid, 'clinical_trials')
        and lower(storage.extension(name)) = 'pdf'
    );
create policy trial_sources_objects_delete on storage.objects for delete to authenticated
    using (
        bucket_id = 'trial-sources'
        and public.has_feature(((storage.foldername(name))[1])::uuid, 'clinical_trials')
    );
