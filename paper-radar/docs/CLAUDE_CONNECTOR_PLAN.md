# Atlas as a Claude connector — plan (rev 2)

Status: **proposal, no code yet**. Rev 2 (2026-10-17), after review against these constraints:

- **Self-funded.** Adding this should cost close to **$0/month**, and the cost should have a
  hard ceiling.
- **Papers only.** The mood board and maps are beta and likely to be removed, so the
  connector covers reading papers and, later, posting them. Nothing else.
- **Several labs use Atlas.** One lab must never see another lab's data. Security comes
  before convenience.

## Is MCP the right approach?

**Yes, for live access, and it's the only real option for claude.ai.** A remote MCP server
("custom connector") is the only way to give Claude's own apps (chat, desktop, mobile,
Cowork, Life Sciences) live access, scoped to the user, to data behind a login. The
alternatives:

| Option | Cost | Security | Verdict |
| --- | --- | --- | --- |
| **Remote MCP connector** (this plan) | ~$0 extra (see Cost) | We control exactly what Claude can do, and every call is logged | **Do it** |
| **"Export for Claude"**: download the lab library as Markdown/BibTeX and add it to a Claude Project | $0, about a day of work | No new attack surface: no tokens, no endpoint | **Worth doing anyway** as the zero-risk option. It's static, though: no live search, no posting, re-export to refresh |
| Skill that calls the Atlas REST API with a pasted token | $0 | Worst: a long-lived token pasted into chat; Claude's code sandbox has restricted network access | No |
| Desktop extension (MCPB) wrapping today's stdio server | $0 | Password/token stored on each laptop; Claude Desktop only | No |

So: build the connector, kept minimal, and optionally ship "Export for Claude" first as a
quick win.

## What it costs

| Item | Monthly | Notes |
| --- | --- | --- |
| Hosting | **$0 extra** | Mounted at `/mcp` on the existing Fly API machine. Papers-only means no Pillow/matplotlib in the image, so there's no memory increase. Works with `auto_stop = "suspend"` once the temporary always-on setting is reverted on 10 Nov: Claude waits far longer than Teams' 5 s, so a sub-second resume is fine. One machine and no autoscaling, so **cost can't run away**: the worst case under abuse is slowness, not a bill. |
| Claude/LLM | **$0** | The server makes no LLM calls; each user's own Claude plan does the thinking. Keep it that way (rule: no `anthropic` calls in `atlas_mcp`). |
| Voyage (semantic search) | ~cents | One short query embedding per semantic search. Capped by the per-user rate limit, plus a **global daily cap**. Above the cap, search falls back to keyword. |
| Supabase OAuth server | $0 expected | Same users, so no extra monthly active users. **Check in M0** that the beta feature isn't a paid add-on on our plan. |
| Domain | $0 | `mcp.labatlas.app` CNAME → Fly cert. |

## The design in one paragraph

Supabase Auth acts as the OAuth 2.1 server, including dynamic client registration. That's
how claude.ai registers itself with a server it hasn't seen before. A consent page on
labatlas.app approves each connection. Claude then calls `https://mcp.labatlas.app/mcp`
with a Supabase user token. The server checks that token and runs a **small, fixed set of
paper tools** as that user, so existing RLS and the per-lab "Claude access" switch decide
what's visible. We build no OAuth broker of our own and pay for no auth service.

```
claude.ai ─ POST /mcp (no token) ─────────────▶ Atlas MCP  ─▶ 401 + metadata
          ─ register + /authorize (PKCE) ─────▶ Supabase Auth ─▶ labatlas.app/oauth/consent
            user logs in, picks lab, Allow ───▶ approveAuthorization
          ◀ access + refresh token ───────────  Supabase Auth
          ─ POST /mcp, Bearer token ──────────▶ Atlas MCP ─▶ Supabase as that user (RLS)
```

## Security model

Security work comes **before** the endpoint goes live, not after. Threats, in order of how
much they worry me:

