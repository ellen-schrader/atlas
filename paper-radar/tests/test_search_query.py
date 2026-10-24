"""Saved-search queries: PubMed syntax parsed once, run on arXiv and preprints."""

from __future__ import annotations

import pytest

from paper_radar.search.query import Doc, QueryError, matches, parse, to_arxiv, without_filters


def _arxiv(query: str) -> str | None:
    node = without_filters(parse(query))
    return to_arxiv(node) if node else None


def _hits(query: str, title: str, abstract: str = "", authors: str = "") -> bool:
    node = without_filters(parse(query))
    assert node is not None
    return matches(node, Doc(title, abstract, authors))


def test_adjacent_terms_mean_and_like_pubmed():
    assert _arxiv("tertiary lymphoid") == "(all:tertiary AND all:lymphoid)"


def test_operators_parentheses_and_field_tags():
    assert _arxiv('("tertiary lymphoid structure"[tiab] OR TLS) AND smith[au]') == (
        '(((ti:"tertiary lymphoid structure" OR abs:"tertiary lymphoid structure") '
        "OR all:tls) AND au:smith)"
    )
    assert _arxiv("cancer NOT mouse[ti]") == "(all:cancer ANDNOT ti:mouse)"


def test_operators_apply_left_to_right_like_pubmed():
    # PubMed has no precedence: the same string must mean the same everywhere.
    assert _arxiv("immunotherapy OR checkpoint AND melanoma") == (
        "((all:immunotherapy OR all:checkpoint) AND all:melanoma)"
    )
    assert not _hits("immunotherapy OR checkpoint AND melanoma", "Immunotherapy in lung cancer")


def test_a_tag_may_follow_a_space():
    assert _arxiv("tertiary lymphoid structure [tiab] AND smith [au]") == (
        "(((all:tertiary AND all:lymphoid) AND (ti:structure OR abs:structure)) AND au:smith)"
    )
    with pytest.raises(QueryError, match="must follow"):
        parse("[tiab] cancer")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("TLS NOT review[pt]", "all:tls"),
        ("(TLS OR english[la]) AND cancer", "(all:tls AND all:cancer)"),
        ("review[pt] NOT TLS", None),  # only a filter is left: nothing to run
        ("Nature[ta]", None),
    ],
)
def test_pubmed_filters_are_left_out_off_pubmed(query, expected):
    # "NOT review[pt]" must not drop every preprint that says "review".
    assert _arxiv(query) == expected


def test_mesh_searches_everything():
    assert _arxiv("Neoplasms[mh]") == "all:neoplasms"


@pytest.mark.parametrize(
    "query",
    ["", "   ", "(cancer", "cancer)", "cancer OR", "AND cancer", "NOT cancer", "cancer [tiab"],
)
def test_bad_queries_say_what_is_wrong(query):
    with pytest.raises(QueryError):
        parse(query)


def test_too_many_terms():
    with pytest.raises(QueryError, match="more than"):
        parse(" OR ".join(f"t{i}" for i in range(61)))


def test_matching_is_case_insensitive_and_takes_plurals():
    assert _hits("tertiary lymphoid structure", "Tertiary Lymphoid Structures in breast cancer")
    assert not _hits("tertiary lymphoid structure", "Lymphoid tissue in the tertiary period")
    assert not _hits("TLS", "Atlas of cells")  # whole words only


def test_phrases_are_contiguous_and_cross_hyphens():
    assert _hits('"deep learning"', "A deep-learning model for histology")
    assert not _hits('"deep learning"', "Deep phenotyping and machine learning")


def test_truncation():
    assert _hits("immunotherap*", "Immunotherapy response in TNBC")
    assert not _hits("immunotherap", "Immunotherapy response in TNBC")


def test_fields_choose_where_to_look():
    assert _hits("smith[au]", "Unrelated", "", "Smith, J.; Doe, A.")
    assert not _hits("smith[au]", "Smith's lemma revisited")
    assert _hits("cohort[ti]", "A cohort study") and not _hits("cohort[ti]", "X", "a cohort")
    assert _hits("cohort[tiab]", "X", "a cohort")


def test_not_and_or():
    q = "(B cell OR T cell) NOT mouse"
    assert _hits(q, "T cell exhaustion in human tumours")
    assert not _hits(q, "T cell exhaustion in mouse tumours")
