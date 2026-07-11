"""Taste model scoring -- STUB.

Two complementary strategies to implement:

1. **In-context scoring** -- give Claude the user's profile + a batch of papers
   and ask for a 0-1 interest score each. Cheap, no training, good cold-start.
2. **Pairwise scoring** -- present pairs and ask which the lab would prefer;
   aggregate the comparisons (e.g. Bradley-Terry / Elo) into a ranking. More
   robust to scale drift once some labels exist.

Fill in the bodies yourself. Read model/config from ``get_settings()``.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..models import Paper, User


def score_in_context(
    user: User,
    papers: list[Paper],
    *,
    settings: Settings | None = None,
) -> dict[int, float]:
    """Score each paper's interest for ``user`` in ``[0, 1]``.

    Args:
        user: The lab profile whose taste we score against.
        papers: Papers to score.
        settings: Optional settings override.

    Returns:
        Mapping of ``paper.id`` -> interest score.
    """
    settings = settings or get_settings()
    # TODO: build a prompt from user.profile_md + user.interests and the papers'
    # titles/summaries/tags; ask Claude for one score per paper; parse + return.
    raise NotImplementedError


def score_pairwise(
    user: User,
    pair: tuple[Paper, Paper],
    *,
    settings: Settings | None = None,
) -> float:
    """Return P(the lab prefers ``pair[0]`` over ``pair[1]``) in ``[0, 1]``.

    Args:
        user: The lab profile.
        pair: The two papers to compare.
        settings: Optional settings override.
    """
    settings = settings or get_settings()
    # TODO: ask Claude which paper better matches the lab's interests; map the
    # answer (and any expressed confidence) to a probability.
    raise NotImplementedError


def rank_papers(scores: dict[int, float]) -> list[int]:
    """Return paper ids sorted by descending interest score."""
    # TODO (trivial): sort scores.items() by value, return the ids.
    raise NotImplementedError
