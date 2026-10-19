"""Finding what an extraction's source points at, in a JATS article."""

from __future__ import annotations

import pytest

from paper_radar.trials import jats
from paper_radar.trials.cited import Article

# Shaped like a Nature Medicine article in Europe PMC: sections with
# subsections, a table with row groups, a figure with panels, and Extended Data
# in the back matter.
XML = b"""<article xmlns:xlink="http://www.w3.org/1999/xlink">
<front><article-meta>
  <abstract id="Abs1"><title>Abstract</title><p>Atezolizumab improved EFS.</p></abstract>
</article-meta></front>
<body>
  <sec id="Sec1"><title>Main</title><p>The primary analysis showed a pCR benefit.</p></sec>
  <sec id="Sec2"><title>Results</title>
    <sec id="Sec3"><title>Patient disposition</title>
      <p>333 patients were randomised (Table 1).
        <table-wrap id="Tab1"><label>Table 1</label>
          <caption><p>Baseline characteristics</p></caption>
          <table>
            <thead><tr><th colspan="2" rowspan="2">Characteristic</th><th colspan="2">ITT</th></tr>
                   <tr><th>Atezolizumab</th><th>Placebo</th></tr></thead>
            <tbody>
              <tr><td>Age, years</td><td>&lt;65</td><td>148 (90)</td><td>139 (83)</td></tr>
              <tr><td/><td>&#8805;65</td><td>17 (10)</td><td>29 (17)</td></tr>
              <tr><td>ECOG PS</td><td>0</td><td>157 (95)</td><td>154 (92)</td></tr>
              <tr><td/><td>1</td><td>8 (5)</td><td>14 (8)</td></tr>
            </tbody>
          </table>
          <table-wrap-foot>
            <fn><p>aRoad traffic accident.</p></fn><fn><p>bPneumonia.</p></fn>
          </table-wrap-foot>
        </table-wrap>
      </p>
    </sec>
    <sec id="Sec4"><title>Secondary outcomes</title><p>EFS HR 0.76.</p>
      <fig id="Fig2"><label>Fig. 2</label><caption><p>EFS, DFS and OS.</p></caption>
        <graphic xlink:href="Fig2_HTML.jpg"/></fig>
    </sec>
  </sec>
  <sec id="Sec8"><title>Discussion</title><p>Benefit held.</p></sec>
  <sec id="Sec9"><title>Methods</title><p>Randomised 1:1.</p>
    <sec id="Sec10"><title>Patients and treatment</title><p>Stage II-III TNBC.</p></sec>
  </sec>
</body>
<back><app-group><app><sec id="Sec15"><title>Extended data</title>
  <table-wrap id="Tab4"><label>Extended Data Table 3</label>
    <caption><p>Summary of safety</p></caption>
    <table><tbody><tr><td>Grade 3/4 AE</td><td>103 (63)</td></tr></tbody></table></table-wrap>
</sec></app></app-group></back>
</article>"""


class _Article(Article):
    def cite_one(self, part):
        (citation,) = self.cite(part)
        return citation


@pytest.fixture
def article():
    return _Article(XML)


def test_a_table_and_the_rows_its_note_names(article):
    c = article.cite_one("Table 1 (ECOG PS)")
    assert c.element.id == "Tab1"
    assert c.element.caption == "Baseline characteristics"
    assert [r[0].text for r in c.element.rows][:3] == [
        "Characteristic",
        "Atezolizumab",
        "Age, years",
    ]
    assert c.element.rows[0][0].header and c.element.rows[0][0].colspan == 2
    assert c.rows == [4, 5]  # "ECOG PS" and its category row under it
    assert article.cite_one("Table 1 (Age)").rows == [2, 3]
    assert article.cite_one("Table 1").rows == []


def test_footnotes_stay_apart(article):
    assert article.cite_one("Table 1").element.footnotes == [
        "aRoad traffic accident.",
        "bPneumonia.",
    ]


