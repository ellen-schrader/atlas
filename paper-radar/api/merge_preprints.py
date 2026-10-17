"""Merge preprints into their published papers, and DOI-case duplicates (service role).

Three passes over ``papers`` (after naming the server on bioRxiv/medRxiv rows
that have no venue), each folding a row into the one it duplicates with
the ``merge_papers`` SQL function (supabase/migrations/20261017120000_paper_aliases.sql),
which moves posts, comments, reactions and reading status across and leaves a
``paper_aliases`` row behind:

  1. **DOI-case duplicates** -- two rows whose DOIs differ only in case, which
     20260725100000_doi_casefold_rerun.sql had to skip. The row already holding
     the lowercase DOI is kept (that is what ``norm_doi`` looks up), else the
     older one.
  2. **Preprints with a stated published version** -- Crossref's
     ``is-preprint-of``, bioRxiv/medRxiv's publication API, or arXiv's journal
     DOI (``published_version``). Merged when that DOI is already in Atlas;
     otherwise reported, for the ingest changes in PR 2 to handle.
  3. **Probable pairs by title** -- a preprint and a non-preprint with the same
     title and first author's surname but no stated link. Only listed, never
     merged: a human checks them and merges with ``--pair OLD_ID NEW_ID``.

Writes nothing unless ``--apply`` is given. See docs/preprint-dedup-plan.md.

Usage (from paper-radar/, with api/.env configured):

    uv run python -m api.merge_preprints                  # report only
    uv run python -m api.merge_preprints --apply
    uv run python -m api.merge_preprints --apply --pair <preprint id> <published id>
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict

from paper_radar.ingest.metadata import (
    RXIV_DOI_PREFIXES,
    arxiv_id_for,
    crossref_venue,
    looks_like_preprint,
    published_version,
)
from paper_radar.ingest.urls import norm_doi

from .merge_suggestions import fold, surname
from .supa import service_client

_PAGE = 500


_COLUMNS = "id, doi, url, title, authors, venue, edited_fields, created_at"


def _fetch_papers(svc, columns: str = _COLUMNS) -> list[dict]:
    """Every paper's identifying fields, oldest first. Shared with api/preprint_watch.py."""
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("papers")
            .select(columns)
            # created_at alone ties (a Teams import inserts a batch with one now()),
            # and offset paging over ties can repeat one row and skip another.
            .order("created_at")
            .order("id")
            .range(start, start + _PAGE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < _PAGE:
            break
        start += _PAGE
    return rows


def is_preprint_row(row: dict) -> bool:
    """True if the stored row looks like a preprint: by DOI, venue or host."""
    return looks_like_preprint(row.get("doi"), row.get("url"), row.get("venue"))


def plan_case_merges(rows: list[dict]) -> list[tuple[str, str]]:
    """``(from_id, into_id)`` for every row whose DOI differs from another's only in case.

    Rows come oldest first. The kept row is the one whose DOI is already the
    lowercase ``norm_doi`` form -- ingest looks DOIs up lowercased, so that is
    the row new posts find -- or failing that, the oldest.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("doi"):
            groups[norm_doi(row["doi"])].append(row)
    merges = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        keep = next((r for r in group if r["doi"] == key), group[0])
        merges.extend((r["id"], keep["id"]) for r in group if r is not keep)
    return merges


def title_key(row: dict) -> tuple[str, str] | None:
    """Normalised (title, first author's surname), or None if either is missing.

    Accents and punctuation are dropped and case folded, so "Single-cell" and
    "Single cell" agree; journals retitle papers often enough that this misses
    some pairs, which is acceptable for a list a person reviews.

    The surname is the last word that is not an initial, so Crossref's
    "Jane Doe", "J. Doe" and PubMed's "Doe J" all give "doe".
    """
    title = row.get("title") or ""
    authors = row.get("authors") or []
    if not title.strip() or not authors:
        return None
    first = surname(authors[0])
    return (fold(title), first) if first else None


def find_title_pairs(preprints: list[dict], rows: list[dict]) -> list[tuple[dict, dict]]:
    """``(preprint, published)`` pairs sharing a title key, preprint side first."""
    published_by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        if not is_preprint_row(row) and (key := title_key(row)):
            published_by_key[key].append(row)
    pairs = []
    for pre in preprints:
        if key := title_key(pre):
            pairs.extend((pre, pub) for pub in published_by_key.get(key, []))
    return pairs


def _merge(svc, from_id: str, into_id: str, reason: str) -> bool:
    """Merge one pair; on failure print why and carry on with the rest."""
    try:
        svc.rpc(
            "merge_papers", {"p_from": from_id, "p_into": into_id, "p_reason": reason}
        ).execute()
    except Exception as exc:  # noqa: BLE001 -- one bad pair must not stop the run
        print(f"  ! merge failed, left as is: {from_id} -> {into_id}: {exc}")
        return False
    return True


def _label(row: dict) -> str:
    return f"{row['id']} {str(row.get('title') or row.get('url'))[:70]}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="merge; without it, only report")
    parser.add_argument("--limit", type=int, help="look up at most this many preprints")
    parser.add_argument(
        "--delay", type=float, default=0.2, help="seconds after a Crossref/bioRxiv lookup"
    )
    parser.add_argument(
        "--arxiv-delay", type=float, default=3.0, help="seconds after an arXiv lookup (its rule)"
    )
    parser.add_argument(
        "--pair",
        nargs=2,
        metavar=("PREPRINT_ID", "PUBLISHED_ID"),
        help="merge this one reviewed pair (reason 'manual') and stop",
    )
    args = parser.parse_args(argv)
    verb = "merged" if args.apply else "would merge"
    svc = service_client()

    def merge(from_id: str, into_id: str, reason: str) -> bool:
        return _merge(svc, from_id, into_id, reason) if args.apply else True

    if args.pair:
        if merge(args.pair[0], args.pair[1], "manual"):
            print(f"{verb}: {args.pair[0]} -> {args.pair[1]}")
        return

    rows = _fetch_papers(svc)
    by_id = {r["id"]: r for r in rows}
    failed = 0

    # 0. bioRxiv/medRxiv rows without a venue: they share DOI prefixes, so the
    #    migration that named the other servers (20261017130000) left these for
    #    Crossref, which names the server.
    unnamed = [
        r
        for r in rows
        if not (r.get("venue") or "").strip()
        and (r.get("doi") or "").lower().startswith(RXIV_DOI_PREFIXES)
        and "venue" not in (r.get("edited_fields") or [])
    ]
    if args.limit:
        unnamed = unnamed[: args.limit]
    named = 0
    print(f"0. bioRxiv/medRxiv preprints without a venue: {len(unnamed)}")
    for row in unnamed:
        venue = crossref_venue(row["doi"])
        time.sleep(args.delay)
        if not venue:
            continue
        if args.apply:
            svc.table("papers").update({"venue": venue}).eq("id", row["id"]).is_(
                "venue", "null"
            ).execute()
        row["venue"] = venue
        named += 1
    print(f"  {'named' if args.apply else 'would name'} {named}")

    # 1. DOI-case duplicates first, so pass 2's lowercase lookups find the kept rows.
    case_merges = plan_case_merges(rows)
    print(f"1. DOI-case duplicates: {len(case_merges)}")
    merged_away: set[str] = set()
    for from_id, into_id in case_merges:
        if not merge(from_id, into_id, "doi_case"):
            failed += 1
            continue
        merged_away.add(from_id)
        print(f"  {verb}: {_label(by_id[from_id])}\n      into {_label(by_id[into_id])}")
    rows = [r for r in rows if r["id"] not in merged_away]

    # 2. Preprints whose published version is stated somewhere.
    by_doi = {norm_doi(r["doi"]): r for r in rows if r.get("doi")}
    preprints = [r for r in rows if is_preprint_row(r)]
    if args.limit:
        preprints = preprints[: args.limit]
    print(f"2. Preprints to look up: {len(preprints)}")
    merged = not_in_atlas = holds_journal_doi = 0
    # Settled rows skip the title pass. "Published, but not in Atlas" is not
    # settled: the journal version may be here under no DOI, or another one.
    settled: set[str] = set()
    for i, row in enumerate(preprints, 1):
        doi, url = row.get("doi"), row.get("url")
        if not (doi or arxiv_id_for(doi, url)):
            continue
        found = published_version(doi, url)
        time.sleep(args.arxiv_delay if arxiv_id_for(doi, url) else args.delay)
        if found is None:
            continue
        published_doi, reason = found
        owner = by_doi.get(norm_doi(published_doi))
        if owner is None:
            not_in_atlas += 1
            print(f"  [{i}] published as {published_doi}, not in Atlas: {_label(row)}")
        elif owner["id"] == row["id"]:
            # An arXiv row already holding the journal DOI (see _fetch_arxiv).
            settled.add(row["id"])
            holds_journal_doi += 1
            print(f"  [{i}] arXiv row holds its journal DOI {published_doi}: {_label(row)}")
        elif merge(row["id"], owner["id"], reason):
            settled.add(row["id"])
            merged += 1
            print(f"  [{i}] {verb} ({reason}): {_label(row)}\n      into {_label(owner)}")
        else:
            failed += 1

    # 3. Same title and first author, but nothing states the link.
    unsettled = [r for r in preprints if r["id"] not in settled]
    pairs = find_title_pairs(unsettled, rows)
    print(f"3. Probable pairs by title, for review (merge with --pair): {len(pairs)}")
    for pre, pub in pairs:
        print(f"  {_label(pre)}\n      and {_label(pub)}")

    print(
        f"Done. venues-named={named} case-duplicates {verb}={len(merged_away)} "
        f"preprints {verb}={merged} "
        f"failed={failed} published-not-in-atlas={not_in_atlas} "
        f"arxiv-holding-journal-doi={holds_journal_doi} title-pairs-to-review={len(pairs)}"
    )
    if args.apply and (merged_away or merged):
        print(
            "Now run: uv run python -m api.backfill_embeddings && "
            "uv run python -m api.backfill_enrichment"
        )


if __name__ == "__main__":
    main()
