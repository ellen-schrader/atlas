"""Offline tests for the map_layouts cold tier (api/layout_store.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from api import layout_store as ls


class _FakeLayouts:
    """In-memory stand-in for the Supabase `map_layouts` table."""

    def __init__(self):
        self.rows: list[dict] = []
        self._reset()

    def _reset(self):
        self._op = None
        self._filters: dict = {}
        self._lt: tuple[str, str] | None = None
        self._pending: dict | None = None

    def table(self, _name):
        self._reset()
        return self

    def select(self, _cols):
        self._op = "select"
        return self

    def upsert(self, row, on_conflict=""):
        self._op = "upsert"
        self._pending = row
        self._conflict = [c.strip() for c in on_conflict.split(",")]
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, k, v):
        self._filters[k] = v
        return self

    def lt(self, k, v):
        self._lt = (k, v)
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self._op == "upsert":
            key = {k: self._pending[k] for k in self._conflict}
            self.rows = [
                r for r in self.rows if any(r.get(k) != v for k, v in key.items())
            ]
            self.rows.append({"created_at": datetime.now(UTC).isoformat(), **self._pending})
            return type("R", (), {"data": [self._pending]})
        if self._op == "delete":
            self.rows = [r for r in self.rows if not self._match(r)]
            return type("R", (), {"data": []})
        return type("R", (), {"data": [r for r in self.rows if self._match(r)]})

    def _match(self, row):
        if not all(row.get(k) == v for k, v in self._filters.items()):
            return False
        if self._lt is not None:
            k, v = self._lt
            return row.get(k, "") < v
        return True


_POINTS = {
    "p1": {"x": 1.5, "y": -2.0, "cluster": 0},
    "p2": {"x": 0.25, "y": 3.0, "cluster": 1},
}


def test_layout_round_trips(monkeypatch):
    fake = _FakeLayouts()
    monkeypatch.setattr(ls, "service_client", lambda: fake)

    assert ls.load_layout("team", "sig") is None  # nothing persisted yet
    ls.store_layout("team", "sig", _POINTS)
    assert ls.load_layout("team", "sig") == _POINTS
    assert ls.load_layout("team", "other-sig") is None  # a changed set misses
    assert ls.load_layout("other-team", "sig") is None  # never cross-team


def test_store_replaces_same_signature(monkeypatch):
    fake = _FakeLayouts()
    monkeypatch.setattr(ls, "service_client", lambda: fake)

    ls.store_layout("team", "sig", _POINTS)
    moved = {"p1": {"x": 9.0, "y": 9.0, "cluster": 1}}
    ls.store_layout("team", "sig", moved)
    assert len(fake.rows) == 1  # upsert, not accumulate
    assert ls.load_layout("team", "sig") == moved


def test_store_gcs_ancient_rows_for_the_team(monkeypatch):
    fake = _FakeLayouts()
    monkeypatch.setattr(ls, "service_client", lambda: fake)

    old = (datetime.now(UTC) - timedelta(days=ls._GC_DAYS + 5)).isoformat()
    fake.rows.append(
        {"team_id": "team", "signature": "ancient", "coords": {}, "created_at": old}
    )
    fake.rows.append(
        {"team_id": "other-team", "signature": "ancient", "coords": {}, "created_at": old}
    )
    ls.store_layout("team", "sig", _POINTS)
    sigs = {(r["team_id"], r["signature"]) for r in fake.rows}
    assert ("team", "ancient") not in sigs        # GC'd
    assert ("other-team", "ancient") in sigs      # other teams untouched
    assert ("team", "sig") in sigs


def test_degrades_when_table_is_missing(monkeypatch):
    class _Boom:
        def table(self, _name):
            raise RuntimeError("relation map_layouts does not exist")

    monkeypatch.setattr(ls, "service_client", lambda: _Boom())
    assert ls.load_layout("team", "sig") is None  # read degrades to a miss
    ls.store_layout("team", "sig", _POINTS)       # write is a logged no-op