1. **One lab seeing another lab's data.** This is new now that several labs use Atlas.
   Today's server is one user per process (`lab._session()` is a process-wide
   `lru_cache`). Hosted as-is, **every caller would act as the first user who connected.**
   Fix: identity per request (M1), plus tests that interleave two users from different
   labs and assert neither sees the other's papers, posts, notes or lab names. **CI blocks
   the merge if these fail.**
2. **A connector token used outside the connector.** The OAuth token is an ordinary
   Supabase user token, and Anthropic's servers hold it. Leaked, it would work against
   PostgREST, Storage and our FastAPI routes directly, with the user's full rights,
   including edits and deletes. Fix: make OAuth-issued tokens **able to do only what the
   tools need** (M2):
   - FastAPI `get_user_id` rejects any token carrying an OAuth `client_id` claim. The
     connector has no business on the web API.
   - **Restrictive** RLS policies: when `auth.jwt() ->> 'client_id'` is set, allow `select`
     on the paper tables the tools read, `insert` into `mcp_tool_calls`, and later `insert`
     into posts. Deny everything else, including Storage and membership/ownership changes.
   - Audit `security definer` RPCs the tools call (`search_papers`, `match_papers`,
     `recommend_papers`, …). They bypass RLS, so each must keep its own team-membership
     check, and any that write must refuse OAuth tokens.
   - ✅ M0 confirmed that OAuth tokens carry `client_id`, so no custom hook is needed.
   - Revocation must be immediate: the restrictive policies also require the token's
     `session_id` to still exist (see M0 results).
3. **Consent phishing.** Open client registration means anyone can register a client
   called "Claude" with an attacker's redirect URL and send a lab member an authorize link.
   Fix: the consent page **only approves allowlisted redirect URIs**: Claude's callback
   URLs (claude.ai / claude.com) and `http://localhost:*` for Claude Code. Anything else
   gets an error page and is denied. The page shows the redirect host prominently.
4. **Prompt injection via paper content.** Titles, abstracts and notes come from other
   members and from external sites. Tool output is already marked as untrusted
   (`_untrusted`). Launching **read-only** means injected text has nothing to write with.
   Writing (M6) is preview-by-default, and posting only adds a paper link to the user's
   own lab.
5. **Data leaving Atlas.** Once results are in Claude's context, Atlas can't control them
   (other connectors, chat sharing). That's inherent and acceptable, *because a lab owner
   chooses it*: keep the per-lab `mcp_access` switch, and make its wording say this
   plainly.
6. **Abuse/DoS.** Per-user rate limit, small request/response caps, a global Voyage cap,
   and the single machine as the hard ceiling (see Cost).

Plus: every call goes to `mcp_tool_calls` (already in place). Users can revoke the
connection from Atlas (M4). Only papers tools exist on the hosted server, so a smaller
surface means fewer things to get wrong.

## Tools on the hosted server

Read (launch): `list_labs`, `search_lab_papers`, `list_recent_papers`, `get_paper`,
`similar_papers`, `recommend_reading`, `lab_digest`, `novelty_check`, `draft_related_work`.
None calls an LLM, and none needs Pillow/matplotlib.

Write (M6, later): `post_paper` only.

Not hosted: all mood-board/figure/plot tools (`list_moodboard`, `get_figure_*`,
`get_moodboard_style`, `check_colorblind_safety`, `preview_plot_spec`,
`add_plot_to_moodboard`, …). They stay on the local stdio server until the beta is removed.

## Milestones

### M0 — Spike (½ day, throwaway, local Supabase)
A toy FastMCP `whoami` server, the local Supabase with the OAuth server and dynamic
registration on, a bare consent page, connected with
`claude mcp add --transport http …`. Check:
1. Claude registers itself with Supabase and completes sign-in; refresh works after an hour.
2. **Token claims**: `iss`, `aud`, `sub`, and whether `client_id` (or similar) is present
   (security item 2 depends on it).
