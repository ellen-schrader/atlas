-- 20260712121000_mood_board_storage.sql — private Storage bucket + policies for
-- mood-board figure images. Split out from 20260712120000_mood_board.sql on
-- purpose (see below).
--
-- Bucket `figures` is PRIVATE: the app never exposes a public URL, it mints
-- short-lived signed URLs. These policies on storage.objects are what actually
-- enforce lab isolation for the image bytes. Object path is `{team_id}/{fig_id}.{ext}`,
-- so the first path segment identifies the owning lab.
--   * SELECT / INSERT: gated by membership in the team named by the first path
--     segment — `is_team_member((storage.foldername(name))[1]::uuid)`.
--   * DELETE: the uploading user only (`owner = auth.uid()`).
--
-- WHY A SEPARATE MIGRATION:
--   storage.objects is owned by `supabase_storage_admin`. On a local stack the
--   migration role is effectively superuser, so `create policy on storage.objects`
--   just works. On some HOSTED Supabase projects the migration role isn't the
--   owner, and `supabase db push` fails here with:
--       ERROR: must be owner of table objects   (SQLSTATE 42501)
--   Because each migration file runs in ONE transaction, keeping these statements
--   with the table DDL would roll the tables back too. Isolated here, a failure
--   on push leaves the mood-board tables intact and only this file unapplied.
--
--   FALLBACK if this file fails on push: create the bucket + the three policies
--   below via the Dashboard → Storage → Policies UI (it runs as the storage
--   admin), using the same expressions, then mark this migration as applied
--   (`supabase migration repair --status applied 20260712121000`). The
--   `public.is_team_member` helper already exists from the base schema.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('figures', 'figures', false, 10485760,
        array['image/png', 'image/jpeg', 'image/webp', 'image/gif'])
on conflict (id) do nothing;

create policy figures_objects_select on storage.objects for select to authenticated
    using (
        bucket_id = 'figures'
        and public.is_team_member(((storage.foldername(name))[1])::uuid)
    );
create policy figures_objects_insert on storage.objects for insert to authenticated
    with check (
        bucket_id = 'figures'
        and public.is_team_member(((storage.foldername(name))[1])::uuid)
    );
create policy figures_objects_delete on storage.objects for delete to authenticated
    using (bucket_id = 'figures' and owner = auth.uid());
