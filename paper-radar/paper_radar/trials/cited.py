"""What an extraction's source points at, in a JATS article, for showing it.

An extracted value's source says where in the document it came from, in
Claude's words: "Results (Patient disposition); Table 1", "Table 1 (ECOG PS)",
"Fig. 2d", "Extended Data Table 3". Each part (split on ";") is matched to the
article: every table or figure it names by label ("Table 2, Fig. 3b", "Tables
1 and 2"), else a section by its title (a subsection in brackets, when there
is one). A table's bracket names its row, so the rows it covers can be marked.

Read with jats.py's safe parsing: any document declaring entities is refused.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import cached_property
from typing import Literal

from . import jats

_PMCID = re.compile(r"PMC\d{1,10}")  # fullmatch: "$" would let a newline through
_XLINK = "{http://www.w3.org/1999/xlink}href"
# A figure's image file as the article names it: a plain file name, no path.
_GRAPHIC = re.compile(r"\w[\w.-]{0,199}")  # fullmatch

# "Table 1", "Extended Data Table 3", "Supplementary Table S2", "Fig. 2d",
# "Figure 3", "Extended Data Fig. 4b": a prefix, the kind, a number and a panel.
_FLOAT = re.compile(
    r"\b(?P<prefix>extended\s+data\s+|supplementary\s+)?"
    r"(?P<kind>tables?|figs?\.?|figures?)\s*"
    r"(?P<number>S?\d+)(?P<panel>[a-z](?:[–,-][a-z])*)?\b",
    re.IGNORECASE,
)
# More numbers after a plural label: "Tables 1 and 2", "Figs. 2, 3b".
_MORE = re.compile(r"\s*(?:,|and|&)\s*(?P<number>S?\d+)(?P<panel>[a-z])?\b", re.IGNORECASE)


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
    image: str | None = None  # a figure's image on PMC


@dataclass
class Citation:
    """One part of a source, and what it points at (None: nothing matched)."""

    part: str
    element: Element | None
    rows: list[int] = field(default_factory=list)  # a table's rows the part names
    panel: str | None = None  # a figure's panel ("d")


def _text(el: ET.Element | None) -> str:
    return jats._text(el) if el is not None else ""


def _key(prefix: str | None, kind: str, number: str) -> str:
    """What identifies a table or figure: "extended data table 3" for
    "Extended Data Table 3", "fig 2" for "Figure 2" or "Fig. 2"."""
    prefix = " ".join(prefix.lower().split()) if prefix else ""
    number = number.upper()
    if number.startswith("S"):  # "Table S2" is "Supplementary Table 2"
        prefix, number = "supplementary", number[1:]
    kind = "table" if kind.lower().startswith("table") else "fig"
    return " ".join(x for x in (prefix, kind, number) if x)


def _label_key(label: str) -> str | None:
    m = _FLOAT.search(label)
    return _key(m["prefix"], m["kind"], m["number"]) if m else None


def _display(key: str, panel: str | None, note: str | None) -> str:
    """A key as a label again: "Extended Data Table 3", "Fig. 2b (EFS)"."""
    *prefix, kind, number = key.split()
    label = " ".join([*(w.capitalize() for w in prefix), "Table" if kind == "table" else "Fig."])
    return f"{label} {number}{panel or ''}" + (f" ({note})" if note else "")


def _note(rest: str) -> str | None:
    """What's in the brackets that open `rest`: "ECOG PS" for " (ECOG PS)",
    "Age, n (%)" for "(Age, n (%))"."""
    rest = rest.strip()
    if not rest.startswith("("):
        return None
    close = rest.rfind(")")
    return (rest[1:close] if close > 0 else rest[1:]).strip() or None


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


def _figure(fig: ET.Element, pmcid: str | None) -> Element:
    return Element(
        id=fig.get("id") or "",
        kind="figure",
        label=_text(fig.find("label")),
        caption=_text(fig.find("caption")),
        image=_image(fig, pmcid),
    )


def _image(fig: ET.Element, pmcid: str | None) -> str | None:
    """Where PMC serves the figure's image (it redirects to NCBI's image
    host), or None. Its figures are JPEGs, named after the article's file:
    the extension may be left off, or be the original's (.tif)."""
    graphics = [g for g in fig.iter("graphic") if g.get("content-type") != "thumb"]
    # The full image, when a figure gives alternatives.
    graphic = next((g for g in graphics if g.get("content-type") == "image"), None)
    graphic = graphic if graphic is not None else next(iter(graphics), None)
    name = graphic.get(_XLINK, "") if graphic is not None else ""
    if not (pmcid and _GRAPHIC.fullmatch(name)):
        return None
    stem, dot, ext = name.rpartition(".")
    if not (dot and ext.lower() in ("jpg", "jpeg", "png", "gif")):
        name = (stem if dot and ext.lower() in ("tif", "tiff", "eps", "pdf") else name) + ".jpg"
    return f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{pmcid[3:]}/bin/{name}"