def test_tables_and_figures_by_label_however_written(article):
    assert article.cite_one("Extended Data Table 3").element.id == "Tab4"
    fig = article.cite_one("Fig. 2d")
    assert (fig.element.id, fig.panel) == ("Fig2", "d")
    assert fig.element.image is None  # no PMC id, so no PMC address
    assert article.cite_one("Figure 2").element.id == "Fig2"
    # Extended Data Table 3 isn't Table 3, and a missing label matches nothing.
    assert article.cite_one("Table 3").element is None
    assert article.cite_one("Extended Data Table 1").element is None


def test_sections_and_their_subsections(article):
    c = article.cite_one("Results (Patient disposition)")
    assert (c.element.kind, c.element.id) == ("section", "Sec3")
    # The table inside the paragraph is an element of its own.
    assert c.element.paragraphs == ["333 patients were randomised (Table 1)."]
    results = article.cite_one("Results").element
    assert results.paragraphs[0] == "## Patient disposition"
    # A note that isn't a subsection is Claude's comment: the section itself.
    assert article.cite_one("Main (introduction, citing primary analysis)").element.id == "Sec1"
    assert article.cite_one("Discussion for definition").element.id == "Sec8"
    assert article.cite_one("Methods (Patients and treatment)").element.id == "Sec10"
    assert article.cite_one("Abstract").element.paragraphs == ["Atezolizumab improved EFS."]
    assert article.cite_one("Conclusions").element is None


def test_notes_however_bracketed(article):
    assert article.cite_one("Table 1(ECOG PS)").rows == [4, 5]
    assert article.cite_one("Table 1 (Age, n (%))").rows == [2, 3]


def test_a_label_spanning_its_category_rows():
    xml = XML.replace(b"<td>ECOG PS</td>", b'<td rowspan="2">ECOG PS</td>').replace(
        b"<tr><td/><td>1</td>", b"<tr><td>1</td>"
    )
    c = _Article(xml).cite_one("Table 1 (ECOG PS)")
    assert c.rows == [4, 5]
    assert [cell.text for cell in c.element.rows[5]][:2] == ["1", "8 (5)"]


def test_every_table_and_figure_a_part_names(article):
    cites = article.cite("Table 1 (Age), Fig. 2b and Extended Data Table 3")
    assert [(c.part, c.element.id) for c in cites] == [
        ("Table 1 (Age)", "Tab1"),
        ("Fig. 2b", "Fig2"),
        ("Extended Data Table 3", "Tab4"),
    ]
    assert cites[0].rows == [2, 3]
    # A plural label lists more numbers: each is looked up, missing ones too.
    assert [(c.part, c.element and c.element.id) for c in article.cite("Tables 1 and 3")] == [
        ("Table 1", "Tab1"),
        ("Table 3", None),
    ]


def test_a_figures_image_on_pmc():
    with_id = XML.replace(
        b"<article-meta>", b'<article-meta><article-id pub-id-type="pmcid">PMC123</article-id>'
    )
    fig = _Article(with_id).cite_one("Fig. 2")
    assert (
        fig.element.image == "https://pmc.ncbi.nlm.nih.gov/articles/instance/123/bin/Fig2_HTML.jpg"
    )
    # JATS may leave off the extension; a path is never followed.
    bare = with_id.replace(b'"Fig2_HTML.jpg"', b'"Fig2_HTML"')
    assert _Article(bare).cite_one("Fig. 2").element.image.endswith("/bin/Fig2_HTML.jpg")
    tif = with_id.replace(b'"Fig2_HTML.jpg"', b'"Fig2_HTML.tif"')
    assert _Article(tif).cite_one("Fig. 2").element.image.endswith("/bin/Fig2_HTML.jpg")
    for bad in (b'"../../x.jpg"', b'"Fig2.jpg&#10;"', b'".hidden.jpg"'):
        odd = with_id.replace(b'"Fig2_HTML.jpg"', bad)
        assert _Article(odd).cite_one("Fig. 2").element.image is None, bad