3. RLS reads work with that token.
4. Supabase pricing/limits for the OAuth server on our plan; and that grants can be
   listed and revoked.

**Go/no-go.** If Claude can't register itself, fall back to a pre-registered client
entered under claude.ai's "Advanced settings". It's clunkier, but it's still $0 and needs
no broker.

### M1 — Papers-only, multi-user server ✅ (branch `connector-m1`)

What landed:
- `server.py` split into `tools.py` (audit decorator, confirm gate, formatting),
  `papers.py` (`READ_TOOLS`, `WRITE_TOOLS`) and `figures.py` (`FIGURE_TOOLS`). The tools
  are plain functions, and each entry point registers the set it serves. `server.py`
  (stdio) still serves all 18. `atlas_mcp.papers` imports no Pillow, matplotlib or numpy.
- `lab.py`: `act_as(token, user_id)` binds a request's user in a contextvar. With no
  bound user, calls **fail closed** ("Not signed in"). The `.env` user is only used after
  `allow_env_session()`, which only the stdio `main()` calls. `with_refresh` never
  re-signs-in for a hosted request. `ATLAS_TEAM_ID` is ignored for hosted callers. Rate
  limiters are keyed per user.
- Tests: `test_mcp_sessions.py` (offline: fail-closed, contextvar isolation across async
  tasks and threads, refresh, default lab, per-user limits) and
  `test_mcp_isolation_integration.py` (opt-in `ATLAS_INTEGRATION=1`, local Supabase only).
  The integration test runs every read tool for two labs concurrently, and calls the RPCs
  and tables directly with the other lab's id. It was mutation-checked: reintroducing
  "first caller wins" makes it fail.
- **Extras not split** (changed from the plan): splitting them would break every existing
  stdio config (`--extra mcp`), because the stdio server imports the figure tools. M3
  instead adds just the `mcp` SDK to the `api` extra, so the image still gets no
  Pillow/matplotlib.

