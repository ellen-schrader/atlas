# Claude integration plan — lab papers over MCP

Goal: let **Claude** search the lab's paper database and refer to specific papers,
so a researcher working in **Claude Code** (and **Claude for Life Sciences**, at the
hackathon) can ask "what has our lab posted on myeloid cells?" and get real,
citable answers from Atlas.

The bridge is a single **MCP (Model Context Protocol) server**. Build it once; every
Claude surface that speaks MCP consumes the same server. We are not building two
integrations.

## Priorities at a glance

| Phase | What | Needs hosting? | Hackathon-critical |
|-------|------|----------------|--------------------|
| **P1** | Local **stdio** MCP server, read-only tools, in Claude Code | No | ✅ yes |
| **P2** | Lab-scoped auth (token via env) | No | ✅ yes |
| **P3** | Write tool (`post_paper`) + citation formatting | No | ➖ nice-to-have |
| **P4** | Remote MCP (HTTP + OAuth) for claude.ai custom connectors | Yes | ➖ fast-follow |
| **P5** | Host the web app so deep links are clickable for humans | Yes | ➖ later |

**You do not need to deploy the web app first.** P1–P3 run entirely on a laptop
against the existing (local or Cloud) Supabase. Hosting only becomes necessary at P4,
and only for the claude.ai / remote-connector surface. For the hackathon, Claude Code
and Claude for Life Sciences can both drive the **local stdio server**, so we can ship
value with zero deployment.

## Architecture

```
Claude Code / Claude for Life Sciences
        │  (MCP, stdio — JSON-RPC over stdin/stdout)
        ▼
  atlas-mcp  (new: paper-radar/mcp/)   ──in-process──▶  api/supa.py, api/embeddings.py
        │                                                 │
        └── reuses the SAME functions the FastAPI uses ───┘
                                                          ▼
                                              Supabase (Postgres + RLS)
```

The MCP server is a **thin adapter over code that already exists**. The FastAPI
service already does the hard parts:

- **JWT verification + RLS scoping** — `api/supa.py`: `user_client(token)` acts as the
  user so lab membership is enforced; `service_client()` for the global corpus.
- **Keyword search** — `search_papers` RPC (Postgres full-text, RLS-scoped, paginated).
- **Semantic search** — the `/search/semantic` logic (embed the query server-side with
  the Voyage key, then `match_papers` RPC, RLS-scoped).
- **Stable deep links** — the web app addresses an open paper as `?paper=<id>`, so a
  tool result can return a shareable reference.

Decision: the MCP server calls these **in-process** (imports `supa.py` / `embeddings.py`),
not over HTTP to the running API. No second network hop, one auth model, one codebase.

## Tool surface (P1 — read-only)

Built with the official Python SDK (`from mcp.server.fastmcp import FastMCP`). Each tool
returns a **citation-ready text block** (title, authors, venue/year, DOI, deep link) plus
structured fields, so Claude refers to papers cleanly.

- `search_lab_papers(query, mode="keyword"|"semantic", limit=10)` — ranked hits from the
  caller's lab. `keyword` → `search_papers` RPC; `semantic` → embed + `match_papers`.
- `get_paper(paper_id)` — full metadata, DOI, abstract, tags, and the `?paper=<id>` link.
- `list_recent_papers(limit=10)` — the lab feed, newest first.

P3 adds one **write** tool:

- `post_paper(url, note?)` — resolve + post a paper into the lab, reusing the existing
  `/posts` path so RLS enforces membership.

## Auth (P2)

The server acts **as a specific user in a specific lab**, so RLS does the access control
for free — the same model the web app and API already use.

- **Local / Claude Code (P1–P3):** pass a **Supabase access token** (or a lab-scoped
  personal access token we mint) via an environment variable. Claude Code expands
  `${ATLAS_TOKEN}` from the shell into the server's env — the secret never lands in
  `.mcp.json` or git. The server attaches it exactly like `user_client(token)` does today.
- **Remote / claude.ai connectors (P4):** full **OAuth 2.1** — the MCP server becomes an
  OAuth *Resource Server* (RFC 9728 protected-resource metadata) that validates Supabase
  JWTs via introspection (`auth.get_user`). ⚠️ This is the one genuinely hard part:
  Supabase GoTrue does not do dynamic client registration for third-party MCP clients, so
  P4 likely needs a small OAuth broker (or a provider such as WorkOS/Auth0). Out of scope
  until after the hackathon.

## Registering in Claude Code

Project-scoped, committed to git so the team shares it:

```jsonc
// .mcp.json (repo root)
{
  "mcpServers": {
    "atlas": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "atlas-mcp"],
      "env": {
        "ATLAS_TOKEN": "${ATLAS_TOKEN}"   // expanded from the shell, never committed
      }
    }
  }
}
```

Equivalent one-liner:

```bash
claude mcp add --scope project --transport stdio \
  --env ATLAS_TOKEN="${ATLAS_TOKEN}" atlas -- uv run atlas-mcp
```

Each teammate runs `export ATLAS_TOKEN=…` before launching Claude Code. For Claude for
Life Sciences at the hackathon: the same stdio server works wherever MCP stdio is
supported; if that environment can only reach a **remote** connector, pull P4 forward
(Claude Code can also consume it via `claude mcp add --transport http … --header
"Authorization: Bearer …"`).

## Implementation gotchas (Python stdio)

- **stdout is JSON-RPC only.** All logging goes to **stderr** (`logging` configured to
  stderr); no stray `print()`. A dirty stdout breaks the protocol silently.
- Sanity-check by running the launch command directly — it should print nothing to
  stdout: `uv run atlas-mcp 2>&1 | head`.
- First-run startup (uv resolve / imports like umap) can be slow; the client's default
  startup timeout is 30 s (`MCP_TIMEOUT` overrides). Keep heavy imports lazy.
- Tools that can return large results may set `_meta["anthropic/maxResultSizeChars"]`.

## Open decisions

1. **Token type for P1** — reuse a raw Supabase access token (simplest, but short-lived)
   vs. mint a longer-lived lab-scoped personal access token. Lean: raw token for the
   spike, PAT before sharing with the team.
2. **Supabase Cloud now or stay local for the spike?** Lean: spike locally; migrate to
   Cloud before P4 (and before anyone remote needs the data).
3. **Package layout** — `paper-radar/mcp/` as its own module vs. folding into `api/`.
   Lean: separate `mcp/` module that imports from `api/` so the two entry points stay
   distinct.

## Next step

Build **P1**: the local read-only stdio server (`search_lab_papers`, `get_paper`,
`list_recent_papers`), reusing `api/supa.py` and `api/embeddings.py`, registered in
Claude Code via `.mcp.json`, validated by asking Claude to search the seeded lab.
