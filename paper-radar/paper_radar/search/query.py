"""Saved-search queries: one query, run on every source (issue #164).

People paste the PubMed string their weekly email already uses, so the syntax is
PubMed's: words, "quoted phrases", AND / OR / NOT, parentheses, a trailing ``*``
for truncation, and field tags such as ``[tiab]`` or ``[au]``. Adjacent terms
mean AND, and the operators apply strictly left to right with no precedence,
as on PubMed: ``a OR b AND c`` is ``(a OR b) AND c``.

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

Queries are pasted from emails, PDFs and Word, so :func:`clean` first turns what
those bring along (curly quotes, odd dashes and spaces, invisible control
characters) into plain text, and spells field tags the way PubMed knows them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache

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


def _tag_key(tag: str) -> str:
    """A tag with case, spaces and punctuation ignored: "Title/Abstract",
    "TitleAbstract" and "title abstract" are one tag."""
    return re.sub(r"[^a-z0-9:]", "", tag.lower())


# Tag key → the tag as PubMed spells it. PubMed reads a tag it does not know,
# such as [TitleAbstract], as [All Fields] without saying so (checked 2026-11-09).
_PUBMED_TAGS = {_tag_key(t): t for t in (*_FIELD_TAGS, *_FILTER_TAGS)}

_PUBMED_SPELLINGS = frozenset(_PUBMED_TAGS.values())

_PUNCT = str.maketrans(
    {
        **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"),  # dashes, minus
        **dict.fromkeys("\u201c\u201d\u201e\u201f\u00ab\u00bb", '"'),  # curly and angle quotes
        **dict.fromkeys("\u2018\u2019\u201a\u201b", "'"),
        **dict.fromkeys("\u200b\u2060\ufeff", " "),  # zero-width spaces still part words
    }
)

# A control character that is not whitespace, between two letters: a PDF's
# hyphen, as in "R\x02loop". Elsewhere a control character is a space.
_IN_WORD_CONTROL = re.compile(r"(?<=\w)[\x00-\x08\x0e-\x1b\x7f-\x84\x86-\x9f](?=\w)")

# Phrases are left alone; a tag is what sits in brackets outside them.
_PHRASE_OR_TAG = re.compile(r'"[^"]*"|\[([^\[\]"]*)\]')


def _pubmed_tag(m: re.Match[str]) -> str:
    tag = m.group(1)
    if tag is None or " ".join(tag.lower().split()) in _PUBMED_SPELLINGS:
        return m.group(0)
    known = _PUBMED_TAGS.get(_tag_key(tag))
    return f"[{known}]" if known else m.group(0)


def clean(query: str) -> str:
    """The query as plain text, for every source including PubMed: compatibility
    forms folded (NFKC: ligatures, full-width letters, no-break spaces), curly
    quotes and dashes made straight, control characters made hyphens inside a
    word and spaces elsewhere, odd spaces made spaces, other invisible characters
    (soft hyphen, joiners, private use) dropped, runs of spaces made one, and
    field tags respelled as PubMed knows them. A PDF left U+0002 for a hyphen in
    one lab's query; sent on as it was, arXiv answered 500 and the preprints
    never matched. Callers clean once at the edge (saving, running) and
    :func:`parse` the result."""
    text = unicodedata.normalize("NFKC", query).translate(_PUNCT)
    text = _IN_WORD_CONTROL.sub("-", text)
    chars = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cc" or cat[0] == "Z":
            chars.append(" ")
        elif cat[0] != "C":
            chars.append(ch)
    return _PHRASE_OR_TAG.sub(_pubmed_tag, " ".join("".join(chars).split()))


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
        "(?P<phrase>[^"]*)" |
        \[(?P<tag>[^\]]*)\] |
        (?P<word>[^\s()"\[\]]+) |
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
        elif m.group("tag") is not None:
            # PubMed takes "word[tiab]" and "word [tiab]" alike: the tag
            # belongs to the term just before it.
            if not out or out[-1][0] != "term":
                raise QueryError(f"[{m.group('tag')}] must follow a search term.")
            term = out[-1][1]
            assert isinstance(term, Term)
            out[-1] = ("term", replace(term, field=_field(m.group("tag"))))
        elif m.group("phrase") is not None:
            words = m.group("phrase").lower().split()
            if words:
                text = " ".join(words)
                out.append(
                    ("term", Term(text.rstrip("*").strip(), "any", True, text.endswith("*")))
                )
        elif m.group("word"):
            word = m.group("word")
            if word in ("AND", "OR", "NOT"):
                out.append((word, None))
                continue
            text = word.rstrip("*").lower()
            if text:
                out.append(("term", Term(text, "any", False, word.endswith("*"))))
        else:
            raise QueryError(f"Unexpected '{m.group('bad')}' in the query.")
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

    def parse_seq(self) -> Node:
        """Terms joined by AND / OR / NOT (or nothing, meaning AND), applied
        left to right with equal precedence, as PubMed does."""
        node = self.parse_primary()
        while self.peek() in ("AND", "OR", "NOT", "term", "("):
            op = "AND"
            if self.peek() in ("AND", "OR", "NOT"):
                op = str(self.take()[0])
            node = Op(op, node, self.parse_primary())
        return node

    def parse_primary(self) -> Node:
        kind = self.peek()
        if kind is None:
            raise QueryError("The query ends where a search term was expected.")
        if kind == "(":
            self.take()
            node = self.parse_seq()
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
    node = parser.parse_seq()
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


@lru_cache(maxsize=4096)
def _pattern(t: Term) -> re.Pattern[str]:
    # A hyphen in the query matches any dash or space in the text, as the
    # space between phrase words does: "r-loop" finds "R\u2010loops" and "R loop".
    words = [re.escape(p) for w in t.text.split() for p in w.split("-") if p]
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
    tiab = f"{doc.title}\n{doc.abstract}"
    fields = {
        "title": doc.title,
        "tiab": tiab,
        "author": doc.authors,
        "any": f"{tiab}\n{doc.authors}",
    }
    return _eval(node, fields)


def _eval(node: Node, fields: dict[str, str]) -> bool:
    if isinstance(node, Term):
        return _pattern(node).search(fields[node.field]) is not None
    left = _eval(node.left, fields)
    if node.op == "AND":
        return left and _eval(node.right, fields)
    if node.op == "OR":
        return left or _eval(node.right, fields)
    return left and not _eval(node.right, fields)