Code review (high) fixes, same PR:
- Sync tools now run in worker threads (`tools.in_worker_thread`, which carries the
  request's contextvars), so one user's slow call can't stall the others. Tested through
  FastMCP's own call path, and mutation-checked: dropping the context fails closed.
- The env-user switch is a contextvar set by the stdio entry point, not a process-wide
  flag.
- An expired hosted token gives a clean "reconnect Atlas" error instead of a raw 401.
- The rate limiter is shared with the API (`api/ratelimit.py`): the key is required, and
  idle users are evicted past 10k keys.
- The local `config.toml` OAuth switch is reverted until M2/M4 protect it (consent page +
  redirect allowlist + token lockdown). Turn it on together with those.

Carried into M3:
- `act_as` builds a Supabase client (and its connection pools) per request. Reuse one
  pooled client per process and attach the token per request, before going live.
- There's **no CI test workflow** today (only deploy + backup). Adding one (offline tests
  on every PR, roughly free within GitHub's included minutes) is a small separate PR. The
  integration test needs a Supabase stack in CI, so it stays a local pre-merge step for
  now.

Original M1 plan:
- Split `server.py`: `atlas_mcp/papers.py` (paper tools) and `atlas_mcp/figures.py`
  (beta tools). The hosted entry point imports only `papers`, so the API image never
  pulls in Pillow/matplotlib. Split the extras: `mcp` (core) and `mcp-figures`.
- `lab.py`: a `ContextVar` holds the request's `(client, user_id)`. Over HTTP it's set
  per request from the verified token. Over stdio it's set once from `.env`, so today's
  local setup keeps working. Remove the `lru_cache`, and audit for any other
  module-level user state.
- Lab selection without `ATLAS_TEAM_ID`: unchanged `_pick_team` (explicit `team_id` → the
  user's only lab → error listing the labs). Every user is in one lab today (decision 4).
- **Cross-lab isolation tests** (security item 1) run in CI.

### M2 — Lock down the token (before anything is public) ✅ (branch `connector-m2`)

The RPC audit changed the design. 12 `SECURITY DEFINER` functions (`create_team`,
`set_member_role`, `set_mcp_access`, `remove_member`, `regenerate_team_code`, …) bypass
RLS and are callable by any signed-in user, so per-table policies alone would have left
them open. Without the gate, a connector token really did create a lab in testing.

What landed (`20261017150000_connector_lockdown.sql`):
1. **PostgREST pre-request gate, default-deny** (`public.connector_request_guard`, set
   via `pgrst.db_pre_request`). A connector token may only GET the tables in
   `public.connector_readable_tables()` (the paper tools' 9, plus `spelling_variants`,
   which keyword search reads as the caller for UK/US spellings) and POST the 3 search
   RPCs plus the audit-log insert. Every other table,
   RPC (including the definer ones), GraphQL, and anything added later gets a 403.
   It also refuses a token whose session is gone (401), so **revoking takes effect
   immediately** rather than up to an hour later.
2. **Restrictive SELECT policies** (`connector_no_read`) on every other table, so an
   embed (`teams?select=*,team_visits(*)`) can't read past the gate.
   `public.close_to_connectors()` is there for new tables, and a pgTAP coverage test
   fails if one is missed.
3. **Storage:** a restrictive `connector_no_storage` policy on `storage.objects`.
4. **Atlas web API:** `deps.require_token` returns 403 for any token with `client_id`
   (all 26 token endpoints go through it).
5. **MCP:** `lab.with_refresh` turns the gate's refusals into `LabError` with the gate's
   wording ("connection revoked — reconnect").

**Account-takeover finding (Auth API, outside the database).** A real connector token
could `PUT /auth/v1/user` and **change the password**: in testing, the new password
worked and the old one failed. It could also start an email change and edit user
metadata. A custom-access-token hook that changes `aud` does **not** help, because the
Auth API ignores `aud`. The fix is the free Auth setting **"Require current password
when updating"** (`GOTRUE_SECURITY_UPDATE_PASSWORD_REQUIRE_CURRENT_PASSWORD`). It was
verified against GoTrue v2.191: the connector token gets `current_password_required`,
emailed password resets still work (recovery sessions are exempt), and the Settings form
now asks for the current password and offers "Email me a reset link" instead.

What remains at the Auth API, and is acceptable: an email change still needs both
inboxes to confirm (`double_confirm_changes`), so it can't complete from a token alone.
A token can also edit `user_metadata` (the app reads names from `profiles`), sign the
user out globally, and list or revoke OAuth grants. That's a nuisance, not a takeover.

Tests:
- `supabase/tests/connector_lockdown_test.sql` (pgTAP): the gate, revocation, embeds,
  Storage, and the coverage check.
- `tests/test_connector_lockdown_integration.py` (opt-in): a **real** OAuth token through
  real PostgREST, Storage and GraphQL. All read tools still work. 13 kinds of write, RPC
  and read are refused, embeds come back empty, Storage is refused, the web session is
  unaffected, and revocation stops the live token. Mutation-checked: with the gate
  switched off, 14 of 18 tests fail.
- Offline: API refusal tests, and the gate-error translation test.

Code review (high) fixes, same PR:
- **Web sign-out is now local** (`signOut({ scope: "local" })`). Supabase's default
  global sign-out deletes every session, including a connected Claude's (refresh fails
  too, not just the gate). Trade-off: signing out of Atlas on one device no longer signs
  out the others.
- **The reset page** turns `current_password_required` (opened bare while signed in) into
  its existing "use Settings" screen.
- **`config.toml` keeps `secure_password_change = false`.** CLI 2.108 maps it to the old
  24h re-authentication rule, which doesn't stop a fresh connector token and would break
  Settings for older sessions. The real setting is the dashboard toggle below.
- Policies use `(select public.is_connector())`, so it's evaluated once per statement.
- Strict UUID check on `session_id`. `require_access` passes gate refusals through
  cleanly.
- The integration tests' "own data came back" checks now look for paper ids. The lab
  name, which an empty reply also contains, made them vacuous. Mutation-checked: closing
  `spelling_variants` again now fails the spelling search check.

**Production steps, in this order:**
1. Merge (deploys the migration and the Settings form).
2. *Then* switch on Auth → **"Require current password when updating"** in the
   dashboard. Doing it before the web deploy would break the old Settings form.
3. Check that "Secure email change" (double confirm) is on.

Redirect-URI allowlist: moved to M4 (the consent page), where it's enforced.

### M3 — Host it ($0) ✅ (branch `connector-m3`)

What landed:
- **`atlas_mcp/http.py`:** a FastMCP resource server serving only the 9 read tools.
  Each tool is wrapped (`as_caller`) to run as the token's user through `lab.act_as`.
  Settings: `stateless_http`, JSON responses, and DNS-rebinding protection allowing
  only the public host (origins: our own, claude.ai, claude.com; no `Origin` is fine).
- **`SupabaseTokenVerifier`:** checks the JWT locally against Supabase's JWKS (cached
  for an hour): ES256/RS256 only (**never HS256**), issuer, `aud=authenticated`,
  exp/iat/sub required, and **`client_id` required**, so web-session tokens are refused.
  Revocation is enforced by the M2 database gate on every query, so the verifier doesn't
  check sessions itself.