def test_a_figures_full_image_not_its_thumbnail():
    xml = XML.replace(
        b"<article-meta>", b'<article-meta><article-id pub-id-type="pmcid">PMC123</article-id>'
    ).replace(
        b'<graphic xlink:href="Fig2_HTML.jpg"/>',
        b'<alternatives><graphic content-type="thumb" xlink:href="Fig2_thumb.gif"/>'
        b'<graphic content-type="image" xlink:href="Fig2_HTML.jpg"/></alternatives>',
    )
    assert _Article(xml).cite_one("Fig. 2").element.image.endswith("/bin/Fig2_HTML.jpg")


def test_the_anchored_element_comes_first(article):
    # Named by the part as well: that citation (with its rows) moves first.
    cites = article.cite_all("Results (Patient disposition); Table 1 (Age)", "Tab1")
    assert [c.element.id for c in cites] == ["Tab1", "Sec3"]
    assert cites[0].rows == [2, 3]
    # Named only by the anchor: added first.
    cites = article.cite_all("Methods", "Fig2")
    assert [(c.part, c.element.id) for c in cites] == [("Fig. 2", "Fig2"), ("Methods", "Sec9")]
    assert [c.element.id for c in article.cite_all("", "Sec4")] == ["Sec4"]
    # An anchor the article doesn't have, or that names something else, is ignored.
    assert [c.element.id for c in article.cite_all("Methods", "nope")] == ["Sec9"]


def test_every_part_of_a_source_once(article):
    cites = article.cite_all(
        "Results (Secondary outcomes); Fig. 2a; Extended Data Table 3; Fig. 2a"
    )
    assert [c.element.id for c in cites] == ["Sec4", "Fig2", "Tab4"]


def test_refuses_entities_and_junk():
    with pytest.raises(jats.NotJats):
        Article(b'<!DOCTYPE a [<!ENTITY x "xx">]><article/>')
    with pytest.raises(jats.NotJats):
        Article(b"%PDF-1.7")


# --- the API ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import api.trials as trials_api  # noqa: E402
from api.app import app  # noqa: E402

client = TestClient(app)
AUTH = {"Authorization": "Bearer t"}
PMC_XML = XML.replace(
    b"<article-meta>", b'<article-meta><article-id pub-id-type="pmcid">PMC123</article-id>'
)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __getattr__(self, _a):
        return lambda *a, **k: self

    def execute(self):
        return SimpleNamespace(data=self.rows)


def _source(monkeypatch, media_type="application/xml", data=PMC_XML):
    monkeypatch.setattr(trials_api, "_require_lab_trial", lambda *_a: "u1")
    row = {"storage_path": "lab/t1/PMC123.xml", "media_type": media_type}
    monkeypatch.setattr(
        trials_api, "user_client", lambda _t: SimpleNamespace(table=lambda _n: _Rows([row]))
    )
    bucket = SimpleNamespace(download=lambda path: data)
    monkeypatch.setattr(
        trials_api,
        "service_client",
        lambda: SimpleNamespace(storage=SimpleNamespace(from_=lambda _b: bucket)),
    )


