"""Comments and reactions on papers, scoped to a team.

Papers are shared across all teams, but every comment/reaction carries the
``team_id`` of its author and is only shown to members of that team.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select

from .db import get_session, init_db
from .models import Comment, Reaction, User

# The fixed palette of reactions offered in the UI.
REACTION_EMOJIS = ["👍", "❤️", "🎉", "💡", "🤔"]


@dataclass
class CommentView:
    """A comment joined with its author's display name, ready for the UI."""

    id: int
    author: str
    body: str
    created_at: datetime


@dataclass
class ReactionSummary:
    """Team-wide tally for one emoji on one paper."""

    emoji: str
    count: int
    mine: bool  # whether the current user is among the reactors


def add_comment(
    paper_id: int, user_id: str, team_id: int, body: str, db_url: str | None = None
) -> Comment:
    body = body.strip()
    if not body:
        raise ValueError("Comment must not be empty.")
    init_db(db_url)
    with get_session(db_url) as session:
        comment = Comment(paper_id=paper_id, user_id=user_id, team_id=team_id, body=body)
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return comment


def list_comments(paper_id: int, team_id: int, db_url: str | None = None) -> list[CommentView]:
    """All comments on ``paper_id`` visible to ``team_id``, oldest first."""
    init_db(db_url)
    with get_session(db_url) as session:
        rows = session.exec(
            select(Comment, User.name)
            .join(User, User.id == Comment.user_id, isouter=True)
            .where(Comment.paper_id == paper_id, Comment.team_id == team_id)
            .order_by(Comment.created_at)
        ).all()
    return [
        CommentView(
            id=comment.id,
            author=author or comment.user_id,
            body=comment.body,
            created_at=comment.created_at,
        )
        for comment, author in rows
    ]


def toggle_reaction(
    paper_id: int, user_id: str, team_id: int, emoji: str, db_url: str | None = None
) -> bool:
    """Add the reaction if absent, remove it if present. Returns True if now set."""
    init_db(db_url)
    with get_session(db_url) as session:
        existing = session.exec(
            select(Reaction).where(
                Reaction.paper_id == paper_id,
                Reaction.user_id == user_id,
                Reaction.emoji == emoji,
            )
        ).first()
        if existing is not None:
            session.delete(existing)
            session.commit()
            return False
        session.add(Reaction(paper_id=paper_id, user_id=user_id, team_id=team_id, emoji=emoji))
        session.commit()
        return True


def reaction_summary(
    paper_id: int, team_id: int, user_id: str, db_url: str | None = None
) -> list[ReactionSummary]:
    """Per-emoji tallies for the team, in ``REACTION_EMOJIS`` order."""
    init_db(db_url)
    with get_session(db_url) as session:
        rows = session.exec(
            select(Reaction).where(Reaction.paper_id == paper_id, Reaction.team_id == team_id)
        ).all()
    summaries = []
    for emoji in REACTION_EMOJIS:
        mine = [r for r in rows if r.emoji == emoji]
        summaries.append(
            ReactionSummary(
                emoji=emoji,
                count=len(mine),
                mine=any(r.user_id == user_id for r in mine),
            )
        )
    return summaries
