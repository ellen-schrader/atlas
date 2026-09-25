"""Offline tests for the metadata backfill's selection and patch rules."""

from __future__ import annotations

from api.backfill_metadata import needs_backfill, plan_update
from paper_radar.ingest.metadata import PaperMetadata


def _meta(**kw) -> PaperMetadata:
    base = {
        "url": "https://www.biorxiv.org/content/10.1101/2026.05.11.724388v1",
        "title": "A preprint",
        "authors": ["Ada Lovelace"],
        "venue": "bioRxiv",
        "year": 2026,
        "doi": "10.1101/2026.05.11.724388",
        "source": "crossref",
    }
    return PaperMetadata(**{**base, **kw})


# --- which rows the backfill claims -----------------------------------------


def test_untitled_rows_are_claimed():
    assert needs_backfill({"id": "p1", "title": None, "doi": None})
    assert needs_backfill({"id": "p1", "title": "   ", "doi": "10.1038/x"})


def test_rendition_dois_are_claimed_even_when_titled():
    # The damage this fixes: a titled row can still hold a dedup key that no
    # later post of the same preprint can ever match.
    for doi in (
        "10.1101/2026.05.11.724388v1",
        "10.1101/2026.05.11.724388v2.full",
        "10.64898/2026.09.20.753045v1.full.pdf",
        "10.64898/2026.09.20.753045v1.supplementary-material",
        "10.1101/070805v1",
    ):
        assert needs_backfill({"id": "p1", "title": "A preprint", "doi": doi}), doi


def test_healthy_rows_are_left_alone():
    assert not needs_backfill({"id": "p1", "title": "A paper", "doi": "10.1101/2026.05.11.724388"})
    assert not needs_backfill({"id": "p1", "title": "A paper", "doi": None})
    # A non-preprint registrant is out of scope: a trailing "v<n>" is only
    # meaningless on bioRxiv/medRxiv, and truncating a real DOI would be worse
    # than the problem being fixed.
    assert not needs_backfill({"id": "p1", "title": "A paper", "doi": "10.1016/j.cell.2025.v1"})


# --- what gets written -------------------------------------------------------


def test_patch_fixes_a_rendition_doi_without_touching_a_good_title():
    row = {"id": "p1", "title": "A preprint", "doi": "10.1101/2026.05.11.724388v1"}
    patch, note = plan_update(row, _meta(), doi_owner=None)
    assert note is None
    assert patch["doi"] == "10.1101/2026.05.11.724388"
    assert "title" not in patch  # unchanged, so not rewritten
    # Only a *new* title makes the row newly embeddable; a DOI fix does not.
    assert "embedded_at" not in patch and "enriched_at" not in patch


def test_patch_on_an_untitled_row_queues_it_for_embed_and_enrich():
    row = {"id": "p1", "title": None, "doi": "10.1101/2026.05.11.724388v1"}
    patch, note = plan_update(row, _meta(), doi_owner=None)
    assert note is None
    assert patch["title"] == "A preprint"
    assert patch["authors"] == ["Ada Lovelace"]
    assert patch["metadata_source"] == "crossref"
    assert patch["embedded_at"] is None and patch["enriched_at"] is None


def test_unresolved_row_is_reported_and_never_written():
    row = {"id": "p1", "title": None, "doi": None}
    patch, note = plan_update(row, _meta(title=None), doi_owner=None)
    assert patch == {}
    assert note == "unresolved"


def test_empty_resolver_fields_never_blank_existing_data():
    # authors/keywords are NOT NULL jsonb and venue/year may already be right;
    # the resolver returning nothing for them is not a reason to overwrite.
    row = {"id": "p1", "title": None, "doi": None}
    patch, _ = plan_update(
        row, _meta(authors=[], keywords=[], venue=None, year=None), doi_owner=None
    )
    assert "authors" not in patch and "keywords" not in patch
    assert "venue" not in patch and "year" not in patch


def test_doi_collision_keeps_the_metadata_but_drops_the_doi():
    # Two rows, one paper. papers.doi is UNIQUE, so writing the resolved DOI
    # would fail; merging means moving paper_posts/reactions/comments, which is
    # a human's call. Fill everything else and report the pair.
    row = {"id": "p1", "title": None, "doi": "10.1101/2026.05.11.724388v1"}
    patch, note = plan_update(row, _meta(), doi_owner="p2")
    assert note == "duplicate of p2"
    assert "doi" not in patch
    assert patch["title"] == "A preprint"


def test_row_that_already_matches_produces_no_patch():
    # Every compared field is selected by _fetch_candidates, so a row the
    # resolver agrees with is a no-op rather than a rewrite of identical values.
    row = {
        "id": "p1",
        "title": "A preprint",
        "doi": "10.1101/2026.05.11.724388",
        "venue": "bioRxiv",
        "year": 2026,
        "abstract": None,
        "metadata_source": "crossref",
    }
    patch, note = plan_update(row, _meta(authors=[], keywords=[]), doi_owner=None)
    assert patch == {} and note is None
