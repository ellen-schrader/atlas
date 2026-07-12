# web/ — Atlas frontend

Vite + React + TypeScript SPA. Talks to Supabase directly (auth + data, secured
by RLS); the Python service (`../api`, later) handles ingest/ML. Styling follows
the IDE-minimal design language in `../docs/MIGRATION_PLAN.md` §4.

## Run

```bash
# 1. This scaffold added a migration (team RPCs) — push it to your project:
cd .. && supabase db push        # applies supabase/migrations/*_team_rpcs.sql

# 2. Point the app at your project:
cd web
cp .env.example .env.local
#   set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY (Supabase → Settings → API)

# 3. Install + run:
npm install
npm run dev                      # http://localhost:5173
```

`npm run build` typechecks (`tsc --noEmit`) and builds; `npm run typecheck` is
typecheck-only.

## Auth note

Supabase requires email confirmation by default, so a new signup won't get a
session until the emailed link is clicked. For faster local iteration you can
turn confirmation off under **Authentication → Providers → Email** in the
dashboard (re-enable before real use).

## What's here (phase 3)

- **Auth** — email/password sign up + log in (`routes/Login.tsx`).
- **Onboarding** — create a lab or join one by code (`routes/Onboarding.tsx`),
  backed by the `create_team` / `join_team_by_slug` RPCs.
- **App shell** — sidebar (account, lab, theme toggle, log out), the lab join
  code, and the editable **USER.md** profile (`routes/AppShell.tsx`).
- **Theme** — light/dark tokens + Lucide icons (`index.css`, `components/`).

Papers (ingest, search, feed, comments, reactions, dashboard) come next.

## Layout

```
src/
  main.tsx            providers (React Query, Router, Theme)
  App.tsx             session + membership routing guard
  lib/                supabase client, types, utils
  hooks/              useSession, useMemberships, useProfile
  components/ ui/      Button, Input, Textarea, Label, Card + Avatar, Brand, Theme*
  routes/             Login, Onboarding, AppShell
```
