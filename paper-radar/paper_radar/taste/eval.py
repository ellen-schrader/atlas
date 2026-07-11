"""Taste model evaluation -- STUB.

Measure how well predicted interest scores agree with held-out human interest
labels (the ``Label.interest`` values). Report a rank correlation so we can tell
whether the taste model is actually learning the lab's preferences.

Fill in the bodies yourself.
"""

from __future__ import annotations

from ..models import Label


def spearman_correlation(predicted: dict[int, float], labels: list[Label]) -> float:
    """Spearman rank correlation between predicted scores and held-out interest.

    Args:
        predicted: Mapping of ``paper.id`` -> predicted interest score.
        labels: Held-out labels (use ``Label.paper_id`` / ``Label.interest``).

    Returns:
        Spearman's rho in ``[-1, 1]``.
    """
    # TODO: align predicted[paper_id] with label.interest over the overlapping
    # paper ids, rank both, and compute the correlation.
    raise NotImplementedError


def evaluate(
    predicted: dict[int, float],
    labels: list[Label],
) -> dict[str, float]:
    """Return a small metrics dict (e.g. spearman, n) for a scoring run."""
    # TODO: assemble {"spearman": ..., "n": ...} (and any extras you want).
    raise NotImplementedError
