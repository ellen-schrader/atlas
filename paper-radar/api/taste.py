"""What a person in a lab likes to read: the recommendation signals, shared.

The web app's Discover feed (api/app.py) and the Claude connector (atlas_mcp)
rank papers the same way from this module, so Claude's "for you" and the app's
agree. Plain Python on purpose: the MCP server runs without numpy, and the
vectors involved are a few hundred at most.

The signals (docs/dashboard.md §3.4), each searched on its own and interleaved:

  * profile     the person's research profile, embedded (profiles.profile_vec);
  * tags        the tags they follow (profiles.interests);
  * engagement  a weighted, time-decayed centroid of the papers they posted,
                saved, reacted to, discussed or read in the lab.

Database reads go through whichever Supabase client the caller has -- the
user's own in the app, the connector's in atlas_mcp -- so RLS applies as usual.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from .merge_suggestions import fold

# Engagement weights for the taste centroid. Not all engagement is endorsement:
# an explicit save or a reaction is a strong "I want more like this"; a plain
# `read` only means "consumed" (preference unknown), so it barely nudges taste; a
# 🤔 reaction is skeptical, not enthusiastic. Sharing a paper with the lab is a
# deliberate pick, as strong as a reaction -- and for a lab that talks in Teams
# it is often the only signal Atlas has. Weights are decayed by age so recent
# interests outweigh old ones.
W_REACTION = 1.0
W_SKEPTIC = 0.3  # 🤔
W_COMMENT = 0.75
W_BOOKMARK = 1.5  # paper_status.saved — an explicit, deliberate save
W_POSTED = 1.0  # shared with the lab, in Atlas or (by name) from Teams
W_READ = 0.25  # read / reading — consumed, but says little about preference
HALFLIFE_DAYS = 90.0

# When one paper carries several kinds of engagement, the strongest names it.
ANCHOR_RANK = {
    "similar_saved": 0,
    "similar_posted": 1,
    "similar_reacted": 2,
    "similar_discussed": 3,
    "similar_read": 4,
    "similar_reading": 5,
}

# Below this, naming one engaged paper as the reason would be a claim the
# embeddings don't support.
REASON_MIN_SIMILARITY = 0.5

# Discover runs one search per signal and interleaves them, rather than one search
# with a blended vector: in a blend, a few saved papers took 50–70% of the
# weight and followed tags only nudged papers that were already close, so a
# researcher's description and tags could vanish from the feed. Each signal the
# caller has gets an equal, round-robin share of the slots, in this order.
DISCOVER_SOURCES = ("profile", "tags", "engagement")


# --- vectors -------------------------------------------------------------------


def parse_vec(value: object) -> list[float] | None:
    """PostgREST returns a `vector` column as a JSON string; normalize to a list."""
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else list(value)  # type: ignore[arg-type]


def dot(a, b) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


def unit(v) -> list[float]:
    """``v`` scaled to length 1 (unchanged if it has none)."""
    n = dot(v, v) ** 0.5
    return [float(x) / n for x in v] if n > 0 else [float(x) for x in v]


# --- time ------------------------------------------------------------------------


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def recency_decay(ts: datetime | None, now: datetime) -> float:
    """Half-life decay: a signal loses half its weight every HALFLIFE_DAYS."""
    if ts is None:
        return 1.0
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALFLIFE_DAYS)


# --- who posted it -----------------------------------------------------------------


def same_person(label: str | None, display_name: str | None) -> bool:
    """Whether a Teams sender name is this person's Atlas display name.

    Posts that arrive from Teams carry only the sender's name as text
    (``posted_by_label``), never a user id. The names must have the same words,
    in any order and ignoring case, accents and punctuation, so "Schrader,
    Ellen" is Ellen Schrader. A single word never matches: a first name alone
    is too often shared.
    """
    if not label or not display_name:
        return False
    a, b = set(fold(label).split()), set(fold(display_name).split())
    return len(a) >= 2 and a == b


def own_posts(client, user_id: str, team_id: str, display_name: str | None) -> list[dict]:
    """The caller's posts in the lab, ``{paper_id, posted_at}``: the ones Atlas
    knows are theirs, plus Teams posts whose sender name is theirs."""
    mine = (
        client.table("paper_posts")
        .select("paper_id, posted_at")
        .eq("team_id", team_id)
        .eq("posted_by", user_id)
        .execute()
        .data
        or []
    )
    if not display_name:
        return mine
    unattributed = (
        client.table("paper_posts")
        .select("paper_id, posted_at, posted_by_label")
        .eq("team_id", team_id)
        .is_("posted_by", "null")
        .not_.is_("posted_by_label", "null")
        .execute()
        .data
        or []
    )
    return mine + [
        {"paper_id": r["paper_id"], "posted_at": r["posted_at"]}
        for r in unattributed
        if same_person(r.get("posted_by_label"), display_name)
    ]


# --- engagement ----------------------------------------------------------------------


def engagement_weights(
    client,
    user_id: str,
    team_id: str,
    anchors: dict[str, str] | None = None,
    display_name: str | None = None,
) -> dict[str, float]:
    """Per-paper positive-interest weight for the user in this lab, blending signal
    strength (save > post = reaction > comment > read) with recency decay.

    Pass ``anchors`` to also collect, from the same rows, each paper's strongest
    kind of engagement for the recommendation reasons (see ANCHOR_RANK). Pass
    ``display_name`` to count the Teams posts sent under it (see same_person)."""
    now = datetime.now(UTC)
    weights: dict[str, float] = {}

    def add(paper_id: str, w: float) -> None:
        weights[paper_id] = weights.get(paper_id, 0.0) + w

    def anchor(paper_id: str, kind: str) -> None:
        if anchors is None:
            return
        if paper_id not in anchors or ANCHOR_RANK[kind] < ANCHOR_RANK[anchors[paper_id]]:
            anchors[paper_id] = kind

    for p in own_posts(client, user_id, team_id, display_name):
        add(p["paper_id"], W_POSTED * recency_decay(parse_ts(p.get("posted_at")), now))
        anchor(p["paper_id"], "similar_posted")
    for r in (
        client.table("reactions")
        .select("paper_id, emoji, created_at")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    ):
        base = W_SKEPTIC if r.get("emoji") == "🤔" else W_REACTION
        add(r["paper_id"], base * recency_decay(parse_ts(r.get("created_at")), now))
        # 🤔 is skeptical: it nudges taste, but "which you reacted to" would read
        # as an endorsement.
        if r.get("emoji") != "🤔":
            anchor(r["paper_id"], "similar_reacted")
    for c in (
        client.table("comments")
        .select("paper_id, created_at")
        .eq("team_id", team_id)
        .eq("author_id", user_id)
        .execute()
        .data
        or []
    ):
        add(c["paper_id"], W_COMMENT * recency_decay(parse_ts(c.get("created_at")), now))
        anchor(c["paper_id"], "similar_discussed")
    for s in (
        client.table("paper_status")
        .select("paper_id, saved, status, updated_at")
        .eq("team_id", team_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    ):
        # Not saved and never started means the row says nothing — it is what
        # un-saving a paper, or un-marking it read, leaves behind. Scoring it as
        # W_READ would let *discarding* a paper feed the taste vector as though
        # it had been consumed. Harmless while the client deleted those rows on
        # the way past; since 20261007130000 they are kept on purpose, so the
        # same question has to be asked here.
        if not s.get("saved") and s.get("status") == "unread":
            continue
        # Keyed off `saved`, not a status value. Since the two-axis split
        # (20261006120000) a save is a boolean that survives being read, so the
        # old `status == "to_read"` test would never fire again and every saved
        # paper would quietly collapse to the much weaker W_READ.
        base = W_BOOKMARK if s.get("saved") else W_READ
        add(s["paper_id"], base * recency_decay(parse_ts(s.get("updated_at")), now))
        if s.get("saved"):
            anchor(s["paper_id"], "similar_saved")
        elif s.get("status") == "read":
            anchor(s["paper_id"], "similar_read")
        elif s.get("status") == "reading":
            anchor(s["paper_id"], "similar_reading")
    return weights


def blend_taste(
    profile_vec: list[float] | None,
    weights: dict[str, float],
    papers: list[dict],
    loaded: dict | None = None,
) -> list[float] | None:
    """A taste vector: a confidence-weighted blend of the profile embedding and a
    recency-/strength-weighted engagement centroid over ``weights``.

    ``papers`` are the weighted papers' rows (``id, title, embedding``). The
    engagement side's weight grows with how many papers the user has actually
    engaged with, so a single incidental interaction can't hijack the feed while
    the profile carries a sparse user. Missing either side falls back to the other;
    missing both returns None (cold start).

    Pass ``loaded`` to keep, for the reasons: "vecs" (paper id → unit vector),
    "titles", and the per-signal query vectors "profile_q" / "engagement_q" that
    Discover searches with."""
    if loaded is not None:
        loaded.setdefault("vecs", {})
        loaded.setdefault("titles", {})
    profile = unit(profile_vec) if profile_vec is not None else None

    centroid = None
    n_engaged = 0
    acc: list[float] | None = None
    wsum = 0.0
    for r in papers:
        w = weights.get(r["id"], 0.0)
        raw = parse_vec(r.get("embedding"))
        if w <= 0 or not raw:
            continue
        v = unit(raw)
        if loaded is not None:
            loaded["vecs"][r["id"]] = v
            loaded["titles"][r["id"]] = r.get("title")
        acc = (
            [w * x for x in v] if acc is None else [a + w * x for a, x in zip(acc, v, strict=False)]
        )
        wsum += w
        n_engaged += 1
    if acc is not None and wsum > 0:
        centroid = unit([a / wsum for a in acc])

    if loaded is not None:
        loaded["profile_q"] = profile
        loaded["engagement_q"] = centroid

    if profile is None and centroid is None:
        return None
    if centroid is None:
        return profile
    if profile is None:
        return centroid

    # Both present: trust engagement more the more of it there is (capped so the
    # profile always keeps a voice). n=1 → ~0.2, n=4 → 0.5, large → 0.7.
    eng_conf = min(0.7, n_engaged / (n_engaged + 4.0))
    return unit(
        [(1 - eng_conf) * p + eng_conf * c for p, c in zip(profile, centroid, strict=False)]
    )


# --- reasons -------------------------------------------------------------------------


def pick_reason(vec, anchors: list[tuple[str, str, str, list[float]]]) -> dict | None:
    """The anchor (kind, paper_id, title, unit vector) nearest to ``vec`` (a unit
    vector), as a reason dict — or None when none clears REASON_MIN_SIMILARITY."""
    best: tuple[float, tuple] | None = None
    for a in anchors:
        sim = dot(vec, a[3])
        if best is None or sim > best[0]:
            best = (sim, a)
    if best is None or best[0] < REASON_MIN_SIMILARITY:
        return None
    kind, paper_id, title, _ = best[1]
    return {"kind": kind, "ref_id": paper_id, "ref_label": title}


def profile_tags(profile_md: str, tags: list[str]) -> list[str]:
    """The tags the profile text names as a phrase: "spatial-transcriptomics"
    matches "spatial transcriptomic(s)", "t-cell-exhaustion" matches "T cell
    exhaustion" but not "B cell … exhaustion", and "cell" doesn't match
    "cellular". Each word may take a plural "s" either way round."""
    text = profile_md.lower()
    out: list[str] = []
    for tag in tags:
        words = [w for w in re.split(r"[-_\s/]+", tag.lower()) if w]
        if not words:
            continue
        phrase = r"[\s\-/]+".join(re.escape(w.removesuffix("s")) + "s?" for w in words)
        if re.search(r"(?<![a-z0-9])" + phrase + r"(?![a-z0-9])", text):
            out.append(tag)
    return out


def followed_hits(post: dict, follows: list[str]) -> list[str]:
    """The followed tags this post carries, by post_tags(): its lab tags if it
    has any, else the paper's own — the rule every tag surface uses."""
    if not follows:
        return []
    tags = post.get("tags") or (post.get("papers") or {}).get("tags") or []
    wanted = set(follows)
    return [t for t in tags if t in wanted]


def interleave(
    sources: dict[str, list[tuple[str, float]]], limit: int
) -> tuple[list[str], dict[str, float], dict[str, str]]:
    """Round-robin over the sources in DISCOVER_SOURCES order, skipping a post
    another source already placed; a source that runs dry yields its turns.
    Returns (post ids in order, post id → similarity, post id → source)."""
    lists = [(name, sources[name]) for name in DISCOVER_SOURCES if sources.get(name)]
    pos = {name: 0 for name, _ in lists}
    order: list[str] = []
    sims: dict[str, float] = {}
    origin: dict[str, str] = {}
    while len(order) < limit:
        placed = False
        for name, items in lists:
            while pos[name] < len(items) and items[pos[name]][0] in origin:
                pos[name] += 1
            if pos[name] < len(items) and len(order) < limit:
                post_id, sim = items[pos[name]]
                pos[name] += 1
                order.append(post_id)
                sims[post_id] = sim
                origin[post_id] = name
                placed = True
        if not placed:
            break
    return order, sims, origin