def test_cited_endpoint_returns_each_part_and_the_pmc_page(monkeypatch):
    _source(monkeypatch)
    r = client.get(
        "/trials/t1/sources/s1/cited",
        params={"team_id": "lab", "where": "Results (Patient disposition); Table 1 (ECOG PS)"},
        headers=AUTH,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["article_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"
    section, table = body["parts"]
    assert section["element"]["id"] == "Sec3"
    assert table["element"]["kind"] == "table"
    assert table["rows"] == [4, 5]
    assert table["element"]["rows"][0][0] == {
        "text": "Characteristic",
        "header": True,
        "colspan": 2,
        "rowspan": 2,
    }


def test_cited_endpoint_only_reads_full_text_files(monkeypatch):
    _source(monkeypatch, media_type="application/pdf")
    r = client.get(
        "/trials/t1/sources/s1/cited", params={"team_id": "lab", "where": "Table 1"}, headers=AUTH
    )
    assert r.status_code == 404


def test_cited_endpoint_refuses_a_file_that_isnt_an_article(monkeypatch):
    _source(monkeypatch, data=b'<!DOCTYPE a [<!ENTITY x "xx">]><article/>')
    r = client.get(
        "/trials/t1/sources/s1/cited", params={"team_id": "lab", "where": "Table 1"}, headers=AUTH
    )
    assert r.status_code == 415


def test_cited_endpoint_404s_when_the_file_is_gone(monkeypatch):
    _source(monkeypatch)

    def gone(_path):
        raise RuntimeError("Object not found")

    bucket = SimpleNamespace(download=gone)
    monkeypatch.setattr(
        trials_api,
        "service_client",
        lambda: SimpleNamespace(storage=SimpleNamespace(from_=lambda _b: bucket)),
    )
    r = client.get(
        "/trials/t1/sources/s1/cited", params={"team_id": "lab", "where": "Table 1"}, headers=AUTH
    )
    assert r.status_code == 404


# --- finding a source's quote -------------------------------------------------------------


def test_a_quoted_table_row_however_its_cells_are_separated(article):
    (c,) = article.cite_all("Table 1 (ECOG PS)", quote="ECOG PS | 0 | 157 (95)")
    assert (c.quote.where, c.quote.index) == ("row", 4)
    (c,) = article.cite_all("Table 1", quote="ECOG PS 0 157 (95)")
    assert c.quote.index == 4


def test_a_quote_isnt_matched_inside_a_longer_number(article):
    (c,) = article.cite_all("Table 1", quote="157 (9")
    assert c.quote is None
    (c,) = article.cite_all("Table 1", quote="57 (95)")
    assert c.quote is None


def test_quotes_from_footnotes_headings_and_with_gaps(article):
    (c,) = article.cite_all("Table 1", quote="bPneumonia.")
    assert (c.quote.where, c.quote.index) == ("footnote", 1)
    (c,) = article.cite_all("Table 1", quote="Table 1 Baseline characteristics")
    assert (c.quote.where, c.quote.start) == ("caption", 0)  # marked in the caption
    (c,) = article.cite_all("Table 1", quote="Table 1")
    assert c.quote.where == "heading"  # only the label: nothing to mark but found
    (c,) = article.cite_all("Results (Patient disposition)", quote="333 patients … (Table 1)")
    assert (c.quote.where, c.quote.start) == ("paragraph", 0)


def test_quotes_with_other_dashes_and_dots():
    xml = XML.replace(b"EFS HR 0.76.", "EFS HR 0.76 (0.61–0.94); P&lt;0·001.".encode())
    (c,) = _Article(xml).cite_all("Results (Secondary outcomes)", quote="0.76 (0.61-0.94); P<0.001")
    para = c.element.paragraphs[0]
    assert para[c.quote.start : c.quote.end] == "0.76 (0.61–0.94); P<0·001"


def test_subsections_written_other_ways(article):
    for where in ("Results, Patient disposition", "Results: Patient disposition"):
        (c,) = article.cite_all(where)
        assert c.element.id == "Sec3", where
    # A comma that isn't a subsection leaves the section as it is.
    (c,) = article.cite_all("Methods, randomisation")
    assert c.element.id == "Sec9"


def test_a_quote_found_where_the_source_didnt_say(article):
    cites = article.cite_all("Table 1", "Tab1", quote="333 patients were randomised")
    assert [c.element.id for c in cites] == ["Tab1", "Sec3"]
    assert cites[0].quote is None and cites[1].quote.where == "paragraph"
    assert cites[1].elsewhere and not cites[0].elsewhere
    assert article.cite_all("Table 1", quote="not in this paper at all")[-1].element.id == "Tab1"


def test_an_anchored_subsection_isnt_shown_twice(article):
    cites = article.cite_all("Results", "Sec3")
    assert [c.element.id for c in cites] == ["Sec3"]
    # Nor a cited subsection of an anchored section.
    assert [c.element.id for c in article.cite_all("Results (Patient disposition)", "Sec2")] == [
        "Sec2"
    ]
    # A table inside a cited section isn't in its text: both stay.
    assert [c.element.id for c in article.cite_all("Results", "Tab1")] == ["Tab1", "Sec2"]


def test_a_source_keeps_a_malformed_anchor_or_long_quote_out_of_the_way():
    from paper_radar.trials.extraction import Source

    s = Source(doc=1, where="Table 1", anchor="[Table id=Tab1] Baseline", quote="x " * 400)
    assert s.anchor == "Tab1"
    assert 290 <= len(s.quote) <= 300 and s.quote.endswith("x")
    assert Source(doc=1, where="x", anchor="no anchor here!").anchor is None
    assert Source(doc=1, where="x", anchor=" Sec3 ", quote="  ").model_dump()["quote"] is None
    # Cut at a word's end: a number cut short would no longer be found.
    long = "a" * 294 + " HR 0.76"  # 300 characters end at "0."
    assert Source(doc=1, where="x", quote=long).quote == "a" * 294 + " HR"


def test_cited_endpoint_says_whether_the_quote_was_found(monkeypatch):
    _source(monkeypatch)
    params = {"team_id": "lab", "where": "Table 1", "anchor": "x" * 200}
    r = client.get(
        "/trials/t1/sources/s1/cited", params={**params, "quote": "ECOG PS | 0"}, headers=AUTH
    )
    assert r.status_code == 200  # the over-long anchor is ignored
    assert r.json()["quote_found"] is True
    assert r.json()["parts"][0]["quote"]["index"] == 4
    r = client.get(
        "/trials/t1/sources/s1/cited", params={**params, "quote": "ECOG PS | 9"}, headers=AUTH
    )
    assert r.json()["quote_found"] is False
    r = client.get("/trials/t1/sources/s1/cited", params=params, headers=AUTH)
    assert r.json()["quote_found"] is None


def test_a_section_titled_with_a_comma_isnt_split():
    xml = XML.replace(
        b'<sec id="Sec8"><title>Discussion</title>',
        b'<sec id="Sec7"><title>Discussion, limitations</title><p>Open label.</p></sec>'
        b'<sec id="Sec8"><title>Discussion</title>',
    )
    (c,) = _Article(xml).cite_all("Discussion, limitations")
    assert c.element.id == "Sec7"


def test_a_quote_in_a_caption_or_title_is_marked_there(article):
    (c,) = article.cite_all("Fig. 2", quote="Fig. 2 EFS, DFS")
    assert (c.quote.where, c.quote.start, c.quote.end) == ("caption", 0, len("EFS, DFS"))


def test_quote_positions_count_as_the_browser_does():
    xml = XML.replace(b"EFS HR 0.76.", "𝑃 &lt; 0.05; EFS HR 0.76.".encode())
    (c,) = _Article(xml).cite_all("Results (Secondary outcomes)", quote="EFS HR 0.76")
    text = c.element.paragraphs[0]
    units = text.encode("utf-16-le")
    assert units[c.quote.start * 2 : c.quote.end * 2].decode("utf-16-le") == "EFS HR 0.76"


def test_cited_endpoint_quote_found_only_where_the_source_said(monkeypatch):
    _source(monkeypatch)

    def found(params):
        r = client.get("/trials/t1/sources/s1/cited", params=params, headers=AUTH)
        return r.json()["quote_found"], [p["elsewhere"] for p in r.json()["parts"]]

    base = {"team_id": "lab", "where": "Table 1"}
    # In Sec3, not Table 1: shown, but still flagged.
    assert found({**base, "quote": "333 patients were randomised"}) == (False, [False, True])
    # A quote with no words to find: nothing to say about it.
    assert found({**base, "quote": "…"}) == (None, [False])
