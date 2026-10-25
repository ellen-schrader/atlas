"""Searches to suggest to someone who has few or none (issue #164).

Writing a first search was the hard part (Ellen, 2026-10-24: "overwhelmed by
how to phrase my query and all the options"), so the Suggestions page offers a
few ready-made ones, built from what Atlas already knows about the person:

  * pairs of tags that come together on papers they shared or saved
    ("spatial transcriptomics" AND "breast cancer"): narrow, so useful;
  * the tags they follow (profiles.interests);
  * tags on several of their papers;
  * the lab's most common tags, for someone who has done neither yet.

Free and instant: no model call. Tags are already one spelling each (tag
hygiene, 20261010140000), hyphens for spaces. A tag an existing search already
names is left out. Nothing is saved: the page opens the search form filled in.
"""

from __future__ import annotations

import re
from collections import Counter
from itertools import combinations

from paper_radar.search import query as q

from .taste import follows_of, post_tags

MAX_IDEAS = 4
_ROWS = 2000  # tagged posts read per question; plenty for counting

# Tags that say what kind of paper it is, not what it is about.
_GENERIC = {
    "review",
    "preprint",
    "methods",
    "method",
    "software",
    "tool",
    "tools",
    "dataset",
    "datasets",
    "benchmark",
    "perspective",
    "commentary",
    "protocol",
    "resource",
    "clinical-trial",
}


def _words(tag: str) -> str:
    return tag.replace("-", " ").strip()


def _term(tag: str) -> str:
    """The tag as a title/abstract term: a phrase in quotes, a word bare."""
    words = _words(tag)
    return f'"{words}"[tiab]' if " " in words else f"{words}[tiab]"


def _name(tag: str) -> str:
    words = _words(tag)
    # Leave short ones alone: "tls", "scrna" are acronyms, not words to capitalise.
    return words[0].upper() + words[1:] if len(words) > 5 else words


def _usable(tag: str) -> bool:
    return len(_words(tag)) >= 3 and tag not in _GENERIC


def _covered(tag: str, queries: list[str]) -> bool:
    """Whether an existing search already names the tag."""
    pattern = re.compile(rf"\b{re.escape(_words(tag))}", re.IGNORECASE)
    return any(pattern.search(text.replace("-", " ")) for text in queries)


def _tags(post: dict) -> list[str]:
    """A post's usable tags: the lab's, else the paper's own (taste.post_tags)."""
    raw = post_tags(post)
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, str) and _usable(t)]


_POST_TAGS = "paper_id, tags, paper:papers(tags)"


def _my_tag_sets(svc, user_id: str, team_id: str) -> list[set[str]]:
    """The lab's tags on each paper the person shared or saved, one set per paper."""
    posted = (
        svc.table("paper_posts")
        .select(_POST_TAGS)
        .eq("team_id", team_id)
        .eq("posted_by", user_id)
        .limit(_ROWS)
        .execute()
        .data
        or []
    )
    by_paper = {r["paper_id"]: set(_tags(r)) for r in posted}
    saved = [
        r["paper_id"]
        for r in svc.table("paper_status")
        .select("paper_id")
        .eq("user_id", user_id)
        .eq("team_id", team_id)
        .eq("saved", True)
        .limit(_ROWS)
        .execute()
        .data
        or []
        if r["paper_id"] not in by_paper
    ]
    for start in range(0, len(saved), 150):
        rows = (
            svc.table("paper_posts")
            .select(_POST_TAGS)
            .eq("team_id", team_id)
            .in_("paper_id", saved[start : start + 150])
            .execute()
            .data
            or []
        )
        for r in rows:
            by_paper.setdefault(r["paper_id"], set()).update(_tags(r))
    return [tags for tags in by_paper.values() if tags]


def _lab_tags(svc, team_id: str) -> Counter:
    rows = (
        svc.table("paper_posts")
        .select(_POST_TAGS)
        .eq("team_id", team_id)
        .order("posted_at", desc=True)
        .limit(_ROWS)
        .execute()
        .data
        or []
    )
    return Counter(t for r in rows for t in set(_tags(r)))


def search_ideas(
    svc, user_id: str, team_id: str, lab_name: str, existing_queries: list[str]
) -> list[dict]:
    """Up to :data:`MAX_IDEAS` searches to suggest, best first:
    ``{name, query, reason}``. Empty if Atlas knows nothing to go on."""
    profile = (
        svc.table("profiles").select("interests").eq("id", user_id).limit(1).execute().data or []
    )
    follows = [t for t in follows_of(profile[0] if profile else None) if _usable(t)]
    mine = _my_tag_sets(svc, user_id, team_id)
    singles = Counter(t for tags in mine for t in tags)
    pairs = Counter(pair for tags in mine for pair in combinations(sorted(tags), 2))

    ideas: list[dict] = []
    used: set[str] = set()

    def add(tags: tuple[str, ...], reason: str) -> None:
        if len(ideas) >= MAX_IDEAS or set(tags) <= used:
            return
        if all(_covered(t, existing_queries) for t in tags):
            return
        query = " AND ".join(_term(t) for t in tags)
        try:
            q.parse(query)
        except q.QueryError:
            return
        name = _name(tags[0]) + "".join(f" and {_words(t)}" for t in tags[1:])
        ideas.append({"name": name, "query": query, "reason": reason})
        used.update(tags)

    for (a, b), n in pairs.most_common():
        if n < 2 or len([i for i in ideas if " AND " in i["query"]]) >= 2:
            break
        add((a, b), f"Together on {n} papers you shared or saved")
    for tag in follows:
        add((tag,), "A tag you follow")
    for tag, n in singles.most_common():
        if n < 2:
            break
        add((tag,), f"On {n} papers you shared or saved")
    if len(ideas) < MAX_IDEAS:
        for tag, n in _lab_tags(svc, team_id).most_common(10):
            if n < 2:
                break
            add((tag,), f"Common in {lab_name}’s library")
    return ideas
