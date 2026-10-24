"""Add a resolved paper to a lab's library, as a background importer does.

Shared by the Teams import and saved-search suggestions: store the paper (or
its published version), post it to the lab once, then embed, tag, look for
duplicate pairs and link clinical trials -- the steps every importer repeated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from paper_radar.ingest.metadata import PaperMetadata
from paper_radar.ingest.urls import _normalize_key

from .config import get_api_settings

log = logging.getLogger(__name__)


@dataclass
class Added:
    paper_id: str
    posted: bool  # False when the lab already had it (by DOI, alias, or a racing post)


def add_to_lab(
    svc,
    team_id: str,
    meta: PaperMetadata,
    url: str,
    *,
    source: str,
    posted_by: str | None = None,
    posted_by_label: str | None = None,
) -> Added:
    """Store ``meta`` and post it to ``team_id`` (service role ``svc``). Idempotent:
    the lab holding the paper already is not an error. Raises on database errors."""
    # Deferred: app imports the importers, so importing app at module load
    # would be circular. These helpers carry the tested dedup + embed logic.
    from .app import _embed_and_store, _enrich_and_store, _upsert_paper
    from .merge_suggestions import suggest_for_post
    from .paper_identity import swap_to_published
    from .trial_links import link_paper

    # A published preprint is stored as its published version.
    meta, stored_url, preprint = swap_to_published(meta, url)
    paper_id, needs_embedding = _upsert_paper(
        meta, stored_url, _normalize_key(stored_url), [preprint] if preprint else []
    )
    existing = (
        svc.table("paper_posts")
        .select("id")
        .eq("paper_id", paper_id)
        .eq("team_id", team_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return Added(paper_id, False)  # already in the lab (matched by DOI under another URL)
    try:
        svc.table("paper_posts").insert(
            {
                "paper_id": paper_id,
                "team_id": team_id,
                "posted_by": posted_by,
                "posted_by_label": posted_by_label,
                "source": source,
            }
        ).execute()
    except Exception as insert_exc:
        # Two imports of the same new paper can race past the `existing` check;
        # the unique(paper_id, team_id) constraint (23505) is the backstop -- a
        # benign no-op, not a failure worth warning about.
        if getattr(insert_exc, "code", None) == "23505":
            return Added(paper_id, False)
        raise
    # The paper is in the lab now; what follows is best effort. A failure is
    # logged, not raised, so a caller doesn't count a posted paper as lost
    # (the embedding and tag backfills retry what is still missing).
    try:
        if needs_embedding and get_api_settings().voyage_api_key:
            _embed_and_store(paper_id, meta.title, meta.abstract)
        if needs_embedding:
            _enrich_and_store(paper_id, meta.title, meta.abstract)
        suggest_for_post(team_id, paper_id)
        link_paper(team_id, paper_id)  # clinical trials; never raises
    except Exception as exc:
        log.warning("after posting paper %s to team %s: %s", paper_id, team_id, exc)
    return Added(paper_id, True)
