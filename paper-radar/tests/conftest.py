"""Suite-wide fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_merge_suggestions(monkeypatch):
    """Posting a paper queues a merge-suggestion pass (api/merge_suggestions.py),
    which reads the lab from the database. Tests of posting have no database, so
    the pass is a no-op unless a test exercises it directly."""
    try:
        import api.merge_suggestions as ms
    except ImportError:  # the api extra is not installed
        return
    monkeypatch.setattr(ms, "suggest_for_post", lambda team_id, paper_id: None)


@pytest.fixture(autouse=True)
def no_trial_links(monkeypatch):
    """Posting a paper also queues linking it to clinical trials
    (api/trial_links.py), which reads the database; a no-op in tests unless a
    test exercises it directly."""
    try:
        import api.trial_links as tl
    except ImportError:  # the api extra is not installed
        return
    monkeypatch.setattr(tl, "link_paper", lambda team_id, paper_id: None)
    monkeypatch.setattr(tl, "link_lab", lambda team_id: None)
