# supabase/

Database schema, Row-Level Security, and isolation tests for the hosted app.
See `../docs/MIGRATION_PLAN.md` (§5 data model, §7 security).

```
migrations/
  20260711163826_init.sql   tables, indexes, profile-bootstrap + mention→TBR triggers
  20260711163827_rls.sql    membership helpers, grants, RLS enable + policies
tests/
  rls_isolation_test.sql    pgTAP: proves labs can't see each other's data
```

## Status

**Live** — all migrations are applied to the hosted project
(`eegjxioiidymmiizflkh`, see `../docs/DEPLOYMENT_PLAN.md` for the full
deployment state). New migrations land via `supabase db push` — run in CI on
merge to main (`.github/workflows/deploy.yml`), or manually as below.

## Apply to the hosted project (no Docker needed)

```bash
# from paper-radar/
supabase login                       # opens a browser once
supabase link --project-ref <ref>    # <ref> is in your project URL / dashboard
supabase db push                     # applies migrations/ to the hosted DB
```

## Run the isolation tests

`supabase test db` runs pgTAP against a *local* shadow database (needs Docker).
The test is **self-contained** — it seeds `auth.users` and switches the auth
context with plain `set role` + JWT claims, so it needs nothing beyond pgTAP
(bundled in the Supabase image).

```bash
supabase test db      # runs supabase/tests/*.sql; expect 10 passing assertions
```

## Key invariants the tests lock in

- A lab member sees **only** papers their lab posted (via `paper_posts`), and
  **zero** rows from any other lab (posts, comments).
- An `@`-mention **auto-adds** the paper to the mentioned user's to-be-read
  list, but **never overwrites** a `reading`/`read` status.

## Notes

- `embedding` / `profile_vec` are `vector(1024)` placeholders — swap the
  dimension when the embedding model is chosen (plan §13.1). They're nullable,
  so this is a cheap `ALTER` later.
- Canonical writes to `papers` / `embedding` / `trends` are **service_role only**
  (the Python worker); all user traffic is bound by RLS.
