"""Saved-search queries: one query, run on every source (issue #164).

People paste the PubMed string their weekly email already uses, so the syntax is
PubMed's: words, "quoted phrases", AND / OR / NOT, parentheses, a trailing ``*``
for truncation, and field tags such as ``[tiab]`` or ``[au]``. Adjacent terms
mean AND, as on PubMed.

PubMed gets the string exactly as typed. For the other sources it is parsed
here once and then

* rendered for arXiv's search API (:func:`to_arxiv`), and
* matched against bioRxiv/medRxiv preprints locally (:func:`matches`), since
  bioRxiv's API cannot search.

Field tags map to what those sources have: title, title/abstract, author.
MeSH and other text tags search everything (preprints have no MeSH terms).
PubMed's filters -- publication type, language, date, journal, subset -- have
no counterpart on a preprint, so those clauses are left out there rather than
read as words ("NOT review[pt]" must not drop preprints that say "review").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_TERMS = 60  # a generous PubMed string has a few dozen

# PubMed tag (lowercased, inside the brackets) → the field we search.
_FIELD_TAGS = {
    "ti": "title",
    "title": "title",
    "tiab": "tiab",
    "title/abstract": "tiab",
    "ab": "tiab",
    "abstract": "tiab",
    "au": "author",
    "author": "author",
    "1au": "author",
    "lastau": "author",
    "fau": "author",
    "full author name": "author",
}


# Filters, not text: left out off PubMed (see the module docstring).
_FILTER_TAGS = {
    "pt",
    "publication type",
    "la",
    "language",
    "dp",
    "publication date",
    "pdat",
    "edat",
    "crdt",
    "mhda",
    "dcom",
    "lr",
    "ta",
    "journal",
    "jour",
    "sb",
    "subset",
    "filter",
    "sh",
    "subheading",
    "majr:noexp",
    "ptyp",
}


class QueryError(ValueError):
    """The query cannot be parsed; the message is meant for the person who typed it."""


@dataclass(frozen=True)
class Term:
    text: str  # lowercased; for a phrase, its words joined by single spaces
    field: str = "any"  # "any" | "title" | "tiab" | "author" | "filter"
    phrase: bool = False
    prefix: bool = False  # a trailing * (truncation)


@dataclass(frozen=True)
class Op:
    op: str  # "AND" | "OR" | "NOT" (binary: left AND NOT right)
    left: Node
    right: Node


Node = Term | Op

_TOKEN = re.compile(
    r"""
    \s*(?:
        (?P<lparen>\() |
        (?P<rparen>\)) |
        "(?P<phrase>[^"]*)"(?:\s*\[(?P<ptag>[^\]]*)\])? |
        (?P<word>[^\s()"\[\]]+)(?:\[(?P<wtag>[^\]]*)\])? |
        (?P<bad>\S)
    )
    """,
    re.VERBOSE,
)


def _field(tag: str | None) -> str:
    if not tag:
        return "any"
    tag = " ".join(tag.lower().split())
    if tag in _FILTER_TAGS:
        return "filter"
    return _FIELD_TAGS.get(tag.replace(":noexp", ""), "any")


def _tokens(query: str) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    pos = 0
    query = query.strip()
    while pos < len(query):
        m = _TOKEN.match(query, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        if m.group("lparen"):
            out.append(("(", None))
        elif m.group("rparen"):
            out.append((")", None))
        elif m.group("phrase") is not None:
            words = m.group("phrase").lower().split()
            if words:
                text = " ".join(words)
                prefix = text.endswith("*")
                out.append(
                    (
                        "term",
                        Term(text.rstrip("*").strip(), _field(m.group("ptag")), True, prefix),
                    )
                )
        elif m.group("word"):
            word = m.group("word")
            if word in ("AND", "OR", "NOT"):
                out.append((word, None))
                continue
            prefix = word.endswith("*")
            text = word.rstrip("*").lower()
            if text:
                out.append(("term", Term(text, _field(m.group("wtag")), False, prefix)))
        else:
            ch = m.group("bad")
            raise QueryError(f"Unexpected '{ch}' in the query.")
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, object]]) -> None:
        self.tokens = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.tokens[self.i][0] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, object]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.peek() == "OR":
            self.take()
            node = Op("OR", node, self.parse_and())
        return node

    def parse_and(self) -> Node:
        node = self.parse_primary()
        while self.peek() in ("AND", "NOT", "term", "("):
            kind = self.peek()
            op = "AND"
            if kind in ("AND", "NOT"):
                self.take()
                op = kind
            node = Op(op, node, self.parse_primary())
        return node

    def parse_primary(self) -> Node:
        kind = self.peek()
        if kind is None:
            raise QueryError("The query ends where a search term was expected.")
        if kind == "(":
            self.take()
            node = self.parse_or()
            if self.peek() != ")":
                raise QueryError("A '(' is never closed.")
            self.take()
            return node
        if kind == "term":
            return self.take()[1]  # type: ignore[return-value]
        if kind == ")":
            raise QueryError("A ')' has no matching '('.")
        raise QueryError(f"{kind} needs a search term on both sides.")


def parse(query: str) -> Node:
    """The query as a tree, or :class:`QueryError` saying what is wrong with it."""
    tokens = _tokens(query)
    if not tokens:
        raise QueryError("The query is empty.")
    if sum(1 for kind, _ in tokens if kind == "term") > MAX_TERMS:
        raise QueryError(f"The query has more than {MAX_TERMS} search terms.")
    parser = _Parser(tokens)
    node = parser.parse_or()
    if parser.peek() is not None:
        raise QueryError("A ')' has no matching '('.")
    return node


def without_filters(node: Node) -> Node | None:
    """The query minus PubMed-only filter clauses; None if nothing is left.

    Dropping a clause drops its operator with it: ``a AND b[pt]`` becomes ``a``,
    ``a NOT b[pt]`` becomes ``a``, and so does ``a OR b[pt]``.
    """
    if isinstance(node, Term):
        return None if node.field == "filter" else node
    left, right = without_filters(node.left), without_filters(node.right)
    if left is None or right is None:
        return left or right if node.op != "NOT" else left
    return Op(node.op, left, right)


# --- arXiv -------------------------------------------------------------------------

_ARXIV_FIELD = {"any": "all", "title": "ti", "author": "au"}


def _arxiv_term(t: Term) -> str:
    # arXiv's search has no truncation; it stems words itself, which covers most
    # of what a trailing * is for.
    value = f'"{t.text}"' if t.phrase or " " in t.text else t.text
    if t.field == "tiab":
        return f"(ti:{value} OR abs:{value})"
    return f"{_ARXIV_FIELD[t.field]}:{value}"


def to_arxiv(node: Node) -> str:
    """The query in arXiv's ``search_query`` syntax. Pass it :func:`without_filters`."""
    if isinstance(node, Term):
        return _arxiv_term(node)
    op = "ANDNOT" if node.op == "NOT" else node.op
    return f"({to_arxiv(node.left)} {op} {to_arxiv(node.right)})"


# --- local matching (bioRxiv / medRxiv) ----------------------------------------------


def _pattern(t: Term) -> re.Pattern[str]:
    words = [re.escape(w) for w in t.text.split()]
    body = r"\W+".join(words)
    # PubMed matches plurals of a plain word; a light s/es keeps "structure"
    # finding "structures" without a stemmer.
    tail = r"\w*" if t.prefix else r"(?:s|es)?\b"
    return re.compile(rf"\b{body}{tail}", re.IGNORECASE)


@dataclass(frozen=True)
class Doc:
    title: str
    abstract: str = ""
    authors: str = ""  # one string, "; "-joined


def matches(node: Node, doc: Doc) -> bool:
    """Whether a preprint satisfies the query, PubMed-style. Pass it
    :func:`without_filters`."""
    if isinstance(node, Term):
        haystack = {
            "title": doc.title,
            "tiab": f"{doc.title}\n{doc.abstract}",
            "author": doc.authors,
            "any": f"{doc.title}\n{doc.abstract}\n{doc.authors}",
        }[node.field]
        return _pattern(node).search(haystack) is not None
    left = matches(node.left, doc)
    if node.op == "AND":
        return left and matches(node.right, doc)
    if node.op == "OR":
        return left or matches(node.right, doc)
    return left and not matches(node.right, doc)
