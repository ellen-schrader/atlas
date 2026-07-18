# Teams → Atlas inbound ingestion (M2) — implementation plan

**Constraint:** no Microsoft Graph. The Atlas API is public on fly, so Teams can call it.

## Scope, and my recommendation

| What | Feasible without Graph? | Recommendation |
|------|------------------------|----------------|
| **Papers** | Yes — cleanly, real-time | **Build now (Phase 1)** |
| **Comments** (thread replies) | Only via a polling sweep + a schema change | Design now, **build later** — needs one product decision |
| **Reactions** | Not really | **Skip** unless Graph becomes available |

The codebase makes the split sharp: `paper_posts` already supports non-Atlas authorship (`posted_by` nullable + `posted_by_label` free text, and `source='teams'` is already reserved), so papers drop straight in. But `comments.author_id` and `reactions.user_id` are **NOT NULL foreign keys to real profiles with no label column** — a Teams commenter/reactor who has no Atlas account can't be represented without a schema change.

---

## Phase 1 — Papers inbound (build now)

**Transport: a Teams _Outgoing Webhook_** (distinct from the Workflows _incoming_ webhook you set up for the outbound direction). Someone writes `@Atlas <paper link>` in the channel; Teams POSTs the message to Atlas, HMAC-signed; Atlas imports the paper and replies inline.

### Teams side (one-time, per team, owner — no Graph, no admin)
1. Team → **Manage team → Apps → Create an outgoing webhook**, name it "Atlas", callback URL = `https://<your-api-host>/integrations/teams/inbound/<team-uuid>` (the same API host your web app already calls).
2. Teams shows an **HMAC security token once** — paste it into Atlas → **Settings → Post to Teams** (new field).
3. Then `@Atlas https://arxiv.org/abs/…` in any channel of that team adds the paper.

### Atlas side
1. **Migration:** add `inbound_secret text` (nullable) to `team_integrations`. Owner-only RLS already covers the table; the secret is never returned to the browser (write-only, like the webhook URL).
2. **Settings UI:** a write-only field to paste the outgoing-webhook token, with the 3-step instructions inline (mirrors the existing "Post to Teams" panel).
3. **New endpoint `POST /integrations/teams/inbound/{team_id}`** — *public* (no JWT; the HMAC is the only gate):
   - Read the **raw** body. Look up `inbound_secret` for `team_id` (service role); none → 404.
   - Verify `HMAC-SHA256(base64-decoded token, raw body)` against the `Authorization: HMAC <sig>` header, **constant-time**; reject unsigned/mismatched with 401.
   - Parse the message: strip the `@Atlas` mention, extract URLs from the text (new `extract_urls_from_text` regex helper in `ingest/urls.py` — the only genuinely new logic), filter the `_SKIP_HOSTS` denylist.
   - Resolve the first paper URL with a **~3.5 s budget** (`fetch_metadata`, already SSRF-guarded via `url_guard`), then `_upsert_paper` + insert `paper_posts` with `source='teams'`, `posted_by=NULL`, `posted_by_label=<Teams sender name>`.
   - **Reply** (one synchronous JSON response, <5 s): `✓ Added "<title>" to the lab` / `⏳ Adding — it'll appear shortly` (finish resolve+embed in the background) / `Already in the lab` / a short usage hint if no URL was found.
4. **Loop guard (already in place):** `source='teams'` posts never trigger the outbound mirror (that fires only on `source='web'`), and `unique(paper_id, team_id)` dedups re-adds — so a paper Atlas itself mirrored out can't bounce back in.

### Security (this endpoint is public — the sensitive part)
- **HMAC is the sole authentication.** Constant-time compare; reject anything unsigned or mismatched. The per-team secret is selected by the `team_id` in the URL path (not a secret itself — the HMAC is the gate).
- The server does **not** fetch the webhook; Teams calls us. The only outbound fetch is `fetch_metadata` on the paper URL, which already runs through the SSRF guard.
- No JWT means no per-user identity — every import is attributed to `posted_by_label` (the Teams sender's display name), never to an Atlas account it can't verify.

### Tests
HMAC verify (valid / invalid / missing / wrong-team), URL-from-text extraction (incl. safelinks unwrap + skip-hosts), dedup "already in the lab", the 3.5 s budget fallback, and unconfigured/disabled team.

---

## Phase 2 — Comments (designed; one decision needed before building)

**Blocker:** `comments.author_id` is a NOT NULL FK to `profiles`, no label column. To import a reply from a Teams user with no Atlas account, pick one:

- **Option A — schema change:** make `author_id` nullable + add `author_label text`; update RLS and the web UI to render "Name (via Teams)". Preserves per-person attribution. More work (migration + RLS + frontend).
- **Option B — synthetic author:** seed one "Teams import" profile and attribute every imported comment to it. No schema change, but loses who-said-what.

**Transport:** comments can't arrive by @mention, so this needs a **scheduled Power Automate sweep** ("Get messages" + the standard "List replies to a message" action) delivered to a new endpoint, then an importer. Caveats: polling (not real-time), the connector's "Get messages" returns only the latest ~50 messages, and each reply must be matched to the right paper (embed `paper_id` in the Atlas-posted card and match replies under that message).

Recommendation: decide A vs B first; I'd lean A if the "who commented" matters, B if you just want the discussion text mirrored.

### Build reply-tag ingestion together with comments

**Requested and shelved (2026-07-18):** adding a paper by replying to a message that contains it and tagging `@Atlas` in the reply (the reply itself has no link) — e.g. someone posts a paper, a labmate replies "@Atlas" to file it.

Why it's shelved and coupled to comments: the real-time Outgoing Webhook payload carries only the reply's own text plus the thread id, **not the parent message's content**, so Atlas can't see the paper link in the message being replied to. Reading the parent needs either Microsoft Graph (unavailable) or the **same scheduled sweep** above — a sweep already walks each thread's root message and its replies, so it can resolve a bare `@Atlas` reply against the root's link at no extra transport cost.

So when the sweep gets built for comments, do reply-tag ingestion in the same pass: for each thread, if a reply mentions Atlas and has no link of its own, import the root message's paper. Until then, `@Atlas <link>` (or a bare DOI) in a message or reply is the supported path.

---

## Reactions — not recommended without Graph

No channel trigger fires on a reaction, so they're only reachable by polling message details; the per-user "who reacted" list is unreliable through the standard connector; and `reactions.user_id` has the same NOT-NULL-real-profile blocker. Low reliability, high effort — skip unless Graph access appears.
