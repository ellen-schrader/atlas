"""Data layer for the Atlas MCP server.

Acts as a specific Atlas user against Supabase so RLS scopes every read to the
labs that user belongs to — the same security model as ``api/supa.py``. Who that
user is depends on the transport:

  * **Hosted (HTTP):** whoever sent the request. The server binds the caller's
    verified token with ``act_as`` for the duration of that request only.
  * **Local (stdio):** one user for the whole process, from the environment —
    ``ATLAS_TOKEN`` (a Supabase access token), or ``ATLAS_EMAIL`` +
    ``ATLAS_PASSWORD`` (signed in with). Only once ``allow_env_session`` is called,
    which the stdio entry point does.

With neither, every call fails: a hosted request that somehow reached a tool
without a bound user must never fall back to the environment's credentials and
read someone else's lab.

Optional: ``ATLAS_TEAM_ID`` (default lab when the user is in more than one) and
``ATLAS_WEB_URL`` (base for the ``?paper=`` deep links; defaults to the hosted
app, so cited links are shareable — override it to point at your own deployment).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache, wraps

from api import embeddings, taste
from api.config import get_api_settings
from api.ratelimit import PerUserRateLimiter
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
# Papers per lab_digest page: one line each, so a fortnight of a busy lab fits.
DIGEST_PAGE = 100


# The lab the in-flight tool call is acting on. Set by resolve_team so the audit
# decorator can attribute a call without re-resolving the team.
_current_team: ContextVar[dict | None] = ContextVar("atlas_current_team", default=None)


class LabError(RuntimeError):
    """A user-facing problem (bad auth, unknown lab, no results scope)."""


# The user the in-flight request acts as (hosted server), bound by `act_as`.
_request_session: ContextVar[tuple[Client, str] | None] = ContextVar(
    "atlas_request_session", default=None
)
# Whether a call with no bound user may act as the environment's user (stdio only).
# A contextvar, not a module flag: it's set in the stdio entry point's own context
# (which every task and worker thread of that server inherits), so nothing else
# sharing the process can switch it on for requests it didn't start.
_env_session_allowed: ContextVar[bool] = ContextVar("atlas_env_session_allowed", default=False)


def allow_env_session() -> None:
    """Let calls in this context act as the user configured in the environment.
    Stdio entry point only."""
    _env_session_allowed.set(True)


def _user_client(token: str) -> Client:
    """A Supabase client that sends `token` on every request, so RLS sees that user.

    The token is applied to *all* sub-clients (postgrest for RLS reads, storage for
    figure-image downloads) by baking it into the client headers.
    """
    s = get_api_settings()
    if not (s.supabase_url and s.supabase_anon_key):
        raise LabError("Supabase is not configured — check api/.env.")
    return create_client(
        s.supabase_url,
        s.supabase_anon_key,
        options=ClientOptions(headers={"Authorization": f"Bearer {token}"}),
    )


@contextmanager
def act_as(token: str, user_id: str, client: Client | None = None) -> Iterator[None]:
    """Run the enclosed tool call as the user who owns `token`.

    The caller (the hosted server's auth layer) must already have verified the token
    and taken `user_id` from it. The binding lives in a contextvar, so concurrent
    requests — each in its own task — never see each other's user. `client`, if
    given, is a client already carrying `token` (the hosted server passes a cheap
    one over a shared connection pool); otherwise a full Supabase client is built.
    """
    reset = _request_session.set((client or _user_client(token), user_id))
    try:
        yield
    finally:
        _request_session.reset(reset)


def _session() -> tuple[Client, str | None]:
    """The Supabase client and user id the current call acts as."""
    bound = _request_session.get()
    if bound is not None:
        return bound
    if not _env_session_allowed.get():
        raise LabError("Not signed in to Atlas.")
    return _env_session()


@lru_cache
def _env_session() -> tuple[Client, str | None]:
    """The stdio user from ``api/.env``, signed in once and cached."""
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

    return _user_client(token), uid


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


# Error codes raised by public.connector_request_guard (the database's connector gate).
_CONNECTOR_REFUSALS = ("ATLAS_CONNECTOR_REVOKED", "ATLAS_CONNECTOR_FORBIDDEN")


def with_refresh(fn):
    """On an expired-session error, drop the cached stdio session and retry once.

    The cached client bakes in a bearer token that expires (~1h); a long-running
    stdio server would otherwise 401 until restarted. Clean `LabError`s (bad
    input, no such lab) are never retried, and neither is a hosted request: its
    token is the client's, so the client refreshes it, and signing in again here
    could only ever mean signing in as somebody else.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LabError:
            raise
        except Exception as exc:  # noqa: BLE001
            if getattr(exc, "code", None) in _CONNECTOR_REFUSALS:
                # The database's connector gate said no (connection revoked, or a read
                # outside its allowlist). Its message is written for the user.
                raise LabError(getattr(exc, "message", None) or str(exc)) from exc
            if not _is_auth_error(exc):
                raise
            if _request_session.get() is not None:
                # Tools only catch LabError; a raw PostgREST 401 would reach the
                # client as an internal error instead of something actionable.
                raise LabError(
                    "Your Atlas sign-in has expired — reconnect Atlas in Claude."
                ) from exc
            _env_session.cache_clear()
            return fn(*args, **kwargs)

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
        if getattr(exc, "code", None) in _CONNECTOR_REFUSALS:
            raise LabError(getattr(exc, "message", None) or str(exc)) from exc
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
    # ATLAS_TEAM_ID is the stdio user's own setting; it means nothing to a hosted caller.
    env_team = get_atlas_settings().atlas_team_id if _request_session.get() is None else ""
    if env_team:
        for t in teams:
            if t["id"] == env_team:
                return t
    if len(teams) == 1:
        return teams[0]
    opts = "; ".join(f"{t['name']} ({t['id']})" for t in teams)
    raise LabError(f"You're in multiple labs — pass team_id. Options: {opts}")


# Query embeddings are the one paid call a hosted tool makes (Voyage). Bounded per
# user by the hosted server's call limit, and here across everyone per UTC day, so no
# amount of use can run up a bill. Long inputs are cut: a few paragraphs is plenty.
_MAX_EMBED_CHARS = 4000


class _DailyBudget:
    def __init__(self) -> None:
        self._day = ""
        self._spent = 0
        self._lock = threading.Lock()

    def spend(self, limit: int) -> None:
        from datetime import UTC, datetime

        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            if today != self._day:
                self._day, self._spent = today, 0
            if self._spent >= limit:
                raise embeddings.EmbeddingError(
                    "today's semantic-search allowance is used up; keyword search still works"
                )
            self._spent += 1

    def refund(self) -> None:
        """Give back a unit whose call produced nothing (Voyage down, no key, …), so an
        outage can't drain the day's allowance for everyone."""
        with self._lock:
            self._spent = max(0, self._spent - 1)


_embed_budget = _DailyBudget()


def _embed_query(text: str) -> list[float]:
    text = text.strip()[:_MAX_EMBED_CHARS]
    if not text:
        raise LabError("Nothing to search for — give me some words.")
    if _request_session.get() is None:
        return embeddings.embed_query(text)
    _embed_budget.spend(get_api_settings().mcp_daily_embeddings)  # hosted: shared, paid
    try:
        return embeddings.embed_query(text)
    except Exception:
        _embed_budget.refund()
        raise


def _hydrate(client: Client, posts: list[dict]) -> list[dict]:
    """Attach each post's paper (URL-sized `in_` queries), preserving post order."""
    ids = list({p["paper_id"] for p in posts})
    if not ids:
        return []
    papers = taste.papers_by_id(client, ids, PAPER_COLUMNS)
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
    hydrated = _hydrate_in_order(client, list(sim))
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
        vector = _embed_query(query)  # raises EmbeddingError if unavailable
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


_parse_embedding = taste.parse_vec


# The caller's signals, computed the way the app's Discover feed does
# (api/taste.py), so Claude's recommendations and the app's agree.


def _taste_signals(client: Client, team: dict) -> dict:
    """What api.taste needs, read as the caller: ``weights`` (paper id → interest),
    ``anchors`` (paper id → strongest engagement), ``loaded`` (query vectors,
    follows, profile text, engaged papers' vectors and titles), ``exclude`` (the
    caller's Teams posts, which the RPCs can't tell are theirs) and ``taste``
    (the blended vector, None on cold start).

    The profile comes from my_recommendation_inputs(): profiles is closed to
    connector tokens, and that function returns the caller's own row only."""
    uid = current_user_id()
    loaded: dict = {"follows": [], "profile_md": "", "profile_md_us": ""}
    signals = {
        "weights": {},
        "anchors": {},
        "loaded": loaded,
        "exclude": frozenset(),
        "taste": None,
    }
    if not uid:
        return signals
    try:
        rows = client.rpc("my_recommendation_inputs", {}).execute().data or []
    except Exception as exc:  # noqa: BLE001
        # PGRST202: the function isn't there (MCP deployed ahead of its migration,
        # or a local stack on another branch). Rank without the profile signals.
        if getattr(exc, "code", None) != "PGRST202":
            raise
        log.warning("my_recommendation_inputs is missing; recommending without the profile")
        rows = []
    profile = rows[0] if rows else {}
    loaded["follows"] = taste.follows_of(profile)
    loaded["profile_md"] = profile.get("profile_md") or ""
    loaded["profile_md_us"] = profile.get("profile_md_us") or ""
    anchors: dict[str, str] = {}
    teams_posts: set[str] = set()
    weights = taste.engagement_weights(
        client,
        uid,
        team["id"],
        anchors,
        display_name=profile.get("display_name"),
        teams_posts=teams_posts,
    )
    papers = taste.papers_by_id(client, list(weights), "id, title, embedding")
    vec = taste.blend_taste(taste.parse_vec(profile.get("profile_vec")), weights, papers, loaded)
    return {
        "weights": weights,
        "anchors": anchors,
        "loaded": loaded,
        "exclude": frozenset(teams_posts),
        "taste": vec,
    }


def _paper_vectors(client: Client, paper_ids) -> dict[str, list[float]]:
    """paper id → unit embedding, for the papers that have one."""
    rows = taste.papers_by_id(client, list(paper_ids), "id, embedding")
    return {r["id"]: taste.unit(v) for r in rows if (v := taste.parse_vec(r.get("embedding")))}


def _with_reasons(
    client: Client,
    hits: list[dict],
    origin: dict[str, str],
    signals: dict,
    vecs: dict[str, list[float]] | None = None,
) -> list[dict]:
    """Attach ``reason`` (api/taste.reason_for) to each hit, from the signal that
    found it (``origin``: post id → source)."""
    if vecs is None:
        engaged = {h["paper_id"] for h in hits if origin.get(h["id"]) == "engagement"}
        vecs = _paper_vectors(client, engaged) if engaged else {}
    candidates = taste.anchor_candidates(signals["anchors"], signals["loaded"])
    for h in hits:
        h["reason"] = taste.reason_for(
            origin.get(h["id"]) or "profile",
            h,
            vecs.get(h["paper_id"]),
            candidates,
            signals["loaded"],
        )
    return hits


def _hydrate_in_order(client: Client, post_ids: list[str]) -> list[dict]:
    """Hydrated posts for ``post_ids``, in that order."""
    if not post_ids:
        return []
    rows = client.table("paper_posts").select(POST_COLUMNS).in_("id", post_ids).execute().data
    by_id = {h["id"]: h for h in _hydrate(client, rows or [])}
    return [by_id[pid] for pid in post_ids if pid in by_id]


@with_refresh
def recommend(team: dict, limit: int) -> list[dict]:
    """Papers to read next, picked the way the app's Discover feed picks them:
    your research profile, the tags you follow and what you post, save, react
    to, discuss and read, each searched on its own and interleaved. Each hit
    carries ``similarity`` and ``reason``. Empty with no taste signal — the
    caller falls back to recent papers, as the app does."""
    client = get_client()
    signals = _taste_signals(client, team)
    if signals["taste"] is None:
        # No profile and no engagement. The app's cold start leads with posts
        # carrying a followed tag, newest first; with no follows either, the
        # caller falls back to recent papers, as the app does.
        follows = signals["loaded"]["follows"]
        rows = taste.rpc_tagged(client, team["id"], follows, None, limit, signals["exclude"])
        hits = _hydrate_in_order(client, [pid for pid, _ in rows])
        return _with_reasons(client, hits, {h["id"]: "tags" for h in hits}, signals, {})
    sources = taste.discover_sources(
        client, team["id"], signals["loaded"], limit, signals["exclude"]
    )
    order, sims, origin = taste.interleave(sources, limit)
    hits = _hydrate_in_order(client, order)
    for h in hits:
        h["similarity"] = sims.get(h["id"])
    return _with_reasons(client, hits, origin, signals)


# The digest's "For you": at most this many papers. A paper counts for a signal
# only if it is in that signal's top quarter of the window AND at least
# FOR_YOU_FLOOR close: the two signals sit on different scales (on one real
# account, papers in the lab scored a median 0.58 against "your posts" but 0.44
# against the research profile), so a single fixed cut-off would let half the
# lab through one and filter the other. The floor keeps a quiet fortnight of
# unrelated papers from producing picks at all.
FOR_YOU_MAX = 5
FOR_YOU_TOP_SHARE = 0.25
FOR_YOU_FLOOR = 0.35


def _top_share(scored: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """The (post id, score) pairs in the top FOR_YOU_TOP_SHARE of the window and
    above FOR_YOU_FLOOR, best first."""
    ranked = sorted(scored, key=lambda x: -x[1])
    keep = max(1, round(len(ranked) * FOR_YOU_TOP_SHARE))
    return [x for x in ranked[:keep] if x[1] >= FOR_YOU_FLOOR]


def _for_you(client: Client, team: dict, cutoff: str, signals: dict) -> list[dict] | None:
    """The window's papers most worth your time, picked like Discover: each
    signal ranks the window on its own (window_scores, in Postgres) and they take
    turns. Papers you posted or engaged with are left out. None when Atlas has
    no signal for you."""
    loaded = signals["loaded"]
    queries = {"profile": loaded.get("profile_q"), "engagement": loaded.get("engagement_q")}
    follows = loaded.get("follows") or []
    if all(q is None for q in queries.values()) and not follows:
        return None

    def window(q) -> list[dict]:
        params = {"p_team": team["id"], "p_since": cutoff, "p_query": q}
        if signals["exclude"]:
            params["p_exclude"] = sorted(signals["exclude"])
        return client.rpc("window_scores", params).execute().data or []

    sources: dict[str, list[tuple[str, float]]] = {}
    rows_by_signal = {name: window(q) for name, q in queries.items() if q is not None}
    for name, rows in rows_by_signal.items():
        scored = [(r["post_id"], r["similarity"]) for r in rows if r["similarity"] is not None]
        sources[name] = _top_share(scored)
    if follows:
        # A followed tag is certain on its own: closeness only orders the tagged
        # papers, and one without an embedding (yet) still counts, last.
        rows = next(iter(rows_by_signal.values()), None) or window(None)
        wanted = set(follows)
        tagged = [r for r in rows if wanted & set(r.get("tags") or [])]
        tagged.sort(key=lambda r: -(r["similarity"] if r["similarity"] is not None else -1.0))
        sources["tags"] = [(r["post_id"], r["similarity"] or 0.0) for r in tagged]

    order, sims, origin = taste.interleave(sources, FOR_YOU_MAX)
    picks = _hydrate_in_order(client, order)
    for h in picks:
        h["similarity"] = sims.get(h["id"])
    return _with_reasons(client, picks, origin, signals)


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
        vec = _embed_query(text.strip())
    else:
        raise LabError("Give me some text or a paper_id to check.")
    hits = _match_by_vector(client, team, vec, limit + (1 if paper_id else 0))
    if paper_id:
        hits = [h for h in hits if h["paper_id"] != paper_id]
    return hits[:limit]


@with_refresh
def digest(team: dict, days: int, offset: int = 0) -> dict:
    """Lab activity in the last `days`: new posts (hydrated, one page of them from
    `offset`), plus — on the first page only — the "For you" picks (None when
    Atlas has no signal for the caller), the new-comment count and the papers the
    caller was @-mentioned on. All RLS-scoped to the lab."""
    from datetime import datetime, timedelta, timezone

    client = get_client()
    tid = team["id"]
    uid = current_user_id()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Page the rendered list so an active lab can't dump hundreds of papers into one
    # tool result; the exact-count header still reports the true total. The id
    # tie-break keeps pages stable when several posts share a timestamp.
    def recent_posts(columns: str):
        return (
            client.table("paper_posts")
            .select(columns, count="exact")
            .eq("team_id", tid)
            .gte("posted_at", cutoff)
        )

    try:
        posts_resp = (
            recent_posts(POST_COLUMNS + ", posted_by")
            .order("posted_at", desc=True)
            .order("id")
            .range(offset, offset + DIGEST_PAGE - 1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        # PostgREST answers an offset past the last row with 416 rather than an
        # empty page; report the true count with no papers instead.
        if getattr(exc, "code", None) != "PGRST103":
            raise
        posts_resp = recent_posts("id").limit(1).execute()
        posts_resp.data = []
    posts = posts_resp.data or []
    new_papers = _hydrate(client, posts)
    n_papers = posts_resp.count if posts_resp.count is not None else offset + len(posts)
    page = {
        "days": days,
        "new_papers": new_papers,
        "n_papers": n_papers,
        # Counted in posts, not hydrated papers: a post whose paper can't be read
        # would otherwise shift every later page.
        "n_fetched": len(posts),
        "n_comments": None,
        "mentions": None,
        "for_you": None,
    }
    if offset:
        # Comments and mentions aren't paged; the first page already reported them.
        return page

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
            my_mentions = [{"id": pid, "title": by_id.get(pid)} for pid in ids]

    try:
        # Nothing new, nothing to pick: skip the signal reads altogether.
        for_you = _for_you(client, team, cutoff, _taste_signals(client, team)) if n_papers else []
    except Exception as exc:  # noqa: BLE001 -- the digest is still worth having
        if getattr(exc, "code", None) in _CONNECTOR_REFUSALS or _is_auth_error(exc):
            raise
        log.warning("for-you picks failed: %s", exc)
        return {**page, "n_comments": n_comments, "mentions": my_mentions, "for_you_failed": True}
    return {**page, "n_comments": n_comments, "mentions": my_mentions, "for_you": for_you}


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


def _RateLimiter(max_events: int, window_seconds: float) -> PerUserRateLimiter:
    """A per-user cap bounding injection-driven spam. Per user because the hosted
    server is one process serving everyone: a single shared window would let one
    user's burst lock out every other lab."""
    return PerUserRateLimiter(
        max_events,
        window_seconds,
        lambda: LabError(
            "Too many shares in a short time — pausing to avoid flooding the lab. "
            "Try again shortly."
        ),
    )


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
    from api.paper_identity import swap_to_published
    from paper_radar.ingest.metadata import fetch_metadata
    from paper_radar.ingest.urls import _clean_url, _normalize_key

    _fetch_limiter.check(current_user_id() or "")
    # validate_share_url now covers the DNS check too (it's inside validate_public_url),
    # so the separate _reject_private_dns call it used to need is gone.
    safe = validate_share_url(url)
    clean = _clean_url(safe)
    # A preprint that has been published is shared as its published version;
    # `preprint` is what was asked for, so the tool can say so.
    meta, clean, preprint = swap_to_published(fetch_metadata(clean), clean)
    return {
        "clean_url": clean,
        "url_norm": _normalize_key(clean),
        "meta": meta,
        "preprint": preprint,
    }


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

    _post_limiter.check(current_user_id() or "")
    meta, clean_url, url_norm = resolved["meta"], resolved["clean_url"], resolved["url_norm"]
    preprint = resolved.get("preprint")
    paper_id, _needs_embedding = _upsert_paper(
        meta, clean_url, url_norm, [preprint] if preprint else []
    )

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
    from api.merge_suggestions import suggest_for_post  # never raises

    suggest_for_post(team["id"], paper_id)
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
