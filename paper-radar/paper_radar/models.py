"""Data models.

- SQLModel *tables*: ``Paper``, ``Label``, ``User`` (persisted in SQLite).
- Plain Pydantic ``PaperEnrichment``: the structured shape we ask the LLM to
  return when enriching a paper (kept separate from the table so the enrichment
  step never has to know about database concerns).

List-valued columns (authors, tags, interests) are stored as JSON blobs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


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


class User(SQLModel, table=True):
    """A lab member (or the lab itself) whose taste we model."""

    id: str = Field(primary_key=True)
    name: str
    profile_md: str = ""
    interests: list[str] = Field(default_factory=list, sa_column=Column(JSON))


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
