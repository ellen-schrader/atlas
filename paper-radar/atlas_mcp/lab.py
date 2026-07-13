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

import json
import logging
import time
from contextvars import ContextVar
from functools import lru_cache, wraps

from api import embeddings
from api.config import get_api_settings
from paper_radar.ingest import url_guard
from supabase import Client, ClientOptions, create_client

from .config import get_atlas_settings

log = logging.getLogger("atlas_mcp.lab")

# Explicit columns — never `papers(*)`, which would drag the 1024-dim embedding
# into every response.
PAPER_COLUMNS = (
    "id, url, doi, title, authors, abstract, venue, year, keywords, tags, code_url, data_url"
)
POST_COLUMNS = "id, team_id, paper_id, posted_at, note, posted_by_label, tags"


# The lab the in-flight tool call is acting on. Set by resolve_team so the audit
# decorator can attribute a call without re-resolving the team.
_current_team: ContextVar[dict | None] = ContextVar("atlas_current_team", default=None)


class LabError(RuntimeError):
    """A user-facing problem (bad auth, unknown lab, no results scope)."""


@lru_cache
def _session() -> tuple[Client, str | None]:
    """An authenticated Supabase client acting as the configured user, cached.

    The user's token is applied to *all* sub-clients (postgrest for RLS reads,
    storage for figure-image downloads) by baking it into the client headers.
    """
    s = get_api_settings()
    if not (s.supabase_url and s.supabase_anon_key):
        raise LabError("Supabase is not configured — check api/.env.")
    cfg = get_atlas_settings()

    if cfg.atlas_token:
        token = cfg.atlas_token
        probe = create_client(s.supabase_url, s.supabase_anon_key)
        try:
            resp = probe.auth.get_user(token)
        except Exception as exc:  # noqa: BLE001 — surface as a clean auth error
            raise LabError(f"ATLAS_TOKEN was rejected: {exc}") from exc
        uid = resp.user.id if resp and resp.user else None
    elif cfg.atlas_email and cfg.atlas_password:
        signin = create_client(s.supabase_url, s.supabase_anon_key)
        try:
            res = signin.auth.sign_in_with_password(
                {"email": cfg.atlas_email, "password": cfg.atlas_password}
            )
        except Exception as exc:  # noqa: BLE001
            raise LabError(f"Could not sign in to Atlas as {cfg.atlas_email}: {exc}") from exc
        token, uid = res.session.access_token, res.user.id
    else:
        raise LabError(
            "No credentials: set ATLAS_TOKEN, or ATLAS_EMAIL and ATLAS_PASSWORD "
            "(in api/.env or the environment), so the MCP server can act as a lab member."
        )

    client = create_client(
        s.supabase_url,
        s.supabase_anon_key,
        options=ClientOptions(headers={"Authorization": f"Bearer {token}"}),
    )
    return client, uid


def get_client() -> Client:
    return _session()[0]


def current_user_id() -> str | None:
    """The signed-in user's id (for 'only mine' filters)."""
    return _session()[1]


def _is_auth_error(exc: Exception) -> bool:
    """Whether `exc` looks like an expired/invalid session — worth a refresh + retry."""
    code = getattr(exc, "code", None)
    if code in (401, "401", "PGRST301", "PGRST302"):
        return True
    msg = f"{getattr(exc, 'message', '')} {exc}".lower()
    return (
        "jwt expired" in msg
        or "token is expired" in msg
        or "unauthorized" in msg
        or ("jwt" in msg and "expired" in msg)
    )