- **Served by the existing API process:** `api/app.py` mounts it as a Starlette `Host`
  route for `MCP_PUBLIC_URL`'s host (set in `fly.toml [env]`), and its lifespan starts
  the MCP session manager. Every other host is the API, unchanged (`POST /mcp` → 404).
- **Pooled database client** (the item carried over from M1): each request gets a
  lightweight `SyncPostgrestClient` over one shared httpx pool. A test pins that tokens
  never leak between callers on the pool.
- **Limits:** 60 tool calls per user per minute. Query embeddings are capped at
  **2000 per UTC day across all users** (`MCP_DAILY_EMBEDDINGS`); past that, semantic
  tools say so and keyword search still works. Inputs are cut to 4000 characters
  before embedding.
- **Image:** the `api` extra gains `mcp` + `pyjwt[crypto]` (lockfile +4 lines). The
  Dockerfile now copies `atlas_mcp`, which `.dockerignore` used to exclude. **Without
  this the API would have crashed at boot**; a local `docker build` + run caught it.
  Inside the image: Pillow and matplotlib aren't loaded, and the process uses ~77 MB.

Tests:
- `tests/test_mcp_http.py` (offline, CI, 17): the verifier (good, web, wrong
  iss/aud/exp/sub, HS256 forgery, bad signature), pool header isolation, the 401
  challenge, metadata, the read-tools-only list, per-call user binding, foreign Host
  refused, the per-user cap, and the embedding budget. Mutation-checked: dropping the
  `client_id` check or the `act_as` binding fails tests.
- `tests/test_mcp_http_integration.py` (opt-in, 5): the **real API process** under
  uvicorn with the connector mounted, the MCP SDK client, and a real OAuth token. It
  covers unauthenticated → 401 + metadata, web token → 401, connector → 9 tools
  answering from its lab, the API host unaffected, and revoke → the next call says so.
- `tests/local_supabase.py`: shared OAuth and local-stack helpers for the integration
  tests.

Code review (high) fixes, same PR:
- **Own thread pools.** Tools: 8 threads (`tools.TOOL_THREADS`). Key-set fetches: 2.
  Before, they shared anyio's default pool with FastAPI's sync endpoints and the Teams
  webhook, so a busy or stuck connector could have starved the API.
- **No refetch amplification.** A token naming an unknown key id refetches Supabase's
  JWKS at most once per 5 minutes; otherwise each junk token was an outbound fetch.
  Key fetches time out after 5 s.