def _section(sec: ET.Element, title: str) -> Element:
    paragraphs: list[str] = []

    def walk(s: ET.Element) -> None:
        for child in s:
            if child.tag == "sec":
                sub = _text(child.find("title"))
                if sub:
                    paragraphs.append(f"## {sub}")
                walk(child)
            elif child.tag in ("p", "list", "disp-quote"):
                # Tables and figures inside a paragraph are elements of their own.
                inner = any(x.tag in ("table-wrap", "fig") for x in child.iter() if x is not child)
                text = _text(jats._without(child, ("table-wrap", "fig")) if inner else child)
                if text:
                    paragraphs.append(text)

    walk(sec)
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
                key = _label_key(_text(el.find("label")))
                if key and key not in self.floats:  # the first, not a later copy
                    self.floats[key] = el

    @cached_property
    def pmcid(self) -> str | None:
        """The article's PMC id ("PMC12283416"), if it gives a well-formed one."""
        for el in self.root.iter("article-id"):
            if el.get("pub-id-type") == "pmcid" and _PMCID.fullmatch(_text(el)):
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

    def _float(self, ref: str, key: str, panel: str | None, note: str | None) -> Citation:
        el = self.floats.get(key)
        if el is None:
            return Citation(ref, None)
        if el.tag == "fig":
            return Citation(ref, _figure(el, self.pmcid), panel=panel.lower() if panel else None)
        table = _table(el)
        return Citation(ref, table, rows=_rows(table, note))

    def cite(self, part: str) -> list[Citation]:
        """What one part of a source points at: each table and figure it
        names, else the section it names (a list of one, its element None
        when nothing matched)."""
        part = part.strip()
        # Every label, with the numbers a plural one goes on to list.
        refs: list[tuple[int, int, str, str | None]] = []  # start, end, key, panel
        for m in _FLOAT.finditer(part):
            refs.append((m.start(), m.end(), _key(m["prefix"], m["kind"], m["number"]), m["panel"]))
            if m["kind"].lower().rstrip(".").endswith("s"):
                pos = m.end()
                while more := _MORE.match(part, pos):
                    key = _key(m["prefix"], m["kind"], more["number"])
                    refs.append((more.start("number"), more.end(), key, more["panel"]))
                    pos = more.end()
        if refs:
            out = []
            for i, (_start, end, key, panel) in enumerate(refs):
                stop = refs[i + 1][0] if i + 1 < len(refs) else len(part)
                note = _note(part[end:stop])
                # Each named on its own: "Table 3" for the 3 of "Tables 1 and 3".
                ref = part if len(refs) == 1 else _display(key, panel, note)
                out.append(self._float(ref, key, panel, note))
            return out
        if part.casefold().startswith("abstract"):
            abstract = next(self.root.iter("abstract"), None)
            if abstract is not None:
                return [Citation(part, _section(abstract, "Abstract"))]
        title, _, rest = part.partition("(")
        sec = self._find_section(title.strip()) if title.strip() else None
        if sec is None:
            return [Citation(part, None)]
        if note := _note("(" + rest if rest else ""):
            # "Results (Patient disposition)": the subsection, when it is one;
            # else the note is Claude's comment ("Main (introduction, …)").
            sub = self._find_section(note, within=sec)
            if sub is not None and sub is not sec:
                sec = sub
        return [Citation(part, _section(sec, _text(sec.find("title"))))]

    def cite_id(self, anchor: str) -> Citation | None:
        """The table, figure or section with this id (an extraction's anchor)."""
        for el in self.root.iter():
            if el.get("id") != anchor:
                continue
            if el.tag == "table-wrap":
                table = _table(el)
                return Citation(table.label or anchor, table)
            if el.tag == "fig":
                fig = _figure(el, self.pmcid)
                return Citation(fig.label or anchor, fig)
            if el.tag in ("sec", "abstract"):
                title = _text(el.find("title")) or ("Abstract" if el.tag == "abstract" else "")
                return Citation(title or anchor, _section(el, title))
            return None
        return None

    def cite_all(self, where: str, anchor: str | None = None) -> list[Citation]:
        """Each part of a source ("A; B"), in order, once each. The element an
        anchor names comes first: it's where the quote is."""
        seen: set[str] = set()
        out = []
        for part in where.split(";"):
            if part.strip() and part.strip().casefold() not in seen:
                seen.add(part.strip().casefold())
                out.extend(self.cite(part))
        named = self.cite_id(anchor) if anchor else None
        if named is not None and named.element is not None:
            same = [c for c in out if c.element is not None and c.element.id == named.element.id]
            out = [*(same[:1] or [named]), *(c for c in out if c not in same[:1])]
        return out


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _rows(table: Element, note: str | None) -> list[int]:
    """The rows a note names ("ECOG PS"): the row whose label (first cell)
    starts with it, and the rows under it without a label of their own (its
    categories), whether the label is blank there or spans them."""
    if not note:
        return []
    # "Age, n (%)" also as "Age": the label may give the units differently.
    wants = {w for w in (_norm(note), _norm(re.split(r"[,(]", note)[0])) if w}
    out: list[int] = []
    spanned = 0  # rows still covered by a label cell from above
    for i, row in enumerate(table.rows):
        if spanned:
            spanned -= 1
            label = None
        else:
            label = row[0] if row else None
            spanned = label.rowspan - 1 if label else 0
        if out:
            if label is not None and (label.text.strip() or label.header):
                break
            out.append(i)
        elif label is not None and not label.header:
            first = _norm(label.text)
            if first and any(
                first.startswith(w) or (len(first) >= 3 and w.startswith(first)) for w in wants
            ):
                out.append(i)
    return out
