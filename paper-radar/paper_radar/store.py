"""Small persistence helpers shared by the CLI and the Streamlit app."""

from __future__ import annotations

import json

from sqlmodel import select

from .config import get_settings
from .db import get_session, init_db
from .models import Paper


def load_fixture_papers() -> list[Paper]:
    """Load seed papers from ``data/fixtures/papers.json`` (unsaved Paper objects)."""
    path = get_settings().fixtures_dir / "papers.json"
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    return [Paper(**rec) for rec in records]


def list_papers() -> list[Paper]:
    """Return all papers from the DB, seeding the fixtures first if it is empty.

    This is what the app calls so it always has something to show. Fixtures are
    written to the DB (rather than returned transiently) so every paper has an
    id that comments and reactions can attach to.
    """
    init_db()
    with get_session() as session:
        papers = list(session.exec(select(Paper)).all())
        if papers:
            return papers
        fixtures = load_fixture_papers()
        for paper in fixtures:
            session.add(paper)
        session.commit()
        for paper in fixtures:
            session.refresh(paper)
        return fixtures


def upsert_paper(paper: Paper) -> Paper:
    """Insert ``paper``, or return the existing row if its URL is already known."""
    init_db()
    with get_session() as session:
        existing = session.exec(select(Paper).where(Paper.url == paper.url)).first()
        if existing is not None:
            return existing
        session.add(paper)
        session.commit()
        session.refresh(paper)
        return paper
