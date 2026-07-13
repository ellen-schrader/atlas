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

import ipaddress
import logging
import socket
import time
from functools import lru_cache, wraps
from urllib.parse import urlsplit

from api import embeddings
from api.config import get_api_settings
from supabase import Client, ClientOptions, create_client

from .config import get_atlas_settings

log = logging.getLogger("atlas_mcp.lab")

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
    return "jwt expired" in msg or "token is expired" in msg or "unauthorized" in msg or (
        "jwt" in msg and "expired" in msg
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


def web_url() -> str:
    return get_atlas_settings().atlas_web_url.rstrip("/")


def paper_link(paper_id: str) -> str:
    """A shareable deep link that opens the paper in the web app."""
    return f"{web_url()}/papers?paper={paper_id}"


@with_refresh
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


@with_refresh
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

MAX_URL_LEN = 2048
MAX_NOTE_LEN = 2000


def validate_share_url(url: str) -> str:
    """Accept only a plausible public http(s) article URL. Blocks non-http
    schemes and loopback/private/link-local hosts so an injected URL can't point
    the metadata fetch at internal infrastructure (SSRF)."""
    raw = (url or "").strip()
    if not raw:
        raise LabError("No URL given.")
    if len(raw) > MAX_URL_LEN:
        raise LabError("That URL is too long.")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise LabError("Only http(s) links can be shared.")
    host = parts.hostname
    if not host:
        raise LabError("That URL has no host.")
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith(".localhost") or lowered.endswith(".internal"):
        raise LabError("That host isn't allowed.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and _is_blocked_ip(ip):
        raise LabError("That host isn't allowed.")
    return raw


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    )


def _reject_private_dns(host: str) -> None:
    """Resolve `host` and reject if it maps to a private/loopback/link-local IP —
    blocks a *public hostname* that points at internal infra (the literal-IP check
    in validate_share_url can't catch that). Best-effort: it does not close the
    DNS-rebinding window between here and the fetch; airtight SSRF protection would
    need a check at connect time."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return  # unresolvable — let fetch_metadata surface the real error
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise LabError("That host resolves to a disallowed address.")


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
    by the fetch rate limiter (so dry-run previews can't be looped for free) and a
    DNS check that rejects public names resolving to internal addresses."""
    from paper_radar.ingest.metadata import fetch_metadata
    from paper_radar.ingest.pdf_extract import _clean_url, _normalize_key

    _fetch_limiter.check()
    safe = validate_share_url(url)
    _reject_private_dns(urlsplit(safe).hostname or "")
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
