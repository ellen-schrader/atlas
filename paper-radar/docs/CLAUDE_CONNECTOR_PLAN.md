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

Carried into M3:
- FastMCP calls sync tools **on the event loop**, so one slow Supabase call stalls
  every user. The hosted server should register the read tools wrapped to run in a
  worker thread (`anyio.to_thread.run_sync`, which carries contextvars), and the session
  tests already cover the threaded case.
- `act_as` builds a Supabase client per request. That's fine at our volume; revisit if it
  ever shows up in latency.
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

### M2 — Lock down the token (before anything is public)
Everything under security items 2–3: FastAPI rejects OAuth tokens; restrictive RLS and
Storage policies for OAuth tokens; RPC audit; redirect-URI allowlist (enforced in M4's
consent page, tested here). Migration tests: with an OAuth-style token, a `delete` on
papers, a membership change and a Storage read are all refused.

### M3 — Host it ($0)
- `FastMCP(token_verifier=SupabaseTokenVerifier(), auth=AuthSettings(...))`, mounted at
  `/mcp` in the existing FastAPI app. `stateless_http=True` (needed because the machine
  suspends).
- The verifier checks the JWT **locally against Supabase's JWKS** (cached, no network
  call per request): ES256 only, issuer, expiry, `client_id` present, and session alive
  (cached for about a minute). Prod already signs with ES256 (M0).
- Per-user rate limit, size caps, global Voyage cap with keyword fallback.
- `mcp.labatlas.app` CNAME. Enable the OAuth server on the prod project via the
  dashboard. Deploy on merge to main as usual, never from a laptop.

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
