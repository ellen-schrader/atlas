"""Offline tests for paper lookups by alias and for recording preprint versions."""

from __future__ import annotations

import types

import pytest

from api import paper_identity
from api.paper_identity import PreprintRef, find_paper, link_preprints, swap_to_published
from paper_radar.ingest.metadata import PaperMetadata


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def limit(self, *_a):
        return self

    def insert(self, row):
        self.db.inserted.append((self.table, row))
        return self

    def execute(self):
        rows = [
            r
            for r in self.db.tables.get(self.table, [])
            if all(r.get(c) == v for c, v in self.filters.items())
        ]
        return types.SimpleNamespace(data=rows[:1])


class _Db:
    def __init__(self, **tables):
        self.tables = tables
        self.inserted: list = []
        self.merged: list = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, args):
        self.merged.append((name, args))
        return types.SimpleNamespace(execute=lambda: None)


def test_find_paper_falls_back_to_an_alias():
    db = _Db(
        papers=[{"id": "pub", "url_norm": "//doi.org/10.1038/x", "doi": "10.1038/x"}],
        paper_aliases=[{"paper_id": "pub", "doi": "10.1101/2025.01.01.1", "url_norm": "biorxiv/1"}],
    )
    assert find_paper(db, "//doi.org/10.1038/x", None)["id"] == "pub"
    assert find_paper(db, "nowhere", "10.1101/2025.01.01.1")["id"] == "pub"
    assert find_paper(db, "biorxiv/1", None)["id"] == "pub"
    assert find_paper(db, "nowhere", "10.9/none") is None


def test_a_preprint_atlas_holds_is_merged_into_the_published_paper():
    db = _Db(papers=[{"id": "pre", "doi": "10.1101/2025.01.01.1", "url_norm": "x"}])
    link_preprints(db, "pub", [PreprintRef("10.1101/2025.01.01.1", None, "bioRxiv", "crossref")])
    assert db.merged == [
        ("merge_papers", {"p_from": "pre", "p_into": "pub", "p_reason": "crossref"})
    ]
    assert db.inserted == []


def test_a_preprint_atlas_does_not_hold_is_recorded_as_an_alias():
    db = _Db()
    url = "https://www.biorxiv.org/content/10.1101/2025.01.01.1v2"
    link_preprints(db, "pub", [PreprintRef("10.1101/2025.01.01.1", url, "bioRxiv", "biorxiv")])
    assert db.merged == []
    [(table, row)] = db.inserted
    assert table == "paper_aliases"
    assert row["paper_id"] == "pub" and row["kind"] == "preprint" and row["reason"] == "biorxiv"
    assert row["doi"] == "10.1101/2025.01.01.1" and row["url"] == url and row["url_norm"]


def test_a_preprint_already_recorded_is_not_recorded_twice():
    db = _Db(paper_aliases=[{"paper_id": "pub", "doi": "10.1101/2025.01.01.1"}])
    link_preprints(db, "pub", [PreprintRef("10.1101/2025.01.01.1", None, None, "crossref")])
    assert db.inserted == [] and db.merged == []


def test_linking_never_raises():
    class _Broken:
        def table(self, name):
            raise RuntimeError("db down")

    link_preprints(_Broken(), "pub", [PreprintRef("10.1101/1", None, None, "crossref")])


def test_swap_to_published(monkeypatch):
    preprint = PaperMetadata(
        url="https://www.biorxiv.org/content/10.1101/2025.01.01.1v1",
        title="Preprint",
        venue="bioRxiv",
        doi="10.1101/2025.01.01.1",
        is_preprint=True,
        published_doi="10.1038/x",
        source="crossref",
    )
    published = PaperMetadata(url="https://doi.org/10.1038/x", title="Published", doi="10.1038/x")
    monkeypatch.setattr(paper_identity, "published_record", lambda m: (published, "crossref"))
    meta, url, ref = swap_to_published(preprint, preprint.url)
    assert meta is published and url == "https://doi.org/10.1038/x"
    assert ref == PreprintRef("10.1101/2025.01.01.1", preprint.url, "bioRxiv", "crossref")

    monkeypatch.setattr(paper_identity, "published_record", lambda m: None)
    assert swap_to_published(preprint, preprint.url) == (preprint, preprint.url, None)


@pytest.mark.parametrize(
    ("posted_as", "expected"),
    [
        ({}, None),
        (
            {
                "doi": "10.1101/1",
                "url": "https://biorxiv.org/x",
                "venue": "bioRxiv",
                "reason": "crossref",
            },
            PreprintRef("10.1101/1", "https://biorxiv.org/x", "bioRxiv", "crossref"),
        ),
    ],
)
def test_posts_with_fields_record_the_replaced_preprint(monkeypatch, posted_as, expected):
    from fastapi.testclient import TestClient

    import api.app as app_mod

    seen: dict = {}
    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    monkeypatch.setattr(
        app_mod,
        "_upsert_paper",
        lambda meta, url, url_norm, preprints=(): (
            seen.update(preprints=list(preprints)),
            ("paper-1", False),
        )[1],
    )
    monkeypatch.setattr(app_mod, "_create_post", lambda *_a, **_k: ("post-1", False, "web"))
    body = {
        "url": "https://doi.org/10.1038/x",
        "team_id": "t",
        "fields": {"title": "Published", "source": "crossref"},
    }
    if posted_as:
        body["replaced_preprint"] = posted_as
    resp = TestClient(app_mod.app).post("/posts", json=body, headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200, resp.text
    assert seen["preprints"] == ([expected] if expected else [])


def test_posts_refuse_a_script_link_as_the_preprint(monkeypatch):
    from fastapi.testclient import TestClient

    import api.app as app_mod

    monkeypatch.setattr(app_mod, "_require_member", lambda _t, _team: "user-1")
    resp = TestClient(app_mod.app).post(
        "/posts",
        json={
            "url": "https://doi.org/10.1038/x",
            "team_id": "t",
            "fields": {"title": "Published", "source": "crossref"},
            "replaced_preprint": {"url": "javascript:alert(1)", "reason": "crossref"},
        },
        headers={"Authorization": "Bearer t"},
    )
    assert resp.status_code == 400
