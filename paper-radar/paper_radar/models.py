"""Data models.

- SQLModel *tables*: ``Paper``, ``Label``, ``User``, ``Team``, ``Comment``,
  ``Reaction`` (persisted in SQLite).
- Plain Pydantic ``PaperEnrichment``: the structured shape we ask the LLM to
  return when enriching a paper (kept separate from the table so the enrichment
  step never has to know about database concerns).

The papers table is shared across all teams; comments and reactions are scoped
to the team of the member who wrote them.

List-valued columns (authors, tags, interests) are stored as JSON blobs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LabelSource(StrEnum):
    """Where an interest label came from."""

    manual = "manual"
    cited = "cited"
    figures_channel = "figures_channel"


class Paper(SQLModel, table=True):
    """A single paper discovered from the lab's Teams channel."""

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True, unique=True)
    title: str | None = None
    authors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    venue: str | None = None
    year: int | None = None
    posted_by: str | None = None
    posted_at: datetime | None = None

    # Source metadata resolved at ingest (arXiv/Crossref/PubMed/Europe PMC/pages).
    doi: str | None = Field(default=None, index=True)
    abstract: str | None = None
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    # Enrichment (filled in by the enrich stage).
    summary: str | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    code_url: str | None = None
    data_url: str | None = None

    # Set once the paper is embedded; row index into the FAISS index.
    embedding_id: int | None = Field(default=None, index=True)


class Label(SQLModel, table=True):
    """A lab interest judgement about a paper."""

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    user_id: str = Field(default="lab", index=True)
    interest: int = Field(default=0, description="0 = skip, 1 = maybe, 2 = strong.")
    good_figure: bool = False
    source: LabelSource = Field(default=LabelSource.manual)


class Team(SQLModel, table=True):
    """A group of users (e.g. one lab) who share comments and reactions."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_utcnow)


class User(SQLModel, table=True):
    """A lab member (or the lab itself) whose taste we model.

    ``id`` is the normalized (lowercased) email for accounts created through
    signup; legacy/system users like ``"lab"`` have an empty ``password_hash``
    and cannot log in.
    """

    id: str = Field(primary_key=True)
    name: str
    password_hash: str = ""
    team_id: int | None = Field(default=None, foreign_key="team.id", index=True)
    profile_md: str = ""
    interests: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Comment(SQLModel, table=True):
    """A comment on a paper, visible to everyone on the author's team."""

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    user_id: str = Field(foreign_key="user.id")
    body: str
    created_at: datetime = Field(default_factory=_utcnow)


class Reaction(SQLModel, table=True):
    """An emoji reaction to a paper, visible to everyone on the author's team.

    One user can react to a paper with a given emoji at most once (toggling
    removes the row).
    """

    __table_args__ = (UniqueConstraint("paper_id", "user_id", "emoji"),)

    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(foreign_key="paper.id", index=True)
    team_id: int = Field(foreign_key="team.id", index=True)
    user_id: str = Field(foreign_key="user.id")
    emoji: str
    created_at: datetime = Field(default_factory=_utcnow)


class PaperEnrichment(BaseModel):
    """Structured output shape for LLM enrichment of one paper.

    Mirrors the enrichable fields on :class:`Paper`; used as the schema the
    enrichment agent must return.
    """

    title: str | None = None
    authors: list[str] = []
    venue: str | None = None
    year: int | None = None
    summary: str | None = None
    tags: list[str] = []
    code_url: str | None = None
    data_url: str | None = None
