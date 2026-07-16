---
name: run-atlas
description: Launch the Atlas app (paper-radar) locally and drive it as a signed-in user — local Supabase + FastAPI + Vite, with a seeded lab. Use when asked to run, start, screenshot, or manually verify the Atlas web app, or to check a change in the real UI rather than in tests.
---

# Running Atlas locally

Atlas is **three processes**, and the web app is useless without the other two:

| Process | Port | Without it |
|---|---|---|
| Supabase (Docker) | 54321 / 54322 / 54323 | App shows "Supabase isn't configured" and never renders |
| FastAPI (`api/app.py`) | **8010** (see gotcha #1) | Recommendations, `/overview` (Map), semantic search all fail |
| Vite (`web/`) | 5173 | — |

You also need **a user and a seeded lab**. A fresh Supabase has an empty
`auth.users`, so there is nothing to log in as and every screen is an empty state.

---

## Gotchas — read these first, they cost real time

1. **Port 8000 is usually already taken.** A `uvicorn` from the user's *main*
   checkout (`~/…/OneDrive/…/papers/paper-radar`) is often already running on
   `:8000`, pointed at a **different Supabase**. It answers `/health` with a 200,
   so it looks fine — but it rejects your local tokens with
   `401 {"detail":"Invalid or expired token"}` and the UI just says
   *"Recommendations are unavailable right now."*
   **Run the API on `:8010`** and set `VITE_API_URL` to match. Do **not** kill the
   user's process.

2. **`fastapi` is not in the default venv.** `uv run uvicorn …` fails with
   `ModuleNotFoundError: No module named 'fastapi'` — and uvicorn dies *quietly*
   while something else still answers on the port. Use
   `uv run --extra api uvicorn …`.

3. **`psql` isn't installed on the host.** Seed through the Supabase container:
   `docker exec -i supabase_db_paper-radar psql -U postgres -d postgres`.

4. **No `VOYAGE_API_KEY` → no embeddings.** That's *fine and often desirable*:
   recommendations fall back to recency and return `cold_start: true`, which is
   exactly the new-lab state you usually want to inspect. But **Map/Overview will
   be empty** and semantic search is off. Don't chase it as a bug.

5. Both env files (`api/.env`, `web/.env.local`) are **gitignored**. Safe to write;
   delete them when done if you want the tree pristine.

---

## Launch

All paths relative to `paper-radar/`.

### 1. Supabase

```bash
supabase start          # needs Docker running; ~1-2 min first time, applies all migrations
supabase status         # keys are stable across restarts (they're the standard demo keys)
```

### 2. Env files

```bash
cat > api/.env <<'EOF'
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_ANON_KEY=sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU
EOF

cat > web/.env.local <<'EOF'
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_ANON_KEY=sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH
VITE_API_URL=http://127.0.0.1:8010
EOF
```

### 3. User + seeded lab

Create a **confirmed** user (`email_confirm: true` — otherwise login fails):

```bash
SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU
curl -s -X POST http://127.0.0.1:54321/auth/v1/admin/users \
  -H "apikey: $SERVICE_KEY" -H "Authorization: Bearer $SERVICE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"ellen@tme-lab.org","password":"atlas-local-dev","email_confirm":true,
       "user_metadata":{"display_name":"Ellen"}}'
```

Take the returned `id` and seed the lab. `seed.sql` in this skill directory does
the rest (profile → team → membership → papers → posts → reactions):

```bash
uid=<the id from above>
sed "s/__UID__/$uid/g" .claude/skills/run-atlas/seed.sql > /tmp/seed.sql
docker cp /tmp/seed.sql supabase_db_paper-radar:/tmp/seed.sql
docker exec -i supabase_db_paper-radar psql -U postgres -d postgres -v ON_ERROR_STOP=1 -f /tmp/seed.sql
```

Login: **`ellen@tme-lab.org` / `atlas-local-dev`**

### 4. The two servers

```bash
uv run --extra api uvicorn api.app:app --port 8010    # background
cd web && npm install && npm run dev                   # background → http://localhost:5173
```

Smoke-test before touching the browser:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8010/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173          # 200 — use localhost, not 127.0.0.1
```

---

## Drive it

Launching proves nothing. Log in and reach the screen you changed.
Playwright is not a dependency — install it into `web/` and remove it after
(**revert `package.json` + `package-lock.json` when done**).

```bash
cd web && npm i -D playwright && npx playwright install chromium
```

```js
// web/drive.mjs — run with `node drive.mjs`, then delete it
import { chromium } from 'playwright';
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 950 } });
p.on('pageerror', e => console.log('PAGEERROR:', e.message));
p.on('response', r => { if (r.url().includes('8010') && !r.ok()) console.log('API', r.status(), r.url()); });

await p.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
await p.fill('#email', 'ellen@tme-lab.org');
await p.fill('#password', 'atlas-local-dev');
await p.getByRole('button', { name: 'Log in', exact: true }).last().click();
await p.waitForTimeout(4000);                       // auth + profile + first fetches

await p.screenshot({ path: '/tmp/home.png', fullPage: true });
console.log(await p.innerText('body'));

// navigate by nav label: Home | Papers | Reading list | Your lab's look | Map
await p.getByRole('link', { name: /Papers/i }).first().click();
await p.waitForTimeout(2000);
await b.close();
```

**Look at the screenshot.** A blank frame means it never rendered.

Selector notes: login inputs are `#email` / `#password`; the submit button and the
mode toggle are both named "Log in", so use `.last()`. Reactions/bookmarks live in
the **paper detail modal** — click a card first.

---

## Verifying the API directly

```bash
TOKEN=$(curl -s -X POST "http://127.0.0.1:54321/auth/v1/token?grant_type=password" \
  -H "apikey: sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH" -H "Content-Type: application/json" \
  -d '{"email":"ellen@tme-lab.org","password":"atlas-local-dev"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -w '\nHTTP %{http_code}\n' \
  "http://127.0.0.1:8010/recommendations?team_id=11111111-1111-1111-1111-111111111111&mode=discover&limit=6" \
  -H "Authorization: Bearer $TOKEN"
```

**Always print the status code.** An error body is `{"detail": "..."}` — if you
`.get('cold_start')` on it you get `None` and misread a 401 as "no results".

---

## Teardown

```bash
pkill -f "uvicorn api.app:app --port 8010"
pkill -f vite
rm -f api/.env web/.env.local
cd web && git checkout -- package.json package-lock.json   # if Playwright was installed
supabase stop                                              # optional; keeps data for next time
```
