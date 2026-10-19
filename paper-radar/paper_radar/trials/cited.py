"""What an extraction's source points at, in a JATS article, for showing it.

An extracted value's source says where in the document it came from, in
Claude's words: "Results (Patient disposition); Table 1", "Table 1 (ECOG PS)",
"Fig. 2d", "Extended Data Table 3". Each part (split on ";") is matched to one
element of the article: a table or figure by its label, else a section by its
title (a subsection in brackets, when there is one). A table part's bracket
names its row, so the rows it covers can be marked.

Read with jats.py's safe parsing: any document declaring entities is refused.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Literal

from . import jats

_XLINK = "{http://www.w3.org/1999/xlink}href"
_PMCID = re.compile(r"^PMC\d{1,10}$")

# "Table 1", "Extended Data Table 3", "Supplementary Table S2", "Fig. 2d",
# "Figure 3", "Extended Data Fig. 4b": a prefix, the kind, a number and a panel.
_FLOAT = re.compile(
    r"\b(?P<prefix>extended\s+data\s+|supplementary\s+)?"
    r"(?P<kind>tables?|figs?\.?|figures?)\s*"
    r"(?P<number>S?\d+)(?P<panel>[a-z](?:[–,-][a-z])*)?\b",
    re.IGNORECASE,
)
# "Results (Patient disposition)": a title and what's in brackets after it.
_TITLE_NOTE = re.compile(r"^\s*(?P<title>[^()]+?)\s*(?:\((?P<note>[^()]*)\))?\s*$")


@dataclass
class Cell:
    text: str
    header: bool = False
    colspan: int = 1
    rowspan: int = 1


@dataclass
class Element:
    """A table, figure or section, ready to show."""

    id: str
    kind: Literal["table", "figure", "section"]
    label: str  # "Table 1", "Fig. 2", or the section's title
    caption: str = ""
    rows: list[list[Cell]] = field(default_factory=list)  # tables
    paragraphs: list[str] = field(default_factory=list)  # sections; "## " starts a subheading
    footnotes: list[str] = field(default_factory=list)
    graphic: str | None = None  # a figure's image file, as the article names it


@dataclass
class Citation:
    """One part of a source, and what it points at (None: nothing matched)."""

    part: str
    element: Element | None
    rows: list[int] = field(default_factory=list)  # a table's rows the part names
    panel: str | None = None  # a figure's panel ("d")


def _text(el: ET.Element | None) -> str:
    return jats._text(el) if el is not None else ""


def _key(label: str) -> str | None:
    """A float's label reduced to what identifies it: "extended data table 3"
    for "Extended Data Table 3", "fig 2" for "Figure 2" or "Fig. 2"."""
    m = _FLOAT.search(label)
    if not m:
        return None
    prefix = " ".join(m["prefix"].lower().split()) if m["prefix"] else ""
    number = m["number"].upper()
    if number.startswith("S"):  # "Table S2" is "Supplementary Table 2"
        prefix, number = "supplementary", number[1:]
    kind = "table" if m["kind"].lower().startswith("table") else "fig"
    return " ".join(x for x in (prefix, kind, number) if x)


def _table(tw: ET.Element) -> Element:
    rows = []
    for tr in tw.iter("tr"):
        cells = [
            Cell(
                text=_text(c),
                header=c.tag == "th",
                colspan=_span(c.get("colspan")),
                rowspan=_span(c.get("rowspan")),
            )
            for c in tr
            if c.tag in ("td", "th")
        ]
        if cells:
            rows.append(cells)
    return Element(
        id=tw.get("id") or "",
        kind="table",
        label=_text(tw.find("label")),
        caption=_text(tw.find("caption")),
        rows=rows,
        footnotes=_footnotes(tw),
    )


def _span(value: str | None) -> int:
    try:
        return max(1, min(int(value or 1), 50))
    except ValueError:
        return 1


def _footnotes(tw: ET.Element) -> list[str]:
    out = []
    for foot in tw.iter("table-wrap-foot"):
        # One line per footnote or paragraph: run together, "a" markers and
        # their text blur ("aRoad traffic accident.bPneumonia").
        parts = [x for x in foot if x.tag in ("fn", "p")]
        out.extend(t for t in (_text(x) for x in parts or [foot]) if t)
    return out


def _figure(fig: ET.Element) -> Element:
    graphic = next(fig.iter("graphic"), None)
    return Element(
        id=fig.get("id") or "",
        kind="figure",
        label=_text(fig.find("label")),
        caption=_text(fig.find("caption")),
        graphic=graphic.get(_XLINK) if graphic is not None else None,
    )


def _section(sec: ET.Element, title: str) -> Element:
    paragraphs: list[str] = []

    def walk(s: ET.Element, depth: int) -> None:
        for child in s:
            if child.tag == "sec":
                sub = _text(child.find("title"))
                if sub:
                    paragraphs.append(f"## {sub}")
                walk(child, depth + 1)
            elif child.tag in ("p", "list", "disp-quote"):
                # Tables and figures inside a paragraph are elements of their own.
                inner = any(x.tag in ("table-wrap", "fig") for x in child.iter() if x is not child)
                text = _text(jats._without(child, ("table-wrap", "fig")) if inner else child)
                if text:
                    paragraphs.append(text)

    walk(sec, 0)
    return Element(id=sec.get("id") or "", kind="section", label=title, paragraphs=paragraphs)


class Article:
    """An article's tables, figures and sections, found by what a source says."""

    def __init__(self, xml: bytes):
        jats._refuse_entities(xml)
        try:
            self.root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise jats.NotJats(str(exc)) from exc
        self.floats: dict[str, ET.Element] = {}
        for el in self.root.iter():
            if el.tag in ("table-wrap", "fig"):
                key = _key(_text(el.find("label")))
                if key and key not in self.floats:  # the first, not a later copy
                    self.floats[key] = el

    @property
    def pmcid(self) -> str | None:
        """The article's PMC id ("PMC12283416"), if it gives a well-formed one."""
        for el in self.root.iter("article-id"):
            if el.get("pub-id-type") == "pmcid" and _PMCID.match(_text(el)):
                return _text(el)
        return None

    def _find_section(self, title: str, within: ET.Element | None = None) -> ET.Element | None:
        """A section by its title: exactly, else the first whose title the
        given one starts with ("Discussion for definition" → Discussion).
        Top-level sections first, so "Results" isn't a subsection of that name."""
        want = " ".join(title.casefold().split())
        if within is not None:
            candidates = list(within.iter("sec"))
        else:
            body = self.root.find("body")
            top = list(body.findall("sec")) if body is not None else []
            candidates = list(dict.fromkeys([*top, *self.root.iter("sec")]))
        titled = [(sec, _text(sec.find("title")).casefold()) for sec in candidates]
        for sec, name in titled:
            if name == want:
                return sec
        for sec, name in titled:
            if name and want.startswith(name + " "):
                return sec
        return None

    def cite(self, part: str) -> Citation:
        """What one part of a source points at."""
        part = part.strip()
        m = _FLOAT.search(part)
        if m:
            el = self.floats.get(_key(m.group(0)) or "")
            if el is None:
                return Citation(part, None)
            if el.tag == "fig":
                return Citation(part, _figure(el), panel=m["panel"].lower() if m["panel"] else None)
            table = _table(el)
            note = _TITLE_NOTE.match(part[m.end() :] or "")
            return Citation(part, table, rows=_rows(table, note["note"] if note else None))
        if part.casefold().startswith("abstract"):
            abstract = next(self.root.iter("abstract"), None)
            if abstract is not None:
                return Citation(part, _section(abstract, "Abstract"))
        tn = _TITLE_NOTE.match(part)
        if not tn:
            return Citation(part, None)
        sec = self._find_section(tn["title"])
        if sec is None:
            return Citation(part, None)
        if tn["note"]:
            # "Results (Patient disposition)": the subsection, when it is one;
            # else the note is Claude's comment ("Main (introduction, …)").
            sub = self._find_section(tn["note"], within=sec)
            if sub is not None and sub is not sec:
                sec = sub
        return Citation(part, _section(sec, _text(sec.find("title"))))

    def cite_all(self, where: str) -> list[Citation]:
        """Each part of a source ("A; B"), in order, once each."""
        seen: set[str] = set()
        out = []
        for part in where.split(";"):
            if part.strip() and part.strip().casefold() not in seen:
                seen.add(part.strip().casefold())
                out.append(self.cite(part))
        return out


def _rows(table: Element, note: str | None) -> list[int]:
    """The rows a note names ("ECOG PS"): the row whose first cell starts with
    it, and the rows under it with an empty first cell (its categories)."""
    if not note:
        return []
    want = " ".join(note.casefold().split())
    out: list[int] = []
    for i, row in enumerate(table.rows):
        first = " ".join(row[0].text.casefold().split()) if row else ""
        if out:
            if first or row[0].header:
                break
            out.append(i)
        elif (
            first
            and not row[0].header
            and (first.startswith(want) or (len(first) >= 3 and want.startswith(first)))
        ):
            out.append(i)
    return out