- **30 s clock leeway** on token times, for a machine just resumed from suspend.
- **Embedding allowance.** A failed call (Voyage down, no key) is refunded; an empty
  query is refused before spending.
- **Misconfiguration.** Missing Supabase settings now say so, instead of looking like
  an expired sign-in.
- **`mcp>=1.28`** in the `api` extra (the version tested).
- **Wiring.** The connector is now an outermost ASGI middleware (`ConnectorHost`), so
  its requests skip the API's CORS (web-app origins only). It has its own policy
  (claude.ai, claude.com), and each lifespan builds a fresh server, so the app can
  start more than once (tests). The dead `build_app` is gone.
- Tests: 27 offline (mutation-checked: the thread pool and the refetch throttle); the
  production image was rebuilt and re-probed.

**Production steps (yours; nothing goes live until M4):**
1. Merge. The deploy mounts the connector on `mcp.labatlas.app`, which nothing can
   reach yet.
2. DNS: add a **CNAME** `mcp` → `paper-radar-api.fly.dev` at your DNS provider.
3. `fly certs add mcp.labatlas.app` (from `paper-radar/`), then wait for the
   certificate. Fly includes a handful of certificates free; check `fly certs list`.
4. Check: `curl -i -X POST https://mcp.labatlas.app/mcp` → 401 with a
   `resource_metadata` link.
5. **Don't** turn on Supabase's OAuth server in production yet. That happens with M4,
   once the consent page and its redirect allowlist exist.

### M4 — Consent page + Connect page (web)
- `/oauth/consent`: log in if needed (existing `?next=` flow) → redirect-URI allowlist
  check → "**Claude** will be able to search and read papers in <your lab>" → if the lab's
  Claude access is off: owners can switch it on
  here, members see "ask your lab owner" with Allow disabled → Allow / Deny.
- `/connect`: lead with "Copy connector URL" and short steps for the Claude app and
  Claude Code. Move the local stdio setup under "Advanced". Keep "Recent Claude activity".
  Add **"Connected apps → Revoke"**.

**This is where chat works:** paste the URL into claude.ai → Settings → Connectors → Add
custom connector, sign in, ask about your lab's papers. The same URL works in the desktop
and mobile apps, Cowork and Claude Code.

### M5 — Make it work well in chat (½ day)
Tool annotations (`readOnlyHint`, `title`) so claude.ai's permission prompts make sense.
A short server `instructions` block: what Atlas is, always link papers to their Atlas
page. Check that the biggest outputs (`lab_digest`, `draft_related_work`) fit. Optionally
add two or three MCP prompts ("This week in my lab", "Is this idea new?").

