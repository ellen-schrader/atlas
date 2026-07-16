# Atlas ↔ Microsoft Teams channel integration — plan

**Constraint:** no Microsoft Graph access (no Azure AD app registration, no Graph API tokens).
**Deployment fact:** the Atlas FastAPI service is deployed on fly.io → it has a public HTTPS URL, so inbound webhooks from Teams are viable. (No fly.toml in this repo — deployment is managed out-of-band; new secrets go in via `fly secrets set`.)

Everything Microsoft-side uses features a regular Teams user / team owner can set up: **Outgoing Webhooks** (Teams-native, still supported — distinct from the retired O365/incoming connectors) and **Power Automate "Workflows"** with standard connectors only. Each Teams channel maps to one Atlas team/lab.

---

## Direction 1 — Atlas → Teams (post papers to the channel)

### Microsoft side (one-time, per channel, no code)
Create a Workflow with the trigger **"When a Teams webhook request is received"** followed by **"Post card in a chat or channel"**. Saving it yields a unique webhook URL. Atlas POSTs JSON to that URL — no auth setup, no Graph. (The old O365 incoming webhooks are disabled May 18–22, 2026; this is the sanctioned replacement.)

### Atlas side
1. **New module `paper-radar/api/teams_integration.py`**
   - `build_paper_card(paper, post) -> dict`: an Adaptive Card with title (linked), authors, venue/year, who posted it, and their note.
   - `post_to_teams(webhook_url, card)`: POST `{"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}` with a short timeout; log-and-swallow failures (posting to Teams must never break the in-app post).
2. **Hook into `create_post()`** (`api/app.py:297`): after the `paper_posts` insert succeeds, add a `BackgroundTasks` job (same pattern as `_embed_and_store` at `api/app.py:314`) that looks up the team's webhook URL and posts the card.
   - **Loop guard:** only fire for posts with `source='web'`. Posts ingested *from* Teams (`source='teams'`) are never echoed back.
3. **Webhook URL storage:** v1 = `TEAMS_WEBHOOK_URLS` in `api/config.py` / fly secrets as a `{team_slug: url}` JSON map. v2 = `team_integrations` table + LabManagement UI field.

---

## Direction 2 — Teams → Atlas (automatic ingestion, no manual exports)

Two complementary mechanisms, both license-free:

### 2a. Primary: Teams Outgoing Webhook → `POST /integrations/teams/outgoing` (real-time, interactive)

**Microsoft side:** a team owner registers an Outgoing Webhook named `Atlas` (Team → Manage team → Apps → Create an outgoing webhook) pointing at the fly.io URL. Teams displays a **base64 security token once** at creation — that's the HMAC secret. The webhook is team-scoped and fires in any channel of that team when someone @mentions `Atlas`.

**Flow:** someone writes `@Atlas https://arxiv.org/abs/…` → Teams POSTs the message JSON to Atlas, signed `Authorization: HMAC <base64 sig>` → Atlas replies inline.

**Atlas side — new endpoint in `api/app.py` + logic in `teams_integration.py`:**
1. **Verify HMAC-SHA256** over the *raw* request body using the base64-decoded token; constant-time compare. Secrets in `ApiSettings` as `TEAMS_OUTGOING_SECRETS` = `{team_slug: base64_token}` — the matching secret also identifies which Atlas team to post into.
2. **Parse:** strip the `@Atlas` mention from the message text/HTML, extract URLs, unwrap `safelinks.protection.outlook.com` redirects, then the existing pipeline: `_clean_url` / `_normalize_key` (`paper_radar/ingest/pdf_extract.py`), `_SKIP_HOSTS` filter.
3. **Reply within the 5-second window** (outgoing webhooks allow exactly one synchronous reply, nothing later):
   - Try `fetch_metadata()` with a ~3.5 s budget. Resolved in time → upsert + insert `paper_posts` (`source='teams'`, `posted_by_label` = message `from.name`) → reply **"✓ Added *{title}* to {lab}"**.
   - Budget exceeded → reply **"⏳ Adding — it'll appear in Atlas shortly"** and finish resolve/upsert/embed/enrich in `BackgroundTasks`.
   - No URL found / skip-host only → reply with a gentle usage hint.
4. Dedup is free: `url_norm`/`doi` uniqueness on `papers`, `unique(paper_id, team_id)` on `paper_posts` → duplicate mention replies "Already in the lab (added by …)".

### 2b. Safety net: scheduled sweep for links shared *without* @Atlas

Power Automate **scheduled flow** (daily): Teams connector **"Get messages"** for the channel (standard action) → write one digest JSON to OneDrive `AtlasTeamsInbox/<channel>/<date>.json`. Locally synced; a CLI `api/import_teams_messages.py` — modeled on the existing `api/import_teams_pdfs.py` — parses each digest through the *same* extraction/upsert code as 2a (shared library function), tracks processed message IDs, runs via `launchd`. Papers already ingested via 2a are skipped by dedup.

*(If the sweep ever needs to bypass OneDrive: the premium Power Automate HTTP action can POST digests straight to a shared-secret endpoint — same importer code, different transport.)*

### Considered and rejected
- **Per-message flow → OneDrive** — superseded: 2a covers real-time, 2b covers completeness with far fewer files.
- **Email relay** — most moving parts; only relevant if OneDrive sync were unavailable.
- **Zapier/Make** — their Teams triggers need tenant admin consent for their Graph app.
- **claude.ai M365-connector bridge** — interactive auth, not dependable unattended; fine as a one-off experiment.

---

## Database migration (one, small)
- Extend the `paper_posts.source` CHECK (defined at `supabase/migrations/…init.sql:83`; new migration alters it) to allow `'teams'`.
- (Later) `team_integrations (team_id, kind, webhook_url, enabled)` with admin-only RLS.

## Milestones
1. **M1 — outbound:** migration + `teams_integration.py` (card builder + poster) + `create_post()` hook + env config; webhook Workflow on a test channel.
2. **M2 — real-time inbound:** `/integrations/teams/outgoing` endpoint (HMAC verify, parse, 5-s reply strategy); register the `Atlas` outgoing webhook; end-to-end test incl. loop-guard and dedup replies.
3. **M3 — sweep:** scheduled "Get messages" flow → OneDrive digest; `import_teams_messages.py` + `launchd` job.
4. **M4 — polish:** `team_integrations` table + LabManagement UI; setup docs for both Microsoft-side pieces.

## Risks / notes
- Outgoing-webhook replies are one-shot and synchronous — hence the 3.5 s resolve budget + fallback wording in 2a.
- The HMAC token is shown only once at webhook creation; rotating it means recreating the webhook and updating the fly secret.
- Outgoing webhook is team-scoped: mentions in *any* channel of the team land in the mapped lab. If per-channel routing is ever needed, branch on the payload's channel id.
- Workflows/flows are personally owned — co-own with a colleague once load-bearing.
- The webhook Workflow posts as "<owner> via Workflows", not "Atlas"; cosmetic.
- 2b assumes the Teams tenant's OneDrive is synced on the machine running the importer; confirm before M3.
