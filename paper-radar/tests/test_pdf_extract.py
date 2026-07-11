"""Smoke test for URL extraction.

Builds a tiny PDF on the fly (so no binary fixture is committed) containing both
a clickable link annotation with an untruncated href and a bare URL in the text,
then checks the extractor recovers both.
"""

from __future__ import annotations

import fitz  # PyMuPDF

from paper_radar.ingest.pdf_extract import _normalize_key, extract_urls_from_pdf

ANNOT_URL = "https://arxiv.org/abs/2306.11207"
TEXT_URL = "https://www.nature.com/articles/s41586-023-06124-2"


def _make_pdf(path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    # Visible text: a bare URL (for the regex path) + a label for the link annot.
    page.insert_text((72, 100), "Shared by Ada Lovelace 3/14/2026 9:41 AM")
    page.insert_text((72, 130), f"Bare link: {TEXT_URL}")
    label_rect = fitz.Rect(72, 150, 300, 170)
    page.insert_text((72, 165), "Clickable (truncated) link…")
    # Link annotation carries the full, untruncated href.
    page.insert_link({"kind": fitz.LINK_URI, "from": label_rect, "uri": ANNOT_URL})
    doc.save(str(path))
    doc.close()


def test_extract_urls_from_pdf(tmp_path):
    pdf_path = tmp_path / "teams_export.pdf"
    _make_pdf(pdf_path)

    result = extract_urls_from_pdf(pdf_path)
    urls = {u.url for u in result.urls}

    assert ANNOT_URL in urls, "should recover the untruncated href from the link annotation"
    assert TEXT_URL in urls, "should recover the bare URL from the page text"

    # The annotation URL should be attributed to the annotation source.
    annot = next(u for u in result.urls if u.url == ANNOT_URL)
    assert annot.via == "annotation"


def test_dedup(tmp_path):
    pdf_path = tmp_path / "teams_export.pdf"
    _make_pdf(pdf_path)
    result = extract_urls_from_pdf(pdf_path)
    assert len({u.url for u in result.urls}) == len(result.urls)


def test_normalize_key_collapses_tracking_and_www():
    base = "https://www.biorxiv.org/content/10.1101/2026.05.11.724388v1"
    # www vs not, trailing slash, and tracking params all collapse to one key.
    assert _normalize_key(base) == _normalize_key(
        "https://biorxiv.org/content/10.1101/2026.05.11.724388v1/"
    )
    assert _normalize_key(base) == _normalize_key(base + "?ct=")
    assert _normalize_key(base) == _normalize_key(base + "?utm_source=x&utm_medium=social")
    assert _normalize_key(
        "https://www.sciencedirect.com/science/article/pii/S123?via%3Dihub"
    ) == _normalize_key("https://www.sciencedirect.com/science/article/pii/S123")


def test_normalize_key_keeps_meaningful_params():
    # openreview ids are not tracking noise -- distinct ids stay distinct.
    a = _normalize_key("https://openreview.net/forum?id=AAA")
    b = _normalize_key("https://openreview.net/forum?id=BBB")
    assert a != b
