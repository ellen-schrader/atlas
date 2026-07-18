"""Tests for the shared URL helpers (extraction from message text, skip-hosts)."""

from __future__ import annotations

from paper_radar.ingest.urls import (
    _normalize_key,
    extract_urls_from_text,
    is_skip_host,
)


def test_extract_plain_and_deduped_in_order():
    text = "look at https://arxiv.org/abs/2401.01234 and again https://arxiv.org/abs/2401.01234"
    assert extract_urls_from_text(text) == ["https://arxiv.org/abs/2401.01234"]


def test_extract_strips_mention_markup_and_entities():
    # Teams messages carry <at> mention tags and HTML-escaped ampersands.
    text = "<at>Atlas</at> https://nature.com/articles/x?a=1&amp;b=2 <br>"
    assert extract_urls_from_text(text) == ["https://nature.com/articles/x?a=1&b=2"]


def test_extract_url_from_titled_anchor_href():
    # A pasted link becomes <a href="URL">Page Title</a>; the URL is only in the
    # href, so tag-stripping alone would lose it (the reported "no paper link" bug).
    text = (
        '<at id="0">Atlas</at> '
        '<a href="https://pubmed.ncbi.nlm.nih.gov/38976543/">'
        "Spatial Proximity Sequencing … - PubMed</a>"
    )
    assert extract_urls_from_text(text) == ["https://pubmed.ncbi.nlm.nih.gov/38976543/"]


def test_extract_anchor_href_variants_and_dedup():
    # Quoted, unquoted, and a duplicate bare copy all collapse to one URL.
    assert extract_urls_from_text("<a href=https://doi.org/10.1/x>t</a>") == [
        "https://doi.org/10.1/x"
    ]
    both = '<a href="https://arxiv.org/abs/1">t</a> also https://arxiv.org/abs/1'
    assert extract_urls_from_text(both) == ["https://arxiv.org/abs/1"]


def test_extract_anchor_href_unescapes_entities_in_query():
    # The whole point of unescaping before href extraction: an &amp; in the href's
    # query must yield the full URL, not one truncated at the first entity.
    text = '<a href="https://www.nature.com/articles/x?a=1&amp;b=2">Title</a>'
    assert extract_urls_from_text(text) == ["https://www.nature.com/articles/x?a=1&b=2"]


def test_extract_trims_trailing_prose_punctuation():
    assert extract_urls_from_text("see (https://arxiv.org/abs/1.2).") == [
        "https://arxiv.org/abs/1.2"
    ]


def test_extract_unwraps_outlook_safelinks():
    wrapped = (
        "https://eu-west.safelinks.protection.outlook.com/?url="
        "https%3A%2F%2Fdoi.org%2F10.1038%2Fx&data=abc"
    )
    assert extract_urls_from_text(f"paper: {wrapped}") == ["https://doi.org/10.1038/x"]


def test_extract_none_and_empty():
    assert extract_urls_from_text(None) == []
    assert extract_urls_from_text("no links here") == []


def test_is_skip_host():
    assert is_skip_host("https://github.com/a/b")
    assert is_skip_host("https://teams.microsoft.com/l/x")
    assert is_skip_host("https://www.youtube.com/watch?v=x")
    assert not is_skip_host("https://arxiv.org/abs/1")
    assert not is_skip_host("https://www.nature.com/articles/x")


def test_extracted_safelink_target_normalizes_like_a_direct_share():
    # A paper shared through SafeLinks must dedupe against the same paper shared raw.
    direct = "https://doi.org/10.1038/x"
    wrapped = extract_urls_from_text(
        "https://x.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdoi.org%2F10.1038%2Fx"
    )[0]
    assert _normalize_key(wrapped) == _normalize_key(direct)
