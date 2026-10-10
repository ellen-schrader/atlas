"""Offline tests for the tag-merge proposal script (no database, no Anthropic)."""

from __future__ import annotations

from collections import Counter

from api.propose_tag_merges import _Merge, collect_tags, render, validate


class _Svc:
    """Stands in for the service client: one page per table."""

    def __init__(self, data):
        self.data = data

    def table(self, name):
        rows = self.data[name]

        class _Q:
            def select(self, column):
                return self

            def range(self, a, b):
                return self

            def execute(self):
                return type("R", (), {"data": rows})()

        return _Q()


def test_collect_tags_normalises_and_counts_rows_once():
    svc = _Svc(
        {
            "papers": [{"tags": ["Deep Learning", "deep-learning", "TME"]}, {"tags": None}],
            "paper_posts": [{"tags": ["tme", ""]}],
        }
    )
    assert collect_tags(svc) == Counter({"deep-learning": 1, "tme": 2})


def test_validate_drops_unsafe_merges():
    counts = Counter({"tumor-microenvironment": 9, "tme": 3, "tumour-microenvironment": 2, "a": 1})
    merges = [
        _Merge(canonical="Tumor Microenvironment", aliases=["TME", "tumour-microenvironment", "made-up"], reason="r"),
        # "tme" is already claimed; "a" -> chain into a kept tag is refused below.
        _Merge(canonical="other", aliases=["tme"], reason="r"),
        _Merge(canonical="a", aliases=["tumor-microenvironment"], reason="chain"),
    ]
    out = validate(merges, counts)
    assert [(m.canonical, m.aliases) for m in out] == [
        ("tumor-microenvironment", ["tme", "tumour-microenvironment"])
    ]


def test_render_escapes_quotes_in_sql():
    counts = Counter({"crohns-disease": 4, "crohn's-disease": 1})
    md, sql = render([_Merge(canonical="crohns-disease", aliases=["crohn's-disease"], reason="r")], counts)
    assert "('crohn''s-disease', 'crohns-disease')" in sql
    assert "select * from public.apply_tag_cleanup();" in sql
    assert "| crohns-disease (4) | crohn's-disease (1) | r |" in md
