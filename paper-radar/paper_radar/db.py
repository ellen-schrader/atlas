"""Database engine + session helpers (SQLite via SQLModel)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

# Importing models registers the tables on SQLModel.metadata so create_all works.
from . import models  # noqa: F401
from .config import Settings, get_settings


@lru_cache
def get_engine(db_url: str | None = None):
    """Return a cached SQLAlchemy engine.

    Pass ``db_url`` to target a different database (e.g. ``sqlite://`` for an
    in-memory test database).
    """
    settings: Settings = get_settings()
    url = db_url or settings.db_url
    if url == "sqlite://":
        # In-memory: keep one shared connection so tables persist across sessions.
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(url, connect_args={"check_same_thread": False})


def init_db(db_url: str | None = None) -> None:
    """Create all tables if they do not yet exist."""
    engine = get_engine(db_url)
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session(db_url: str | None = None) -> Iterator[Session]:
    """Yield a session bound to the (cached) engine."""
    engine = get_engine(db_url)
    with Session(engine) as session:
        yield session
