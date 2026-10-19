"""JATS full text (Europe PMC) → the plain text Claude reads for extraction.

The XML's markup costs more tokens than its words, and a third of an article is
references, author lists and declarations that hold no trial data. Kept: the
title, abstract, every body section about the trial (methods, results,
discussion), every table (rows as " | "-separated cells, with footnotes) and
every figure caption. The stored file stays the original; only what is sent to
Claude is trimmed, and anything that can't be parsed is sent as it was.

Parsed with the standard library, refusing any document that declares entities
(the "billion laughs" family), though Europe PMC's files never do.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# Sections with no trial data in them, matched on their titles.
_DROP_SECTIONS = re.compile(
    r"^\s*(references?|acknowledg|author(s'|s’)? contributions?|peer review|competing interests"
    r"|conflicts? of interest|data availability|code availability|footnotes?|online content"
    r"|reporting summary|associated data|additional information|ethics declarations"
    r"|declaration|funding)",
    re.IGNORECASE,
)
_DROP_TAGS = {"ref-list", "ack", "fn-group", "contrib-group", "aff", "author-notes", "permissions"}


class NotJats(Exception):
    pass


def _text(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _table(tw: ET.Element) -> str:
    lines = []
    head = " ".join(_text(x) for x in (tw.find("label"), tw.find("caption")) if x is not None)
    if head:
        lines.append(f"[Table] {head}")
    for tr in tw.iter("tr"):
        cells = [_text(c) for c in tr if c.tag in ("td", "th")]
        if any(cells):
            lines.append(" | ".join(cells))
    for foot in tw.iter("table-wrap-foot"):
        lines.append(_text(foot))
    return "\n".join(lines)


def _figure(fig: ET.Element) -> str:
    head = " ".join(_text(x) for x in (fig.find("label"), fig.find("caption")) if x is not None)
    return f"[Figure] {head}" if head else ""


def _section(sec: ET.Element, depth: int, out: list[str]) -> None:
    title = sec.find("title")
    title_text = _text(title) if title is not None else ""
    if title_text and _DROP_SECTIONS.match(title_text):
        return
    if title_text:
        out.append(f"\n{'#' * min(depth, 4)} {title_text}")
    for child in sec:
        if child.tag == "title" or child.tag in _DROP_TAGS:
            continue
        if child.tag == "sec":
            _section(child, depth + 1, out)
        elif child.tag == "table-wrap":
            out.append(_table(child))
        elif child.tag == "fig":
            out.append(_figure(child))
        else:
            # A paragraph (or list) may hold tables and figures inline.
            inner = [x for x in child.iter() if x.tag in ("table-wrap", "fig") and x is not child]
            for x in inner:
                out.append(_table(x) if x.tag == "table-wrap" else _figure(x))
            # Copy-and-strip only when there's something inline to strip.
            text = _text(_without(child, ("table-wrap", "fig")) if inner else child)
            if text:
                out.append(text)


def _without(el: ET.Element, tags: tuple[str, ...]) -> ET.Element:
    """A copy of `el` without the given descendants (already output separately)."""
    copy = ET.fromstring(ET.tostring(el))
    for parent in copy.iter():
        for child in list(parent):
            if child.tag in tags:
                parent.remove(child)
    return copy


def to_text(xml: bytes) -> str:
    """The article as extraction text. Raises NotJats if it can't be read."""
    if b"<!ENTITY" in xml:
        raise NotJats("declares entities")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise NotJats(str(exc)) from exc
    out: list[str] = []
    title = next(root.iter("article-title"), None)
    if title is not None:
        out.append(f"# {_text(title)}")
    for abstract in root.iter("abstract"):
        out.append("\n## Abstract")
        out.append(_text(abstract))
    body = next(root.iter("body"), None)
    if body is None:
        raise NotJats("no body")
    for child in body:
        if child.tag == "sec":
            _section(child, 2, out)
        elif child.tag == "table-wrap":
            out.append(_table(child))
        elif child.tag == "fig":
            out.append(_figure(child))
        elif child.tag not in _DROP_TAGS:
            text = _text(child)
            if text:
                out.append(text)
    # The back matter: appendix sections, and tables anywhere in it
    # (Extended Data, supplementary tables).
    back = next(root.iter("back"), None)
    if back is not None:
        done: set[int] = set()
        for app in back.iter("app"):
            for sec in app.findall("sec"):  # top level: _section recurses
                _section(sec, 2, out)
                done.update(id(t) for t in sec.iter("table-wrap"))
        for tw in back.iter("table-wrap"):
            if id(tw) not in done:
                out.append(_table(tw))
    # Some publishers put every table and figure in a <floats-group> after it.
    for floats in root.iter("floats-group"):
        for x in floats:
            if x.tag == "table-wrap":
                out.append(_table(x))
            elif x.tag == "fig":
                out.append(_figure(x))
    return "\n".join(x for x in out if x).strip()
