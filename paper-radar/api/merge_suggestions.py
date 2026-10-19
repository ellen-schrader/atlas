"""Suggest merging a preprint and a published paper that look like one piece of work.

Stated links (Crossref, bioRxiv's API, arXiv) are merged automatically
(api/preprint_watch.py). What is left are pairs nothing links: a lab holding a
preprint and a published paper with nearly the same title and an author in
common. Atlas can't be sure, so it asks: each pair becomes a
``merge_suggestions`` row for that lab, and any member answers it in the app
(decide_merge_suggestion, 20261018120000_preprint_watch.sql). A dismissed pair
stays dismissed: the unique key means it is never inserted again.

Run per lab by the daily job, and for one new paper when it is posted.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher

from paper_radar.ingest.metadata import looks_like_preprint

log = logging.getLogger(__name__)

# How alike two folded titles must be. Journals often retitle a preprint
# slightly ("A …" → "The …", a colon, a word); 0.85 keeps those and drops
# papers that merely share a topic. A person confirms every pair.
MIN_TITLE_SIMILARITY = 0.85
_PAGE = 1000


def fold(text: str) -> str:
    """Lowercase ASCII words: accents, punctuation and case dropped."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def surname(name: str) -> str | None:
    """The last word that is not an initial: "Jane Doe", "J. Doe", "Doe J" → "doe"."""
    words = fold(str(name)).split()
    names = [w for w in words if len(w) > 2] or words
    return names[-1] if names else None


def _author_keys(authors: list) -> set[str]:
    """Surnames of the first and last author: who leads and who supervises, the
    two least likely to change between preprint and publication."""
    if not authors:
        return set()
    return {s for s in (surname(authors[0]), surname(authors[-1])) if s}


def find_pairs(rows: list[dict], only: str | None = None) -> list[tuple[dict, dict, float]]:
    """``(preprint, published, score)`` for every likely pair among one lab's papers.

    ``rows`` carry id, doi, url, venue, title, authors. With ``only``, just the
    pairs that include that paper (a new post). Authors are compared first, as
    they are cheap and rule out nearly everything.
    """
    preprints, published = [], []
    for row in rows:
        if not (row.get("title") or "").strip():
            continue
        side = (
            preprints
            if looks_like_preprint(row.get("doi"), row.get("url"), row.get("venue"))
            else published
        )
        side.append((row, fold(row["title"]), _author_keys(row.get("authors") or [])))

    if only:
        # A new post pairs only with the other side: narrow first, so a lab of
        # thousands costs one pass, not every preprint against every paper.
        if any(row["id"] == only for row, _, _ in preprints):
            preprints = [p for p in preprints if p[0]["id"] == only]
        else:
            published = [p for p in published if p[0]["id"] == only]
    pairs = []
    for pre, pre_title, pre_authors in preprints:
        for pub, pub_title, pub_authors in published:
            if not (pre_authors & pub_authors):
                continue
            matcher = SequenceMatcher(None, pre_title, pub_title)
            if matcher.quick_ratio() < MIN_TITLE_SIMILARITY:
                continue
            score = matcher.ratio()
            if score >= MIN_TITLE_SIMILARITY:
                pairs.append((pre, pub, round(score, 3)))
    return pairs


def lab_papers(
    svc, team_id: str, columns: str = "id, doi, url, venue, title, authors"
) -> list[dict]:
    """Every paper the lab holds, with the given columns (by default, what
    matching needs)."""
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("paper_posts")
            .select(f"papers({columns})")
            .eq("team_id", team_id)
            .order("id")
            .range(start, start + _PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(r["papers"] for r in page if r.get("papers"))
        if len(page) < _PAGE:
            break
        start += _PAGE
    return rows


def suggest(svc, team_id: str, only: str | None = None) -> int:
    """Record the lab's likely pairs as suggestions; returns how many were found.

    Existing pairs, pending or dismissed, are left as they are.
    """
    pairs = find_pairs(lab_papers(svc, team_id), only=only)
    if pairs:
        svc.table("merge_suggestions").upsert(
            [
                {
                    "team_id": team_id,
                    "preprint_id": pre["id"],
                    "published_id": pub["id"],
                    "score": score,
                }
                for pre, pub, score in pairs
            ],
            on_conflict="team_id,preprint_id,published_id",
            ignore_duplicates=True,
        ).execute()
    return len(pairs)


def suggest_for_post(team_id: str, paper_id: str | None) -> None:
    """Background task after a post: suggestions involving the new paper, or
    the whole lab (``paper_id=None``, after an import). Every way of posting
    calls it: the web, BibTeX imports, Teams and MCP."""
    from .supa import service_client

    try:
        suggest(service_client(), team_id, only=paper_id)
    except Exception as exc:  # noqa: BLE001 -- the daily job finds it tomorrow
        log.warning("merge suggestions for paper %s in team %s failed: %s", paper_id, team_id, exc)
