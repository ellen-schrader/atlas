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
