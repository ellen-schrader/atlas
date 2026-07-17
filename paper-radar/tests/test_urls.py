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