### M6 — Writing (later, separate decision)
`post_paper` on the hosted server: preview by default, `confirm=true` to post. Note that
the hosted server **can't** show the in-app confirmation popup the stdio server uses
(stateless HTTP can't send it), so the gate is the preview step plus Claude's own "allow
this tool?" prompt. Many users set that to "always allow". Posting needs its own RLS
allowance (M2) and a tighter rate limit.

## Distribution

1. **Connector URL** (after M4): any paid Claude user can add it. For Claude Team/Enterprise
   organisations (an institute), an admin can add it once for everyone.
2. **Root `.mcp.json`**: switch to the remote URL; keep stdio documented for development.
3. **Anthropic Connectors Directory**: now that several labs use Atlas, this becomes
   worthwhile, but only once it's stable. It needs a privacy policy, terms, a support
   contact and a reviewer test account. Free, but it takes time and review.

## Size

| Milestone | Size |
| --- | --- |
| M0 spike | ½ day |
| M1 papers-only, multi-user | 1–2 days |
| M2 token lockdown | 1 day |
| M3 hosting | 1 day |
| M4 consent + Connect | 1–2 days |
| M5 chat polish | ½ day |
| M6 writing | later |

Separate PRs for M1–M4. Nothing merges without your go-ahead. Optional and independent:
"Export for Claude" (about 1 day) as a zero-risk option people can use today.

## M0 results (2026-10-17): go

Spike: a toy FastMCP resource server + bare consent page against local Supabase
(GoTrue v2.191) with the OAuth server on, driven headlessly by the MCP SDK's own OAuth
client. Two throwaway labs, one user each. Code in the session scratchpad, not committed.

| Question | Result |
| --- | --- |
| Full flow (discovery → DCR → `/authorize` PKCE → consent → code → token → tool call) | ✅ Works with no changes. The SDK's `AuthSettings` publishes the right metadata and 401 challenge. |
| Consent API | ✅ `GET /auth/v1/oauth/authorizations/{id}` (client name, redirect URI, scopes, user) and `POST …/{id}/consent {"action":"approve"\|"deny"}` → `redirect_url`, both with the user's own session token. |
| Token claims | ✅ `client_id` present, plus `amr[0].method = "oauth_provider/authorization_code"`, `session_id`, `aud = "authenticated"`, `iss = <project>/auth/v1`. **Connector tokens can be told apart from web logins.** Supabase's docs recommend exactly this (`auth.jwt() ->> 'client_id'`) in RLS. |
| Verification | ✅ Signed with **ES256**, locally and **in prod** (prod JWKS already serves an ES256 key). Local JWKS verification works: no network call per request, no migration needed. |
| RLS | ✅ User A's token sees Lab A's 2 posts and **none** of Lab B's. |
| Refresh | ✅ `POST /auth/v1/oauth/token grant_type=refresh_token` returns a new access + refresh token. |
| Cost | ✅ Supabase: "no separate charge, available on all plans". OAuth users count as monthly active users, but they're the same people. Still **beta**. |
| ⚠️ Leaked token | A connector token **deleted a lab post directly via PostgREST**, and `/auth/v1/user` (which our FastAPI uses) accepts it. Confirms M2 is required before go-live. |
| ⚠️ Open registration | DCR accepted a client named **"Claude"** with redirect `https://evil.example/cb`. Confirms the consent-page redirect allowlist is required. |
| ⚠️ Revocation | `DELETE /auth/v1/user/oauth/grants?client_id=…` kills refresh and the session immediately, but the **already-issued access token keeps working against PostgREST until it expires (≤1 h)**. Fix (M2): revoke deletes the `auth.sessions` row, so a restrictive RLS check "OAuth token ⇒ its `session_id` still exists" (via a small `security definer` helper, since `authenticated` can't read `auth`) makes revocation immediate. The MCP verifier calls the same helper, with a short cache. |
| Grants listing | ✅ `GET /auth/v1/user/oauth/grants` lists connected clients (for M4's "Connected apps → Revoke"). |

Not yet tested: the real claude.ai client. It can't reach localhost, so that happens on
the first deploy (M3). DCR with claude.ai's callback URL is accepted. Claude Code can be
tested locally against M1/M2 with `claude mcp add --transport http`.

Local config change kept for M1+: `supabase/config.toml` `[auth.oauth_server]
enabled = true, allow_dynamic_registration = true`. (`site_url` is `127.0.0.1:3000`
locally; point `authorization_url_path` at the Vite consent route when M4 lands.)

## Decisions (2026-10-17)

1. **Connector only.** No "Export for Claude": there's no direct use case for it.
2. **`mcp.labatlas.app`.** This is a subdomain of the domain we already own, so nothing new
   to register: one CNAME record at the DNS provider → `paper-radar-api.fly.dev`, plus
   `fly certs add mcp.labatlas.app` (Fly issues the TLS cert).
3. **Read-only launch.** Reading papers from the database first; `post_paper` waits for M6.
4. **No lab picker, no stored default.** Every user is in exactly one lab today, so the
   existing "only lab" rule in `_pick_team` is enough. If multi-lab membership arrives
   later, the existing error (which lists the labs and asks for `team_id`) still behaves
   safely; add a stored default then.
