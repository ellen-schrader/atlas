"""Build the spelling_variants migration from VarCon (British <-> American).

VarCon (http://wordlist.aspell.net/, en-wl/wordlist) lists the preferred
American, British, Canadian and Australian spellings of English words. This
keeps only what Atlas needs: one-word pairs where a British spelling ("B" or
"Z", preferred or a common "v" variant such as "foetal") differs from the
preferred American one ("A"). Rarer variants ("V", "-", "x"), possessives,
capitalised words and ambiguous mappings are dropped.

VarCon's unverified clusters carry archaic, Scots and fragment entries
("ret" -> "ert", "sae" -> "se", "cre" -> "cer") that would rewrite gene names
and abbreviations. So a pair is kept if its cluster is marked <verified>, or if
the British word has at least 5 letters and turns into the American one by the
usual spelling patterns (_PATTERNS) — a check that can only reject pairs.

A few biomedical words VarCon lacks are added from SUPPLEMENT. This is a
modified (filtered and extended) form of VarCon; see THIRD_PARTY_NOTICES.md.

Usage (from paper-radar/):
    python scripts/varcon_to_sql.py path/to/varcon.txt --max-level 80 > out.sql
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

_WORD = re.compile(r"^[a-z]+$")
_BRITISH = {"B", "Z", "Bv", "Zv"}

# The usual British -> American changes, applied together to vet a pair from an
# unverified cluster: the pair is kept only if they turn one word into the other.
_PATTERNS = [
    (re.compile(r"ae"), "e"),
    (re.compile(r"oe"), "e"),
    (re.compile(r"our"), "or"),
    # -re after b/t (centre, fibre, litre, sabre, theatre): centre(s) -> center(s),
    # centred -> centered, centring -> centering. Never a bare "red"/"ring" end,
    # or "favoured" -> "favored" would be mangled.
    (re.compile(r"([bt])re(s?)$"), r"\1er\2"),
    (re.compile(r"([bt])r(ed|ing)$"), r"\1er\2"),
    (re.compile(r"is(e|ed|es|er|ers|ing|ation|ations|able)"), r"iz\1"),
    (re.compile(r"ys(e|ed|es|er|ers|ing)"), r"yz\1"),
    (re.compile(r"ll"), "l"),
    (re.compile(r"ence(s)?$"), r"ense\1"),
    (re.compile(r"ogue(s)?$"), r"og\1"),
    (re.compile(r"sulph"), "sulf"),
    (re.compile(r"mme(s)?$"), r"m\1"),
]
_MIN_UNVERIFIED = 5

# Not VarCon: biomedical British spellings missing from it, added by hand.
SUPPLEMENT = {
    "oesophageal": "esophageal",
    "gastrooesophageal": "gastroesophageal",
    "oesophagectomy": "esophagectomy",
    "tumourigenesis": "tumorigenesis",
    "tumourigenic": "tumorigenic",
    "tumourigenicity": "tumorigenicity",
    "leukaemic": "leukemic",
    "glycaemia": "glycemia",
    "glycaemic": "glycemic",
    "hypoglycaemia": "hypoglycemia",
    "hypoglycaemic": "hypoglycemic",
    "hyperglycaemia": "hyperglycemia",
    "lymphoedema": "lymphedema",
    "caecum": "cecum",
    "caecal": "cecal",
    "analogue": "analog",
    "analogues": "analogs",
    "homologue": "homolog",
    "homologues": "homologs",
    "orthologue": "ortholog",
    "orthologues": "orthologs",
    "paralogue": "paralog",
    "paralogues": "paralogs",
    "leucocyte": "leukocyte",
    "leucocytes": "leukocytes",
    "leucocytosis": "leukocytosis",
    "tumoural": "tumoral",
    "intratumoural": "intratumoral",
    "peritumoural": "peritumoral",
    "fibreoptic": "fiberoptic",
}
_LEVEL = re.compile(r"\(level (\d+)\)")


def _entries(line: str) -> list[tuple[set[str], str]]:
    """'A Cv: tumor / B C D: tumour | note' -> [({'A','Cv'}, 'tumor'), ...]."""
    body = line.split(" | ", 1)[0].split(" #", 1)[0]
    out = []
    for part in body.split(" / "):
        if ": " not in part:
            continue
        tags, word = part.split(": ", 1)
        out.append(({t for t in tags.split() if not t.isdigit()}, word.strip()))
    return out


def fits_pattern(uk: str, us: str) -> bool:
    """Do the usual spelling changes turn ``uk`` into ``us``?"""
    for pattern, repl in _PATTERNS:
        uk = pattern.sub(repl, uk)
    return uk == us


def pairs(text: str, max_level: int) -> dict[str, str]:
    """British spelling -> American spelling, one word each, unambiguous only."""
    candidates: dict[str, set[str]] = defaultdict(set)
    american: set[str] = set()
    level, verified = 100, False
    for raw in text.splitlines():
        if raw.startswith("# "):
            m = _LEVEL.search(raw)
            level = int(m.group(1)) if m else 100
            verified = "<verified>" in raw
            continue
        if not raw.strip() or raw.startswith("#"):
            continue
        entries = _entries(raw)
        us = [w for tags, w in entries if "A" in tags]
        # Every American spelling counts for the ambiguity check, whatever its
        # level — a British form that is American anywhere is left alone.
        american.update(us)
        if level > max_level or len(us) != 1:
            continue
        for w in (w for tags, w in entries if tags & _BRITISH):
            if w != us[0] and (
                verified or (len(w) >= _MIN_UNVERIFIED and fits_pattern(w, us[0]))
            ):
                candidates[w].add(us[0])
    found = {
        uk: next(iter(us))
        for uk, us in candidates.items()
        if len(us) == 1
        and _WORD.match(uk)
        and _WORD.match(next(iter(us)))
        # A British form that is also a preferred American spelling elsewhere
        # ("practise"? no; "metre"? no; but e.g. "draught" vs "draft") is
        # ambiguous: leave it alone.
        and uk not in american
    }
    return {**found, **{uk: us for uk, us in SUPPLEMENT.items() if uk not in found}}


def render(mapping: dict[str, str], source: Path, max_level: int) -> str:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = ",\n".join(f"    ('{uk}', '{us}')" for uk, us in sorted(mapping.items()))
    return (
        f"-- Generated by scripts/varcon_to_sql.py from VarCon varcon.txt\n"
        f"-- (sha256 {digest}), SCOWL level <= {max_level}: {len(mapping)} pairs.\n"
        f"-- Filtered from VarCon, Copyright 2000-2020 Kevin Atkinson and Benjamin Titze;\n"
        f"-- original lists Copyright 1993 Geoff Kuenning. See THIRD_PARTY_NOTICES.md.\n"
        f"insert into public.spelling_variants (uk, us) values\n{rows};\n"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("varcon", type=Path)
    parser.add_argument("--max-level", type=int, default=80)
    args = parser.parse_args(argv)
    text = args.varcon.read_text(encoding="latin-1")  # VarCon is Latin-1, not UTF-8
    mapping = pairs(text, args.max_level)
    sys.stdout.write(render(mapping, args.varcon, args.max_level))


if __name__ == "__main__":
    main()
