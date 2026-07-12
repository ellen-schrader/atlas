"""Tests for team-scoped comments and reactions."""

from __future__ import annotations

from paper_radar.auth import signup
from paper_radar.db import get_session, init_db
from paper_radar.models import Paper
from paper_radar.social import add_comment, list_comments, reaction_summary, toggle_reaction

INMEM = "sqlite://"


def _make_paper(url: str) -> int:
    init_db(INMEM)
    with get_session(INMEM) as session:
        paper = Paper(url=url, title="Some paper")
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper.id


def test_comments_are_scoped_to_the_team():
    paper_id = _make_paper("https://example.org/social-1")
    alice = signup("Alice", "alice@a.org", "password-a", "Team A", db_url=INMEM)
    amir = signup("Amir", "amir@a.org", "password-a", "Team A", db_url=INMEM)
    bob = signup("Bob", "bob@b.org", "password-b", "Team B", db_url=INMEM)

    add_comment(paper_id, alice.id, alice.team_id, "great figure 3", db_url=INMEM)
    add_comment(paper_id, bob.id, bob.team_id, "team B private note", db_url=INMEM)

    # Both members of team A see Alice's comment, with her display name.
    seen_by_amir = list_comments(paper_id, amir.team_id, db_url=INMEM)
    assert [(c.author, c.body) for c in seen_by_amir] == [("Alice", "great figure 3")]

    # Team B only sees its own comment.
    seen_by_bob = list_comments(paper_id, bob.team_id, db_url=INMEM)
    assert [c.body for c in seen_by_bob] == ["team B private note"]


def test_reaction_toggle_and_team_scoping():
    paper_id = _make_paper("https://example.org/social-2")
    cara = signup("Cara", "cara@c.org", "password-c", "Team C", db_url=INMEM)
    cole = signup("Cole", "cole@c.org", "password-c", "Team C", db_url=INMEM)
    dana = signup("Dana", "dana@d.org", "password-d", "Team D", db_url=INMEM)

    assert toggle_reaction(paper_id, cara.id, cara.team_id, "👍", db_url=INMEM) is True
    assert toggle_reaction(paper_id, cole.id, cole.team_id, "👍", db_url=INMEM) is True
    assert toggle_reaction(paper_id, dana.id, dana.team_id, "👍", db_url=INMEM) is True

    by_emoji = {s.emoji: s for s in reaction_summary(paper_id, cara.team_id, cara.id, db_url=INMEM)}
    assert by_emoji["👍"].count == 2  # Dana's reaction is on team D, not visible here
    assert by_emoji["👍"].mine is True
    assert by_emoji["❤️"].count == 0

    # Toggling again removes Cara's reaction.
    assert toggle_reaction(paper_id, cara.id, cara.team_id, "👍", db_url=INMEM) is False
    by_emoji = {s.emoji: s for s in reaction_summary(paper_id, cara.team_id, cara.id, db_url=INMEM)}
    assert by_emoji["👍"].count == 1
    assert by_emoji["👍"].mine is False


def test_empty_comment_rejected():
    paper_id = _make_paper("https://example.org/social-3")
    eryn = signup("Eryn", "eryn@e.org", "password-e", "Team E", db_url=INMEM)
    try:
        add_comment(paper_id, eryn.id, eryn.team_id, "   ", db_url=INMEM)
    except ValueError:
        pass
    else:
        raise AssertionError("empty comment should raise")
