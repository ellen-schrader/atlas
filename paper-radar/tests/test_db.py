"""Smoke tests for DB init and the fixtures loader."""

from __future__ import annotations

from sqlmodel import select

from paper_radar.db import get_session, init_db
from paper_radar.models import LabelSource, Paper
from paper_radar.store import load_fixture_papers

INMEM = "sqlite://"


def test_init_db_and_roundtrip():
    init_db(INMEM)
    paper = Paper(
        url="https://example.org/paper-1",
        title="Test paper",
        authors=["A. Author", "B. Author"],
        tags=["breast", "spatial"],
        year=2025,
    )
    with get_session(INMEM) as session:
        session.add(paper)
        session.commit()

    with get_session(INMEM) as session:
        rows = session.exec(select(Paper)).all()
        assert len(rows) == 1
        got = rows[0]
        assert got.url == "https://example.org/paper-1"
        # JSON list columns round-trip.
        assert got.authors == ["A. Author", "B. Author"]
        assert got.tags == ["breast", "spatial"]


def test_label_source_enum():
    assert LabelSource.manual.value == "manual"
    assert set(LabelSource) == {
        LabelSource.manual,
        LabelSource.cited,
        LabelSource.figures_channel,
    }


def test_fixtures_load():
    papers = load_fixture_papers()
    assert 3 <= len(papers) <= 5
    for p in papers:
        assert p.url
        assert isinstance(p.authors, list)
        assert isinstance(p.tags, list)
