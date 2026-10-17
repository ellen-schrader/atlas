"""Offline tests for the daily preprint check and merge suggestions."""

from __future__ import annotations

import types

from api import preprint_watch
from api.merge_suggestions import find_pairs
from paper_radar.ingest.metadata import PaperMetadata


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.eqs, self.ins = db, table, {}, {}

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def in_(self, col, vals):
        self.ins[col] = set(vals)
        return self

    def upsert(self, rows, **kw):
        self.db.upserts.append((self.table, rows, kw))
        return self

    def execute(self):
        rows = [
            r
            for r in self.db.tables.get(self.table, [])
            if all(r.get(c) == v for c, v in self.eqs.items())
            and all(r.get(c) in v for c, v in self.ins.items())
        ]
        return types.SimpleNamespace(data=rows)


class _Db:
    def __init__(self, **tables):
        self.tables = tables
        self.upserts: list = []
        self.rpcs: list = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, args):
        self.rpcs.append((name, args))
        return types.SimpleNamespace(execute=lambda: None)


# --- merge suggestions ---------------------------------------------------------


def _paper(pid, title, authors, doi, venue=None, url=None):
    return {"id": pid, "title": title, "authors": authors, "doi": doi, "venue": venue, "url": url}


def test_a_retitled_published_version_is_suggested():
    pre = _paper(
        "p",
        "A spatial atlas of tertiary lymphoid structures in NSCLC",
        ["Ada Lovelace", "Bo Byron"],
        "10.1101/2025.01.01.1",
        "bioRxiv",
    )
    pub = _paper(
        "j",
        "The spatial atlas of tertiary lymphoid structures in NSCLC",
        ["Lovelace A", "Byron B"],
        "10.1038/x",
        "Nature",
    )
    [(a, b, score)] = find_pairs([pre, pub])
    assert (a["id"], b["id"]) == ("p", "j") and score >= 0.85


def test_no_suggestion_without_a_shared_lead_or_last_author():
    pre = _paper("p", "Same title", ["Ada Lovelace", "Bo Byron"], "10.1101/1", "bioRxiv")
    pub = _paper("j", "Same title", ["Cy Curie", "Di Darwin"], "10.1038/x", "Nature")
    assert find_pairs([pre, pub]) == []


def test_no_suggestion_for_a_merely_similar_topic():
    pre = _paper("p", "Spatial atlas of lung cancer", ["Ada Lovelace"], "10.1101/1", "bioRxiv")
    pub = _paper(
        "j", "Single-cell atlas of breast cancer metastasis", ["Ada Lovelace"], "10.1038/x"
    )
    assert find_pairs([pre, pub]) == []


def test_two_preprints_or_two_journal_papers_are_not_paired():
    a = _paper("a", "Same title", ["Ada Lovelace"], "10.1101/1", "bioRxiv")
    b = _paper("b", "Same title", ["Ada Lovelace"], "10.21203/rs.3.rs-1/v1", "Research Square")
    c = _paper("c", "Other", ["Ada Lovelace"], "10.1038/x", "Nature")
    d = _paper("d", "Other", ["Ada Lovelace"], "10.1016/y", "Cell")
    assert find_pairs([a, b, c, d]) == []


def test_only_restricts_to_pairs_with_the_new_paper():
    pre1 = _paper("p1", "Title one", ["Ada Lovelace"], "10.1101/1", "bioRxiv")
    pub1 = _paper("j1", "Title one", ["Ada Lovelace"], "10.1038/1")
    pre2 = _paper("p2", "Title two", ["Bo Byron"], "10.1101/2", "bioRxiv")
    pub2 = _paper("j2", "Title two", ["Bo Byron"], "10.1038/2")
    pairs = find_pairs([pre1, pub1, pre2, pub2], only="j2")
    assert [(a["id"], b["id"]) for a, b, _ in pairs] == [("p2", "j2")]


# --- who hears about a publication ---------------------------------------------


def test_recipients_are_the_poster_and_whoever_saved_or_read_it():
    db = _Db(
        paper_posts=[
            {"paper_id": "p", "team_id": "t1", "posted_by": "ada"},
            {"paper_id": "p", "team_id": "t2", "posted_by": None},  # a Teams PDF import
        ],
        paper_status=[
            {"paper_id": "p", "team_id": "t1", "user_id": "bo", "saved": True, "status": "unread"},
            {"paper_id": "p", "team_id": "t1", "user_id": "cy", "saved": False, "status": "unread"},
            {"paper_id": "p", "team_id": "t2", "user_id": "di", "saved": False, "status": "read"},
            {"paper_id": "p", "team_id": "t2", "user_id": "ex", "saved": True, "status": "read"},
        ],
        team_members=[
            {"team_id": "t1", "user_id": "ada"},
            {"team_id": "t1", "user_id": "bo"},
            {"team_id": "t1", "user_id": "cy"},
            {"team_id": "t2", "user_id": "di"},  # "ex" has left t2
        ],
    )
    assert preprint_watch.recipients(db, "p") == {"t1": {"ada", "bo"}, "t2": {"di"}}


