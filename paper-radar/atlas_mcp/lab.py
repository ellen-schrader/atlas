"""Data layer for the Atlas MCP server.

Acts as a specific Atlas user against Supabase so RLS scopes every read to the
labs that user belongs to — the same security model as ``api/supa.py``. The
user is chosen by environment:

  * ``ATLAS_TOKEN``                     — a Supabase access token (JWT), or
  * ``ATLAS_EMAIL`` + ``ATLAS_PASSWORD`` — email/password we sign in with.

Optional: ``ATLAS_TEAM_ID`` (default lab when the user is in more than one) and
``ATLAS_WEB_URL`` (base for the ``?paper=`` deep links; defaults to the Vite dev
server).
"""

from __future__ import annotations

import os
from functools import lru_cache

from api import embeddings
from api.config import get_api_settings
from supabase import Client, create_client

# Explicit columns — never `papers(*)`, which would drag the 1024-dim embedding
# into every response.
PAPER_COLUMNS = (
    "id, url, doi, title, authors, abstract, venue, year, keywords, tags, code_url, data_url"
)
POST_COLUMNS = "id, team_id, paper_id, posted_at, note, posted_by_label, tags"


class LabError(RuntimeError):
    """A user-facing problem (bad auth, unknown lab, no results scope)."""


@lru_cache
def _session() -> tuple[Client, str | None]:
    """An authenticated Supabase client acting as the configured user, cached."""
    s = get_api_settings()
    if not (s.supabase_url and s.supabase_anon_key):
        raise LabError("Supabase is not configured — check api/.env.")
    client = create_client(s.supabase_url, s.supabase_anon_key)

    token = os.environ.get("ATLAS_TOKEN")
    if token:
        client.postgrest.auth(token)
        try:
            resp = client.auth.get_user(token)
        except Exception as exc:  # noqa: BLE001 — surface as a clean auth error
            raise LabError(f"ATLAS_TOKEN was rejected: {exc}") from exc
        return client, (resp.user.id if resp and resp.user else None)

    email, password = os.environ.get("ATLAS_EMAIL"), os.environ.get("ATLAS_PASSWORD")
    if not (email and password):
        raise LabError(
            "No credentials: set ATLAS_TOKEN, or ATLAS_EMAIL and ATLAS_PASSWORD, "
            "so the MCP server can act as a lab member."
        )
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not sign in to Atlas as {email}: {exc}") from exc
    client.postgrest.auth(res.session.access_token)
    return client, res.user.id


def get_client() -> Client:
    return _session()[0]


def web_url() -> str:
    return os.environ.get("ATLAS_WEB_URL", "http://localhost:5173").rstrip("/")


def paper_link(paper_id: str) -> str:
    """A shareable deep link that opens the paper in the web app."""
    return f"{web_url()}/papers?paper={paper_id}"


def list_teams() -> list[dict]:
    """The labs the configured user belongs to (id, name, slug)."""
    client, uid = _session()
    q = client.table("team_members").select("team_id, teams(id, name, slug)")
    if uid:
        q = q.eq("user_id", uid)
    rows = q.execute().data or []
    # RLS lets a member see teammates too; dedupe to the distinct teams.
    seen: dict[str, dict] = {}
    for r in rows:
        t = r.get("teams")
        if t and t["id"] not in seen:
            seen[t["id"]] = t
    return list(seen.values())


def resolve_team(team_id: str | None) -> dict:
    """Pick the lab to act on: explicit id → ATLAS_TEAM_ID → the only one."""
    teams = list_teams()
    if not teams:
        raise LabError("You don't belong to any lab.")
    if team_id:
        for t in teams:
            if t["id"] == team_id:
                return t
        raise LabError(f"You are not a member of lab {team_id}.")
    env_team = os.environ.get("ATLAS_TEAM_ID")
    if env_team:
        for t in teams:
            if t["id"] == env_team:
                return t
    if len(teams) == 1:
        return teams[0]
    opts = "; ".join(f"{t['name']} ({t['id']})" for t in teams)
    raise LabError(f"You're in multiple labs — pass team_id. Options: {opts}")


def _hydrate(client: Client, posts: list[dict]) -> list[dict]:
    """Attach each post's paper (one `in_` query), preserving post order."""
    ids = list({p["paper_id"] for p in posts})
    if not ids:
        return []
    papers = client.table("papers").select(PAPER_COLUMNS).in_("id", ids).execute().data or []
    by_id = {p["id"]: p for p in papers}
    out = []
    for p in posts:
        paper = by_id.get(p["paper_id"])
        if paper:
            out.append({**p, "paper": paper})
    return out


def search(team: dict, query: str, mode: str, limit: int) -> list[dict]:
    """Ranked posts in `team` for `query`. mode: "keyword" | "semantic"."""
    client = get_client()
    if mode == "semantic":
        # The embedding key is server-side only; the ranking RPC runs as the
        # user, so RLS still scopes results to this lab.
        vector = embeddings.embed_query(query)  # raises EmbeddingError if unavailable
        matches = (
            client.rpc(
                "match_papers", {"p_team": team["id"], "p_query": vector, "p_limit": limit}
            )
            .execute()
            .data
            or []
        )
        if not matches:
            return []
        sim = {m["post_id"]: m["similarity"] for m in matches}
        posts = (
            client.table("paper_posts").select(POST_COLUMNS).in_("id", list(sim)).execute().data
            or []
        )
        hydrated = _hydrate(client, posts)
        for h in hydrated:
            h["similarity"] = sim.get(h["id"])
        hydrated.sort(key=lambda h: -(h.get("similarity") or 0))
        return hydrated

    if mode != "keyword":
        raise LabError(f"Unknown search mode {mode!r} — use 'keyword' or 'semantic'.")
    posts = (
        client.rpc("search_papers", {"p_team": team["id"], "p_q": query, "p_limit": limit})
        .execute()
        .data
        or []
    )
    return _hydrate(client, posts)


def recent(team: dict, limit: int) -> list[dict]:
    """The lab's most recently posted papers (search_papers with an empty query)."""
    client = get_client()
    posts = (
        client.rpc("search_papers", {"p_team": team["id"], "p_q": "", "p_limit": limit})
        .execute()
        .data
        or []
    )
    return _hydrate(client, posts)


def get_post(team: dict, paper_id: str) -> dict:
    """One paper as posted in `team`, hydrated with its metadata."""
    client = get_client()
    posts = (
        client.table("paper_posts")
        .select(POST_COLUMNS)
        .eq("team_id", team["id"])
        .eq("paper_id", paper_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not posts:
        raise LabError(f"No paper {paper_id} in {team['name']}.")
    return _hydrate(client, posts)[0]