def with_refresh(fn):
    """On an expired-session error, drop the cached session and retry once.

    The cached client bakes in a bearer token that expires (~1h); a long-running
    stdio server would otherwise 401 until restarted. Clean `LabError`s (bad
    input, no such lab) are never retried.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LabError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_auth_error(exc):
                _session.cache_clear()
                return fn(*args, **kwargs)
            raise

    return wrapper


def require_access(team: dict) -> None:
    """Refuse to act on a lab that hasn't switched Claude access on.

    Enforced here, in the one place every tool resolves its lab through, rather than
    bolted onto each of the ten tools — a tool added later is gated by construction.

    Connecting is not a personal decision: the server reads the lab's shared corpus
    and, since ``post_paper``, writes into it. So an *owner* opts the lab in, from
    the Connect screen in the web app.
    """
    client, _ = _session()
    try:
        rows = client.table("mcp_access").select("enabled").eq("team_id", team["id"]).execute().data
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not check Claude access for {team['name']}: {exc}") from exc

    if not (rows and rows[0].get("enabled")):
        raise LabError(
            f"Claude access is off for {team['name']}. An owner can turn it on in Atlas → "
            f"Connect Claude. (This is a lab-wide setting: the server can read the lab's "
            f"papers and post into it, so it isn't one member's call.)"
        )


def log_tool_call(team: dict | None, tool: str, ok: bool) -> None:
    """Record a tool call so the lab can see what Claude looked at.

    Best-effort and never raises: an audit write must not be able to fail a tool the
    user legitimately invoked. A missing row is a gap in the log, not a broken lab.
    """
    if not team:
        return
    try:
        client, uid = _session()
        client.table("mcp_tool_calls").insert(
            {"team_id": team["id"], "user_id": uid, "tool": tool, "ok": ok}
        ).execute()
    except Exception:  # noqa: BLE001 — logging is not worth failing a call over
        pass


def web_url() -> str:
    return get_atlas_settings().atlas_web_url.rstrip("/")


def paper_link(paper_id: str) -> str:
    """A shareable deep link that opens the paper in the web app."""
    return f"{web_url()}/papers?paper={paper_id}"


@with_refresh
def list_teams() -> list[dict]:
    """The labs the configured user belongs to (id, name)."""
    client, uid = _session()
    q = client.table("team_members").select("team_id, teams(id, name)")
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
    """Pick the lab to act on: explicit id → ATLAS_TEAM_ID → the only one.

    Also the access gate: every tool that touches a lab resolves it through here, so
    a lab that hasn't opted in is refused once, centrally. ``list_labs`` deliberately
    does not go through this — you need it to find the team_id you're being asked for,
    and it exposes nothing but the names of labs you are already a member of.
    """
    team = _pick_team(team_id)
    # Attribute the call *before* the gate, so a REFUSED attempt is logged too. An
    # audit trail whose only blind spot is "someone tried to use Claude on this lab
    # while access was off" would be missing the one event it most exists to show.
    _current_team.set(team)
    require_access(team)
    return team


def current_team() -> dict | None:
    """The lab the in-flight tool call resolved, if any.

    Lets the audit decorator name the lab without resolving it a second time (which
    would double every tool's round-trips just to write a log row).
    """
    return _current_team.get()


def clear_team() -> None:
    """Forget the resolved lab. Called at the start of every tool.

    Without this, a tool that resolves no lab (``list_labs``) or fails before
    resolving one would inherit whatever the *previous* call left behind, and the
    audit log would attribute it to the wrong lab. An audit trail that misattributes
    is worse than none.
    """
    _current_team.set(None)


def _pick_team(team_id: str | None) -> dict:
    teams = list_teams()
    if not teams:
        raise LabError("You don't belong to any lab.")
    if team_id:
        for t in teams:
            if t["id"] == team_id:
                return t
        raise LabError(f"You are not a member of lab {team_id}.")
    env_team = get_atlas_settings().atlas_team_id
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


def _hydrate_scored(client: Client, rows: list[dict]) -> list[dict]:
    """Given ranking-RPC rows carrying `post_id` + `similarity` (match_papers /
    recommend_papers), fetch and hydrate those posts, attach the score, and return
    them most-similar first."""
    if not rows:
        return []
    sim = {r["post_id"]: r["similarity"] for r in rows}
    posts = (
        client.table("paper_posts").select(POST_COLUMNS).in_("id", list(sim)).execute().data or []
    )
    hydrated = _hydrate(client, posts)
    for h in hydrated:
        h["similarity"] = sim.get(h["id"])
    hydrated.sort(key=lambda h: -(h.get("similarity") or 0))
    return hydrated


@with_refresh
def search(team: dict, query: str, mode: str, limit: int) -> list[dict]:
    """Ranked posts in `team` for `query`. mode: "keyword" | "semantic"."""
    client = get_client()
    if mode == "semantic":
        # The embedding key is server-side only; the ranking RPC runs as the
        # user, so RLS still scopes results to this lab.
        vector = embeddings.embed_query(query)  # raises EmbeddingError if unavailable
        matches = (
            client.rpc("match_papers", {"p_team": team["id"], "p_query": vector, "p_limit": limit})
            .execute()
            .data
            or []
        )
        return _hydrate_scored(client, matches)

    if mode != "keyword":
        raise LabError(f"Unknown search mode {mode!r} — use 'keyword' or 'semantic'.")
    posts = (
        client.rpc("search_papers", {"p_team": team["id"], "p_q": query, "p_limit": limit})
        .execute()
        .data
        or []
    )
    return _hydrate(client, posts)


@with_refresh
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


# === similarity + recommendations (read-only, embedding-based) =============
# All numpy-free: the MCP server runs under the lean `mcp` extra (no numpy), so
# vector math here is plain Python over `list[float]`. The nearest-neighbour work
# stays in Postgres (match_papers / recommend_papers over the HNSW index).


def _unit(v: list[float]) -> list[float] | None:
    """L2-normalise a vector; None if it has no magnitude."""
    s = sum(x * x for x in v) ** 0.5
    return [x / s for x in v] if s > 0 else None


def _centroid(vectors: list[list[float]]) -> list[float] | None:
    """The L2-normalised mean of unit-normalised vectors (equal weight each), so a
    few papers define a taste direction. None when nothing usable was passed."""
    acc: list[float] | None = None
    n = 0
    for v in vectors:
        u = _unit(v)
        if u is None:
            continue
        if acc is None:
            acc = list(u)
        elif len(u) == len(acc):
            for i in range(len(acc)):
                acc[i] += u[i]
        else:
            continue  # different dimensionality — skip rather than crash/corrupt
        n += 1
    if acc is None:
        return None
    return _unit([x / n for x in acc])


def _parse_embedding(raw) -> list[float] | None:
    """PostgREST returns a pgvector column as a JSON string — normalise to a list."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    return raw


def taste_vector(team: dict) -> list[float] | None:
    """A taste centroid for the signed-in user: the mean embedding of the papers
    they've read/are reading or reacted to in this lab. None on cold start (no
    such engagement). RLS scopes every read to the caller."""
    client = get_client()
    uid = current_user_id()
    if not uid:
        return None
    tid = team["id"]
    ids: set[str] = set()
    status = (
        client.table("paper_status")
        .select("paper_id")
        .eq("team_id", tid)
        .eq("user_id", uid)
        .in_("status", ["read", "reading"])
        .execute()
        .data
        or []
    )
    ids.update(r["paper_id"] for r in status)
    reacted = (
        client.table("reactions")
        .select("paper_id")
        .eq("team_id", tid)
        .eq("user_id", uid)
        .execute()
        .data
        or []
    )
    ids.update(r["paper_id"] for r in reacted)
    if not ids:
        return None
    rows = client.table("papers").select("id, embedding").in_("id", list(ids)).execute().data or []
    vectors = [v for v in (_parse_embedding(r.get("embedding")) for r in rows) if v]
    return _centroid(vectors)


@with_refresh
def recommend(team: dict, limit: int) -> list[dict]:
    """Papers to read next, ranked by the user's taste (recommend_papers RPC, which
    already drops self-posted / already-engaged papers and re-ranks for freshness).
    Empty list when there's no taste signal — the caller handles cold start."""
    client = get_client()
    vec = taste_vector(team)
    if vec is None:
        return []
    rows = (
        client.rpc("recommend_papers", {"p_team": team["id"], "p_query": vec, "p_limit": limit})
        .execute()
        .data
        or []
    )
    return _hydrate_scored(client, rows)


def _match_by_vector(client: Client, team: dict, vec: list[float], limit: int) -> list[dict]:
    """Hydrated posts in `team` nearest to `vec` (match_papers RPC), most-similar
    first. Shared by the semantic search / similar / novelty paths."""
    matches = (
        client.rpc("match_papers", {"p_team": team["id"], "p_query": vec, "p_limit": limit})
        .execute()
        .data
        or []
    )
    return _hydrate_scored(client, matches)


def _paper_embedding(client: Client, paper_id: str) -> list[float] | None:
    rows = (
        client.table("papers").select("embedding").eq("id", paper_id).limit(1).execute().data or []
    )
    return _parse_embedding(rows[0]["embedding"]) if rows else None


@with_refresh
def similar(team: dict, paper_id: str, limit: int) -> list[dict] | None:
    """Papers in `team` most similar to `paper_id` (by its stored embedding), the
    anchor itself excluded. None when the anchor has no embedding (caller falls
    back to keyword search). match_papers is team-scoped, so results stay in-lab;
    the caller validates the anchor belongs to the lab (for a clean error + title)."""
    client = get_client()
    vec = _paper_embedding(client, paper_id)
    if vec is None:
        return None
    hits = _match_by_vector(client, team, vec, limit + 1)  # +1 to absorb the anchor
    return [h for h in hits if h["paper_id"] != paper_id][:limit]


@with_refresh
def novelty(
    team: dict, *, text: str | None = None, paper_id: str | None = None, limit: int = 5
) -> list[dict]:
    """The lab papers closest to `text` (embedded) or to `paper_id` (its embedding),
    most-similar first, for a 'have we covered this?' check. Anchor excluded."""
    client = get_client()
    if paper_id:
        get_post(team, paper_id)
        vec = _paper_embedding(client, paper_id)
        if vec is None:
            raise LabError("That paper has no embedding to compare against.")
    elif text and text.strip():
        vec = embeddings.embed_query(text.strip())
    else:
        raise LabError("Give me some text or a paper_id to check.")
    hits = _match_by_vector(client, team, vec, limit + (1 if paper_id else 0))
    if paper_id:
        hits = [h for h in hits if h["paper_id"] != paper_id]
    return hits[:limit]


@with_refresh
def digest(team: dict, days: int) -> dict:
    """Lab activity in the last `days`: new posts (hydrated), new-comment count, and
    the papers the caller was @-mentioned on. All RLS-scoped to the lab."""
    from datetime import datetime, timedelta, timezone

    client = get_client()
    tid = team["id"]
    uid = current_user_id()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Cap the rendered list so an active lab can't dump hundreds of papers into one
    # tool result; the exact-count header still reports the true total.
    post_cap = 20
    posts_resp = (
        client.table("paper_posts")
        .select(POST_COLUMNS + ", posted_by", count="exact")
        .eq("team_id", tid)
        .gte("posted_at", cutoff)
        .order("posted_at", desc=True)
        .limit(post_cap)
        .execute()
    )
    new_papers = _hydrate(client, posts_resp.data or [])
    n_papers = posts_resp.count if posts_resp.count is not None else len(new_papers)

    comments = (
        client.table("comments")
        .select("id", count="exact")
        .eq("team_id", tid)
        .gte("created_at", cutoff)
        .execute()
    )
    n_comments = comments.count or 0

    my_mentions: list[dict] = []
    if uid:
        rows = (
            client.table("mentions")
            .select("paper_id, created_at")
            .eq("team_id", tid)
            .eq("mentioned_user", uid)
            .gte("created_at", cutoff)
            .execute()
            .data
            or []
        )
        if rows:
            ids = list({r["paper_id"] for r in rows})
            papers = client.table("papers").select("id, title").in_("id", ids).execute().data or []
            by_id = {p["id"]: p.get("title") for p in papers}
            my_mentions = [{"title": by_id.get(pid) or pid} for pid in ids]

    return {
        "days": days,
        "new_papers": new_papers,
        "n_papers": n_papers,
        "n_comments": n_comments,
        "mentions": my_mentions,
    }


@with_refresh
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


# === write path (post a paper, comment, mention) ===========================
# These are the only writing operations in the MCP server. They act as the
# signed-in user (RLS enforces lab membership, self-authorship, and that a
# mentionee is a co-member), never with the service-role key — except the one
# global-corpus dedup below, which cannot leak or escalate.

MAX_NOTE_LEN = 2000


def validate_share_url(url: str) -> str:
    """Accept only a plausible public http(s) article URL, as a LabError.

    The rules live in `paper_radar.ingest.url_guard` now — the HTTP API fetches the
    same URLs through the same `fetch_metadata`, and having the guard here meant MCP
    was defended and the API wasn't. This wraps the shared check to keep the MCP
    error type (and the "shared" wording the tools speak).
    """
    try:
        return url_guard.validate_public_url(url)
    except url_guard.BlockedUrl as exc:
        raise LabError(str(exc).replace("fetched", "shared")) from exc


class _RateLimiter:
    """A simple per-process sliding-window cap. The MCP process is one user, so
    this is effectively a per-user write quota that bounds injection-driven spam."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._events: list[float] = []

    def check(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._events = [t for t in self._events if now - t < self.window]
        if len(self._events) >= self.max_events:
            raise LabError(
                "Too many shares in a short time — pausing to avoid flooding the lab. "
                "Try again shortly."
            )
        self._events.append(now)


# Writes and outbound metadata fetches are capped separately: the fetch limiter
# also covers confirm=false dry-runs (which resolve metadata but don't write), so
# an injected preview loop can't drive unbounded outbound requests.
_post_limiter = _RateLimiter(max_events=20, window_seconds=3600)
_fetch_limiter = _RateLimiter(max_events=40, window_seconds=3600)
# Style cards are the mood board's other write path, and each one uploads a
# rendered PNG as well as inserting a row — so an injected loop costs storage,
# not just rows. Capped like post_paper.
_card_limiter = _RateLimiter(max_events=20, window_seconds=3600)


@with_refresh
def list_members(team: dict) -> list[dict]:
    """The lab's members: {user_id, display_name}. RLS-scoped to the caller's lab."""
    client = get_client()
    rows = (
        client.table("team_members")
        .select("user_id, profiles(display_name)")
        .eq("team_id", team["id"])
        .execute()
        .data
        or []
    )
    out = []
    for r in rows:
        prof = r.get("profiles") or {}
        out.append({"user_id": r["user_id"], "display_name": prof.get("display_name") or ""})
    return out


def resolve_member(team: dict, name: str) -> dict:
    """Resolve a teammate to tag by EXACT display name (case-insensitive). Never
    guesses: no match or a name shared by >1 member raises, as does tagging
    yourself. Exact-only is deliberate — it blocks injection like "tag everyone"
    and stops a loose partial from silently tagging the wrong person."""
    wanted = (name or "").strip().lstrip("@")
    if not wanted:
        raise LabError("No teammate name given to tag.")
    me = current_user_id()
    members = [m for m in list_members(team) if m["user_id"] != me]
    matches = [m for m in members if m["display_name"].lower() == wanted.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        others = ", ".join(m["display_name"] for m in members) or "(no teammates)"
        raise LabError(
            f"No teammate named exactly “{wanted}” in {team['name']}. Members: {others}."
        )
    raise LabError(
        f"More than one member is named “{wanted}” in {team['name']} — can't tell them apart."
    )


def resolve_metadata(url: str) -> dict:
    """Fetch citation metadata for a validated URL (one outbound request). Covered
    by the fetch rate limiter (so dry-run previews can't be looped for free) and, in
    `fetch_metadata` itself, a guard that rejects internal addresses — including ones
    reached by redirect."""
    from paper_radar.ingest.metadata import fetch_metadata
    from paper_radar.ingest.urls import _clean_url, _normalize_key

    _fetch_limiter.check()
    # validate_share_url now covers the DNS check too (it's inside validate_public_url),
    # so the separate _reject_private_dns call it used to need is gone.
    safe = validate_share_url(url)
    clean = _clean_url(safe)
    meta = fetch_metadata(clean)
    return {"clean_url": clean, "url_norm": _normalize_key(clean), "meta": meta}


@with_refresh
def find_existing_post(team: dict, paper_id: str) -> str | None:
    """The post id if this paper is already in the lab, else None (idempotency)."""
    rows = (
        get_client()
        .table("paper_posts")
        .select("id")
        .eq("team_id", team["id"])
        .eq("paper_id", paper_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0]["id"] if rows else None


@with_refresh
def post_paper(team: dict, resolved: dict) -> tuple[str, str, bool]:
    """Ensure the paper exists (global dedup) and post it into the lab as the
    user. Returns (post_id, paper_id, already_shared). Rate-limited. Any note the
    user wrote goes into a comment (add_comment_with_mention), not the post row.
    @with_refresh so an expired JWT is refreshed + retried, like the read path."""
    from api.app import _upsert_paper  # global-corpus dedup (service role, contained)

    _post_limiter.check()
    meta, clean_url, url_norm = resolved["meta"], resolved["clean_url"], resolved["url_norm"]
    paper_id, _needs_embedding = _upsert_paper(meta, clean_url, url_norm)

    existing = find_existing_post(team, paper_id)
    if existing:
        return existing, paper_id, True

    uid = current_user_id()
    row = {
        "paper_id": paper_id,
        "team_id": team["id"],
        "posted_by": uid,
        "source": "web",
        "via": "claude_mcp",  # provenance — free-text column, no constraint change
    }
    try:
        inserted = get_client().table("paper_posts").insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "code", None) == "42501":
            raise LabError(f"You are not a member of {team['name']}.") from exc
        raise LabError(f"Could not share the paper: {exc}") from exc
    return inserted.data[0]["id"], paper_id, False


@with_refresh
def add_comment_with_mention(
    team: dict, paper_id: str, body: str, mention: dict | None
) -> str | None:
    """Post a comment as the user; if `mention` is given, tag that teammate (the
    body embeds "@name" so the web UI highlights it, and the mention row notifies
    them + adds the paper to their to-read via the DB trigger).

    Returns None on full success, or a warning string if the comment posted but the
    tag couldn't be added — we DON'T raise there, so the caller reports partial
    success instead of a failure that would invite a retry (and duplicate the
    comment). @with_refresh only ever retries a failed *comment* insert, before
    anything has landed, so it can't duplicate."""
    client = get_client()
    text = (body or "").strip()[:MAX_NOTE_LEN]
    if mention:
        text = f"@{mention['display_name']} {text}".strip()
    if not text:
        return None
    uid = current_user_id()
    try:
        inserted = (
            client.table("comments")
            .insert({"paper_id": paper_id, "team_id": team["id"], "author_id": uid, "body": text})
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise LabError(f"Could not post the comment: {exc}") from exc
    if not mention:
        return None
    comment_id = inserted.data[0]["id"] if inserted.data else None
    try:
        client.table("mentions").insert(
            {
                "paper_id": paper_id,
                "team_id": team["id"],
                "mentioned_user": mention["user_id"],
                "mentioned_by": uid,
                "comment_id": comment_id,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — comment landed; tag is best-effort
        log.warning("mention insert for %s failed: %s", mention["display_name"], exc)
        return f"(couldn't notify @{mention['display_name']} — tag failed)"
    return None
