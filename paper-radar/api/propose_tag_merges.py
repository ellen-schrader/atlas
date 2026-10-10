"""Propose tag merges for review (service role, read-only on the database).

Collects every tag in use — AI tags on papers and every lab's own tags on posts —
asks Claude which ones mean the same thing (plurals, spelling variants,
abbreviations, synonyms), and writes two files for a human to review:

  tag-merges.md   the proposals as a table: kept tag, tags merged into it, why
  tag-merges.sql  the same as a migration body: tag_aliases inserts + cleanup

Nothing is changed. After review, edit the .sql (delete rows you disagree with)
and add it as a migration; on merge it inserts the aliases and rewrites stored
tags through apply_tag_cleanup() (20261010140000_tag_hygiene.sql).

Usage (from paper-radar/, with ANTHROPIC_API_KEY and the target database's
SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in .env):
    uv run --extra api python -m api.propose_tag_merges [--out-dir .]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from paper_radar.config import get_settings

from .enrichment import normalise_tag
from .supa import service_client

_PAGE = 1000


class _Merge(BaseModel):
    canonical: str
    aliases: list[str]
    reason: str


class _Merges(BaseModel):
    merges: list[_Merge]


def _rows(svc, table: str, column: str) -> list[list]:
    out: list[list] = []
    start = 0
    while True:
        # Ordered: without it, separate LIMIT/OFFSET pages can overlap or skip rows.
        page = (
            svc.table(table)
            .select(column)
            .order("id")
            .range(start, start + _PAGE - 1)
            .execute()
            .data
            or []
        )
        out.extend(r.get(column) or [] for r in page)
        if len(page) < _PAGE:
            return out
        start += _PAGE


def collect_tags(svc) -> Counter:
    """Every tag on papers and posts, normalised, with how many rows carry it."""
    counts: Counter = Counter()
    for tags in _rows(svc, "papers", "tags") + _rows(svc, "paper_posts", "tags"):
        for tag in {normalise_tag(t) for t in tags if isinstance(t, str)}:
            if tag:
                counts[tag] += 1
    return counts


def propose(counts: Counter, settings) -> list[_Merge]:
    import anthropic

    listing = "\n".join(f"{tag} ({n})" for tag, n in counts.most_common())
    prompt = (
        "Below is every topical tag in a research lab's paper library, with how many "
        "papers carry it. Find groups of tags that mean the same thing: plurals, "
        "spelling variants (tumor/tumour), abbreviations (tme / "
        "tumor-microenvironment), word-order or hyphenation variants, and true "
        "synonyms.\n\n"
        "For each group, pick the kept tag (usually the most-used, or the clearest "
        "full form) and list the others as aliases. Do NOT merge tags that are "
        "related but different: a narrower topic is not a synonym of a broader one "
        "(triple-negative-breast-cancer is not breast-cancer), and a method is not "
        "its application. When unsure, leave the tags apart. Use the tags exactly as "
        "listed. Give a short reason per group.\n\n<tags>\n" + listing + "\n</tags>"
    )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.parse(
        model=settings.anthropic_model,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_format=_Merges,
    )
    return resp.parsed_output.merges


def existing_aliases(svc) -> dict[str, str]:
    """The merges already in tag_aliases (alias → canonical)."""
    rows = svc.table("tag_aliases").select("alias, canonical").execute().data or []
    return {r["alias"]: r["canonical"] for r in rows}


def validate(
    merges: list[_Merge], counts: Counter, existing: dict[str, str] | None = None
) -> list[_Merge]:
    """Keep only merges that are safe to apply as written: aliases that exist,
    none already merged, none claimed twice, and no chains — tag_aliases must
    stay flat (its trigger refuses chains), across this batch and the merges
    already in the table."""
    existing = existing or {}
    kept: list[_Merge] = []
    claimed: set[str] = set()
    # A kept tag that's already merged away is followed to where it went.
    resolved = [
        (existing.get(normalise_tag(m.canonical), normalise_tag(m.canonical)), m) for m in merges
    ]
    canonicals = {c for c, _ in resolved} | set(existing.values())
    for canonical, m in resolved:
        aliases = []
        for a in m.aliases:
            a = normalise_tag(a)
            if (
                a
                and a != canonical
                and a in counts
                and a not in claimed
                and a not in canonicals
                and a not in existing
            ):
                aliases.append(a)
                claimed.add(a)
        if canonical and aliases:
            kept.append(_Merge(canonical=canonical, aliases=aliases, reason=m.reason))
    return kept


def _sql(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def render(merges: list[_Merge], counts: Counter) -> tuple[str, str]:
    md = [
        f"# Proposed tag merges ({len(merges)} groups, "
        f"{sum(len(m.aliases) for m in merges)} tags merged)",
        "",
        "| Keep | Merge into it | Why |",
        "|---|---|---|",
    ]
    sql = [
        "-- Reviewed tag merges (proposed by api/propose_tag_merges.py).",
        "insert into public.tag_aliases (alias, canonical) values",
    ]
    values = []
    for m in sorted(merges, key=lambda m: -counts.get(m.canonical, 0)):
        merged = ", ".join(f"{a} ({counts[a]})" for a in m.aliases)
        md.append(f"| {m.canonical} ({counts.get(m.canonical, 0)}) | {merged} | {m.reason} |")
        values += [f"    ({_sql(a)}, {_sql(m.canonical)})" for a in m.aliases]
    # No "on conflict": validate() leaves out aliases already in the table, so a
    # conflict means the table changed since — fail loudly rather than overwrite.
    sql.append(",\n".join(values) + ";")
    sql += ["", "select * from public.apply_tag_cleanup();", ""]
    return "\n".join(md) + "\n", "\n".join(sql)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=Path("."), help="where to write the files")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    svc = service_client()
    counts = collect_tags(svc)
    print(f"{len(counts)} distinct tags")
    merges = validate(propose(counts, settings), counts, existing_aliases(svc))
    if not merges:
        print("No merges proposed.")
        return
    md, sql = render(merges, counts)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "tag-merges.md").write_text(md)
    (args.out_dir / "tag-merges.sql").write_text(sql)
    print(f"{len(merges)} groups → {args.out_dir / 'tag-merges.md'} and tag-merges.sql")


if __name__ == "__main__":
    main()
