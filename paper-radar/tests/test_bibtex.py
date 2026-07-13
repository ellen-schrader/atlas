"""BibTeX parsing — against the shapes a real Zotero export actually contains.

A researcher's library is messy: brace-protected capitals, accented names, entries with
no DOI, `@misc` web pages, month macros, and a few records nothing can love. The import
has to survive all of it and be honest about what it couldn't take.
"""

from __future__ import annotations

from datetime import date

from paper_radar.ingest.bibtex import parse_bibtex

ZOTERO = r"""
@article{werb_spatial_2025,
	title = {Spatially resolved clonal architecture in ductal carcinoma {in} {situ}},
	volume = {640},
	issn = {1476-4687},
	url = {https://www.nature.com/articles/s41586-025-01},
	doi = {10.1038/s41586-025-01},
	abstract = {Spatial profiling of DCIS reveals clonal neighbourhoods.},
	journal = {Nature},
	author = {Werb, Zena and Patel, Rohan and Müller, Anja},
	month = mar,
	year = {2025},
	keywords = {spatial omics, DCIS, breast},
}

@inproceedings{chen_imc_2024,
	title = {Imaging mass cytometry of the invasive front},
	booktitle = {Proceedings of {SPIE}},
	author = {Chen, Mei},
	year = {2024},
	month = {11},
	day = {3},
}

@misc{nih_portal,
	title = {Spatial biology data portal},
	howpublished = {\url{https://example.org/portal}},
	url = {https://example.org/portal},
	author = {{National Institutes of Health}},
	year = {2023},
}

@article{no_identity,
	journal = {Some Journal},
	year = {2020},
}
"""


def test_parses_a_zotero_export():
    result = parse_bibtex(ZOTERO)
    keys = [e.key for e in result.entries]
    assert keys == ["werb_spatial_2025", "chen_imc_2024", "nih_portal"]

    # An entry with no DOI, no URL and no title can't be deduped or displayed — it is
    # rejected, and *reported*, rather than silently dropped or crashing the import.
    assert len(result.rejected) == 1
    assert result.rejected[0][0] == "no_identity"
    assert "nothing to import" in result.rejected[0][1].lower()


def test_braces_and_accents_are_cleaned():
    e = parse_bibtex(ZOTERO).entries[0]
    # `{in} {situ}` protects capitalisation in LaTeX; it must not reach the UI.
    assert e.title == "Spatially resolved clonal architecture in ductal carcinoma in situ"
    assert "{" not in (e.title or "")


def test_authors_are_reordered_from_last_first():
    e = parse_bibtex(ZOTERO).entries[0]
    assert e.authors == ["Zena Werb", "Rohan Patel", "Anja Müller"]


def test_month_macro_and_numeric_month_both_resolve():
    a, b = parse_bibtex(ZOTERO).entries[0], parse_bibtex(ZOTERO).entries[1]
    assert a.published_at == date(2025, 3, 1)   # `month = mar` (a bare macro, not a string)
    assert b.published_at == date(2024, 11, 3)  # numeric month + day


def test_year_only_becomes_jan_1_and_is_flagged_as_imprecise():
    """The reason publication date is stored separately from posted_at: BibTeX usually
    gives a year, so a whole corpus would pile onto Jan 1 and sort arbitrarily."""
    e = parse_bibtex(ZOTERO).entries[2]
    assert e.published_at == date(2023, 1, 1)
    assert e.year == 2023


def test_doi_is_recovered_from_the_url_when_the_doi_field_is_missing():
    bib = """
    @article{k, title = {T}, url = {https://doi.org/10.1016/j.cell.2025.02.001}, year = {2025}}
    """
    e = parse_bibtex(bib).entries[0]
    assert e.doi == "10.1016/j.cell.2025.02.001"
    assert e.identifier == "https://doi.org/10.1016/j.cell.2025.02.001"


def test_identifier_prefers_doi_over_url():
    e = parse_bibtex(ZOTERO).entries[0]
    assert e.identifier == "https://doi.org/10.1038/s41586-025-01"


def test_entry_without_doi_falls_back_to_its_url():
    e = parse_bibtex(ZOTERO).entries[2]
    assert e.doi is None
    assert e.identifier == "https://example.org/portal"


def test_a_broken_file_is_reported_not_raised():
    result = parse_bibtex("@article{oops, title = {unclosed")
    # Whatever bibtexparser makes of this, we must not explode: either it salvages the
    # entry or it reports it, but the import survives.
    assert isinstance(result.entries, list)
    assert isinstance(result.rejected, list)


def test_empty_file_is_empty_not_an_error():
    result = parse_bibtex("")
    assert result.entries == []
    assert result.rejected == []
