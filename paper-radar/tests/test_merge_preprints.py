"""Offline tests for the preprint merge script's selection rules."""

from __future__ import annotations

from api.merge_preprints import find_title_pairs, is_preprint_row, plan_case_merges, title_key


def test_preprints_are_recognised_by_doi_venue_or_host():
    assert is_preprint_row({"doi": "10.1101/2025.01.01.000001"})
    assert is_preprint_row({"doi": "10.64898/2026.09.20.753045"})
    assert is_preprint_row({"doi": "10.48550/arXiv.1706.03762"})
    assert is_preprint_row({"doi": None, "venue": "bioRxiv"})
    assert is_preprint_row(
        {"doi": "10.5555/3295222.3295349", "url": "https://arxiv.org/abs/1706.03762"}
    )
    assert not is_preprint_row(
        {"doi": "10.1038/s41586-025-00001-x", "venue": "Nature", "url": "https://www.nature.com/x"}
    )


def test_case_merges_keep_the_lowercase_doi():
    rows = [
        {"id": "old", "doi": "10.1158/2159-8290.CD-25-1745"},
        {"id": "new", "doi": "10.1158/2159-8290.cd-25-1745"},
        {"id": "other", "doi": "10.1038/x"},
    ]
    assert plan_case_merges(rows) == [("old", "new")]


def test_case_merges_keep_the_oldest_when_none_is_lowercase():
    rows = [
        {"id": "old", "doi": "10.1158/ABC"},
        {"id": "new", "doi": "10.1158/Abc"},
        {"id": "untitled", "doi": None},
    ]
    assert plan_case_merges(rows) == [("new", "old")]


def test_title_key_ignores_case_accents_and_punctuation():
    a = {"title": "Single-cell atlas of the Tumour micro-environment.", "authors": ["José García"]}
    b = {"title": "Single cell atlas of the tumour micro environment", "authors": ["J. Garcia"]}
    assert title_key(a) == title_key(b)
    assert title_key({"title": "", "authors": ["A"]}) is None
    assert title_key({"title": "T", "authors": []}) is None


def test_title_pairs_match_a_preprint_to_a_published_paper_only():
    pre = {"id": "p", "doi": "10.1101/1", "title": "Same Title", "authors": ["Ada Lovelace"]}
    pub = {"id": "j", "doi": "10.1038/1", "title": "Same title", "authors": ["A. Lovelace"]}
    other_pre = {"id": "q", "doi": "10.1101/2", "title": "Same title", "authors": ["Ada Lovelace"]}
    stranger = {"id": "s", "doi": "10.1038/2", "title": "Same title", "authors": ["Bo Byron"]}
    pairs = find_title_pairs([pre], [pre, pub, other_pre, stranger])
    assert [(a["id"], b["id"]) for a, b in pairs] == [("p", "j")]


def test_title_key_reads_pubmed_style_names():
    # PubMed and Europe PMC give "Doe J"; Crossref, arXiv and bioRxiv "Jane Doe".
    crossref = {"title": "A title", "authors": ["Jane Doe"]}
    for name in ("Doe J", "Doe JA", "J. Doe", "J Doe"):
        assert title_key({"title": "A title", "authors": [name]}) == title_key(crossref), name


def test_a_failing_merge_does_not_stop_the_run(monkeypatch, capsys):
    import api.merge_preprints as script

    rows = [
        {"id": "a", "doi": "10.1/X", "title": "A", "authors": [], "url": "u1"},
        {"id": "b", "doi": "10.1/x", "title": "B", "authors": [], "url": "u2"},
        {"id": "c", "doi": "10.2/Y", "title": "C", "authors": [], "url": "u3"},
        {"id": "d", "doi": "10.2/y", "title": "D", "authors": [], "url": "u4"},
    ]

    class Rpc:
        def __init__(self, args):
            self.args = args

        def execute(self):
            if self.args["p_from"] == "a":
                raise RuntimeError("boom")

    class Svc:
        merged: list = []

        def rpc(self, name, args):
            Svc.merged.append(args["p_from"])
            return Rpc(args)

    monkeypatch.setattr(script, "service_client", lambda: Svc())
    monkeypatch.setattr(script, "_fetch_papers", lambda svc: rows)
    script.main(["--apply"])
    out = capsys.readouterr().out
    assert Svc.merged == ["a", "c"]
    assert "merge failed" in out
    assert "case-duplicates merged=1" in out and "failed=1" in out


def test_published_but_not_in_atlas_still_gets_a_title_match(monkeypatch, capsys):
    import api.merge_preprints as script

    rows = [
        {"id": "p", "doi": "10.1101/1", "title": "Same", "authors": ["Ada Lovelace"], "url": "u1"},
        # The journal version, posted as a landing page that gave no DOI.
        {"id": "j", "doi": None, "title": "Same", "authors": ["Lovelace A"], "url": "u2"},
    ]
    monkeypatch.setattr(script, "service_client", lambda: object())
    monkeypatch.setattr(script, "_fetch_papers", lambda svc: rows)
    monkeypatch.setattr(
        script, "published_version", lambda doi, url: ("10.1016/j.cell.1", "crossref")
    )
    monkeypatch.setattr(script.time, "sleep", lambda s: None)
    script.main([])
    out = capsys.readouterr().out
    assert "not in Atlas" in out
    assert "title-pairs-to-review=1" in out
