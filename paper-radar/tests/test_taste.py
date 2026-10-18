"""Offline tests for the shared recommendation signals (api/taste.py)."""

from __future__ import annotations

import random

import numpy as np
import pytest

from api import taste


class _Query:
    """A supabase-py query stand-in that applies the eq / is_ filters it is given."""

    def __init__(self, rows: list[dict]):
        self._rows = rows
        self._negate = False

    @property
    def not_(self):
        self._negate = True
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, col, value):
        self._rows = [r for r in self._rows if col not in r or r[col] == value]
        return self

    def is_(self, col, value):
        assert value == "null"
        keep = (
            (lambda r: r.get(col) is not None) if self._negate else (lambda r: r.get(col) is None)
        )
        self._negate = False
        self._rows = [r for r in self._rows if keep(r)]
        return self

    def in_(self, *_a, **_k):
        return self

    def execute(self):
        return type("Result", (), {"data": self._rows})()


class _Client:
    def __init__(self, **tables):
        self._tables = tables

    def table(self, name):
        return _Query(list(self._tables.get(name, [])))


# --- whose Teams post is it --------------------------------------------------------


def test_same_person_matches_names_in_any_order():
    assert taste.same_person("Ellen Schrader", "Ellen Schrader")
    assert taste.same_person("Schrader, Ellen", "ellen schrader")
    assert taste.same_person("Zoë Müller", "Zoe Muller")


def test_same_person_is_strict():
    assert not taste.same_person("Ellen", "Ellen")  # one word is too often shared
    assert not taste.same_person("Ellen Schrader", "Ellen Smith")
    assert not taste.same_person("Ellen M Schrader", "Ellen Schrader")
    assert not taste.same_person(None, "Ellen Schrader")
    assert not taste.same_person("Ellen Schrader", None)


# --- engagement --------------------------------------------------------------------


def _posts():
    return [
        {"paper_id": "mine", "posted_by": "u1", "posted_at": None, "posted_by_label": None},
        {
            "paper_id": "teams-mine",
            "posted_by": None,
            "posted_by_label": "Schrader, Ellen",
            "posted_at": None,
        },
        {
            "paper_id": "teams-other",
            "posted_by": None,
            "posted_by_label": "Sara Ali",
            "posted_at": None,
        },
        {"paper_id": "theirs", "posted_by": "u2", "posted_at": None, "posted_by_label": None},
    ]


def test_papers_you_posted_count_including_your_teams_posts():
    client = _Client(paper_posts=_posts())
    anchors: dict[str, str] = {}
    weights = taste.engagement_weights(client, "u1", "t1", anchors, display_name="Ellen Schrader")
    assert weights == {
        "mine": pytest.approx(taste.W_POSTED),
        "teams-mine": pytest.approx(taste.W_POSTED),
    }
    assert anchors == {"mine": "similar_posted", "teams-mine": "similar_posted"}


def test_without_a_display_name_only_attributed_posts_count():
    weights = taste.engagement_weights(_Client(paper_posts=_posts()), "u1", "t1")
    assert set(weights) == {"mine"}


def test_a_save_outranks_a_post_as_the_reason():
    client = _Client(
        paper_posts=[{"paper_id": "p", "posted_by": "u1", "posted_at": None}],
        paper_status=[{"paper_id": "p", "saved": True, "status": "unread", "updated_at": None}],
        reactions=[{"paper_id": "p", "emoji": "👍", "created_at": None}],
    )
    anchors: dict[str, str] = {}
    weights = taste.engagement_weights(client, "u1", "t1", anchors)
    assert anchors["p"] == "similar_saved"
    assert weights["p"] == pytest.approx(taste.W_POSTED + taste.W_BOOKMARK + taste.W_REACTION)


# --- the blend, unchanged by the move off numpy --------------------------------------


def _numpy_blend(profile_vec, weights, papers):
    """The pre-move implementation (api/app.py, numpy), as the reference."""

    def l2(v):
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    profile = l2(np.asarray(profile_vec, dtype=np.float64)) if profile_vec else None
    acc, wsum, n = None, 0.0, 0
    for r in papers:
        w = weights.get(r["id"], 0.0)
        if w <= 0 or not r.get("embedding"):
            continue
        v = l2(np.asarray(r["embedding"], dtype=np.float64))
        acc = w * v if acc is None else acc + w * v
        wsum += w
        n += 1
    centroid = l2(acc / wsum) if acc is not None else None
    if profile is None and centroid is None:
        return None
    if centroid is None:
        return profile
    if profile is None:
        return centroid
    conf = min(0.7, n / (n + 4.0))
    return l2((1 - conf) * profile + conf * centroid)


@pytest.mark.parametrize("with_profile", [True, False])
@pytest.mark.parametrize("n_papers", [0, 1, 3, 12])
def test_blend_matches_the_numpy_implementation(with_profile, n_papers):
    rng = random.Random(n_papers * 2 + with_profile)
    dim = 16
    profile = [rng.uniform(-1, 1) for _ in range(dim)] if with_profile else None
    papers = [
        {"id": f"p{i}", "title": f"P{i}", "embedding": [rng.uniform(-1, 1) for _ in range(dim)]}
        for i in range(n_papers)
    ]
    weights = {p["id"]: rng.uniform(0.1, 2.0) for p in papers}
    got = taste.blend_taste(profile, weights, papers)
    want = _numpy_blend(profile, weights, papers)
    if want is None:
        assert got is None
    else:
        assert got == pytest.approx(want.tolist(), abs=1e-9)


def test_blend_keeps_what_the_reasons_need():
    loaded: dict = {}
    papers = [{"id": "p1", "title": "One", "embedding": "[3, 4]"}]  # PostgREST's string form
    taste.blend_taste([1.0, 0.0], {"p1": 1.0}, papers, loaded)
    assert loaded["vecs"]["p1"] == pytest.approx([0.6, 0.8])
    assert loaded["titles"] == {"p1": "One"}
    assert loaded["profile_q"] == pytest.approx([1.0, 0.0])
    assert loaded["engagement_q"] == pytest.approx([0.6, 0.8])