# --- the daily check's decisions -------------------------------------------------

_RECORD = PaperMetadata(
    url="https://doi.org/10.1038/x",
    title="Published title",
    authors=["Ada Lovelace"],
    venue="Nature",
    year=2026,
    doi="10.1038/X",
)


def _watch(monkeypatch, found, record=_RECORD):
    monkeypatch.setattr(preprint_watch, "published_version", lambda doi, url: found)
    monkeypatch.setattr(preprint_watch, "crossref_record", lambda doi: record)
    sent: list = []
    monkeypatch.setattr(
        preprint_watch.teams_integration,
        "notify_preprint_published",
        lambda team_id, **kw: sent.append((team_id, kw)),
    )
    return sent


def _db_with_post():
    return _Db(
        paper_posts=[{"paper_id": "pre", "team_id": "t1", "posted_by": "ada"}],
        paper_status=[],
        team_members=[{"team_id": "t1", "user_id": "ada"}],
    )


def test_a_published_version_in_atlas_is_merged_into(monkeypatch):
    sent = _watch(monkeypatch, ("10.1038/x", "crossref"))
    db = _db_with_post()
    row = {"id": "pre", "doi": "10.1101/1", "url": "https://biorxiv.org/x", "venue": "bioRxiv"}
    by_doi = {"10.1038/x": {"id": "pub"}}
    assert preprint_watch.handle_preprint(db, row, by_doi, dry_run=False) == "merge"
    assert db.rpcs == [("merge_papers", {"p_from": "pre", "p_into": "pub", "p_reason": "crossref"})]
    [(table, rows, _kw)] = db.upserts
    assert table == "notifications"
    assert rows == [
        {
            "user_id": "ada",
            "team_id": "t1",
            "paper_id": "pub",
            "kind": "preprint_published",
            "payload": {
                "title": "Published title",
                "venue": "Nature",
                "year": 2026,
                "preprint_venue": "bioRxiv",
            },
        }
    ]
    assert sent[0][0] == "t1" and sent[0][1]["paper_id"] == "pub"


def test_a_published_version_not_in_atlas_is_promoted_in_place(monkeypatch):
    _watch(monkeypatch, ("10.1038/x", "biorxiv"))
    db = _db_with_post()
    row = {"id": "pre", "doi": "10.1101/1", "url": "https://biorxiv.org/x", "venue": "bioRxiv"}
    assert preprint_watch.handle_preprint(db, row, {}, dry_run=False) == "promote"
    [(name, args)] = db.rpcs
    assert name == "promote_to_published" and args["p_paper"] == "pre"
    assert args["p_reason"] == "biorxiv" and args["p_preprint_doi"] is None
    patch = args["p_patch"]
    assert patch["doi"] == "10.1038/x" and patch["url_norm"] == "//doi.org/10.1038/x"
    assert patch["title"] == "Published title" and patch["published_at"] == "2026-01-01"
    assert db.upserts[0][1][0]["paper_id"] == "pre"


def test_an_arxiv_row_holding_its_journal_doi_keeps_arxivs_as_the_alias(monkeypatch):
    _watch(monkeypatch, ("10.1038/x", "arxiv"))
    db = _db_with_post()
    row = {
        "id": "pre",
        "doi": "10.1038/x",
        "url": "https://arxiv.org/abs/1706.03762",
        "venue": "arXiv",
    }
    by_doi = {"10.1038/x": row}
    assert preprint_watch.handle_preprint(db, row, by_doi, dry_run=False) == "promote"
    assert db.rpcs[0][1]["p_preprint_doi"] == "10.48550/arxiv.1706.03762"


def test_dry_run_writes_nothing(monkeypatch):
    sent = _watch(monkeypatch, ("10.1038/x", "crossref"))
    db = _db_with_post()
    row = {"id": "pre", "doi": "10.1101/1", "url": "u", "venue": "bioRxiv"}
    assert preprint_watch.handle_preprint(db, row, {}, dry_run=True) == "promote"
    assert db.rpcs == [] and db.upserts == [] and sent == []


def test_nothing_happens_until_crossref_has_the_published_record(monkeypatch):
    _watch(monkeypatch, ("10.1038/x", "biorxiv"), record=None)
    db = _db_with_post()
    row = {"id": "pre", "doi": "10.1101/1", "url": "u", "venue": "bioRxiv"}
    assert preprint_watch.handle_preprint(db, row, {}, dry_run=False) is None
    assert db.rpcs == []


def test_an_unpublished_preprint_is_left_alone(monkeypatch):
    _watch(monkeypatch, None)
    db = _db_with_post()
    assert (
        preprint_watch.handle_preprint(db, {"id": "pre", "doi": "10.1101/1"}, {}, dry_run=False)
        is None
    )
    assert db.rpcs == [] and db.upserts == []
