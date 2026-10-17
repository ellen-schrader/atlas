"""Daily: catch preprints that have been published, and tell the labs that hold them.

Runs on a GitHub Actions schedule (.github/workflows/preprint-watch.yml) with
the service role. For every preprint in Atlas it asks the sources that state a
link (Crossref, bioRxiv's API, arXiv; ``published_version``). When one names a
published version:

  * **already in Atlas** -> the preprint is merged into it (``merge_papers``);
  * **not in Atlas** -> the preprint becomes it, in place (``promote_to_published``):
    same id, so posts, comments and reading status stay; the preprint is kept
    as an alias and linked from the card. This also covers old arXiv rows that
    stored their journal DOI.

Either way, the people who held the preprint -- whoever posted it, and anyone
who saved it or started reading it -- get a notification in the bell, and labs
with Teams connected get a card. Then it records likely duplicate pairs
nothing links, for the labs to answer (api/merge_suggestions.py), and re-embeds
and re-tags what changed.

Usage (from paper-radar/, with the service role in the environment):

    uv run python -m api.preprint_watch --dry-run    # what it would do
    uv run python -m api.preprint_watch
"""

from __future__ import annotations

import argparse
import logging
import time

from paper_radar.ingest.metadata import (
    arxiv_id_for,
    crossref_record,
    looks_like_preprint,
    published_version,
)
from paper_radar.ingest.urls import _normalize_key, norm_doi

from . import merge_suggestions, teams_integration
from .supa import service_client

log = logging.getLogger(__name__)

_PAGE = 500
_PAPER_COLUMNS = "id, doi, url, title, authors, venue, year, created_at"


def _fetch_papers(svc) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("papers")
            .select(_PAPER_COLUMNS)
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


def published_patch(record) -> dict:
    """The fields promote_to_published writes, from a Crossref record."""
    doi = norm_doi(record.doi)
    return {
        "doi": doi,
        "url": record.url,
        "url_norm": _normalize_key(record.url),
        "title": record.title,
        "authors": record.authors,
        "venue": record.venue,
        "year": record.year,
        "abstract": record.abstract,
        "keywords": record.keywords,
        # The bibtex migration's "year only" marker, which the Papers sort reads.
        "published_at": f"{record.year}-01-01" if record.year else None,
        "metadata_source": "crossref",
    }


def recipients(svc, paper_id: str) -> dict[str, set[str]]:
    """``{team_id: {user_id}}``: who held this preprint, per lab.

    Whoever posted it, and anyone who saved it or started reading it -- people
    it mattered to, not the whole lab. Only current members: the bell is per
    lab, and a notice for a lab someone left would never show.
    """
    out: dict[str, set[str]] = {}
    posts = (
        svc.table("paper_posts")
        .select("team_id, posted_by")
        .eq("paper_id", paper_id)
        .execute()
        .data
        or []
    )
    for post in posts:
        out.setdefault(post["team_id"], set())
        if post.get("posted_by"):
            out[post["team_id"]].add(post["posted_by"])
    statuses = (
        svc.table("paper_status")
        .select("team_id, user_id, saved, status")
        .eq("paper_id", paper_id)
        .execute()
        .data
        or []
    )
    for st in statuses:
        if st["team_id"] in out and (st.get("saved") or st.get("status") != "unread"):
            out[st["team_id"]].add(st["user_id"])
    for team_id, users in out.items():
        if not users:
            continue
        members = (
            svc.table("team_members")
            .select("user_id")
            .eq("team_id", team_id)
            .in_("user_id", sorted(users))
            .execute()
            .data
            or []
        )
        out[team_id] = {m["user_id"] for m in members}
    return out


def notify(svc, who: dict[str, set[str]], paper_id: str, record, preprint_venue: str | None) -> int:
    """Bell notifications and Teams cards for one publication; returns how many people."""
    payload = {
        "title": record.title,
        "venue": record.venue,
        "year": record.year,
        "preprint_venue": preprint_venue,
    }
    rows = [
        {
            "user_id": user_id,
            "team_id": team_id,
            "paper_id": paper_id,
            "kind": "preprint_published",
            "payload": payload,
        }
        for team_id, users in who.items()
        for user_id in sorted(users)
    ]
    if rows:
        svc.table("notifications").upsert(
            rows, on_conflict="user_id,team_id,paper_id,kind", ignore_duplicates=True
        ).execute()
    for team_id in who:
        teams_integration.notify_preprint_published(
            team_id,
            paper_id=paper_id,
            url=record.url,
            title=record.title,
            authors=record.authors,
            venue=record.venue,
            year=record.year,
            preprint_venue=preprint_venue,
        )
    return len(rows)


def handle_preprint(svc, row: dict, by_doi: dict[str, dict], *, dry_run: bool) -> str | None:
    """Look one preprint up and act on what is found. Returns what happened."""
    found = published_version(row.get("doi"), row.get("url"))
    if found is None:
        return None
    published_doi, reason = found
    owner = by_doi.get(norm_doi(published_doi))
    label = f"{row['id']} {str(row.get('title'))[:60]}"

    if owner is not None and owner["id"] != row["id"]:
        record = crossref_record(published_doi) or _as_record(owner)
        if dry_run:
            print(f"  would merge ({reason}): {label} -> {owner['id']}")
            return "merge"
        who = recipients(svc, row["id"])
        svc.rpc(
            "merge_papers", {"p_from": row["id"], "p_into": owner["id"], "p_reason": reason}
        ).execute()
        n = notify(svc, who, owner["id"], record, row.get("venue"))
        print(f"  merged ({reason}): {label} -> {owner['id']}; told {n}")
        return "merge"

    record = crossref_record(published_doi)
    if record is None:
        print(f"  published as {published_doi}, but Crossref has no record yet: {label}")
        return None
    # An arXiv row that already holds its journal DOI keeps arXiv's as the alias.
    arxiv_id = arxiv_id_for(row.get("doi"), row.get("url"))
    preprint_doi = f"10.48550/arxiv.{arxiv_id.lower()}" if arxiv_id else None
    if dry_run:
        print(f"  would promote ({reason}) to {published_doi} ({record.venue}): {label}")
        return "promote"
    who = recipients(svc, row["id"])
    svc.rpc(
        "promote_to_published",
        {
            "p_paper": row["id"],
            "p_patch": published_patch(record),
            "p_reason": reason,
            "p_preprint_doi": preprint_doi,
        },
    ).execute()
    by_doi[norm_doi(published_doi)] = row
    n = notify(svc, who, row["id"], record, row.get("venue"))
    print(f"  promoted ({reason}) to {published_doi} ({record.venue}): {label}; told {n}")
    return "promote"


def _as_record(row: dict):
    """A stored paper standing in for its Crossref record, when Crossref has none."""
    from paper_radar.ingest.metadata import PaperMetadata

    return PaperMetadata(
        url=row.get("url") or "",
        title=row.get("title"),
        authors=row.get("authors") or [],
        venue=row.get("venue"),
        year=row.get("year"),
        doi=row.get("doi"),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("--limit", type=int, help="look up at most this many preprints")
    parser.add_argument("--delay", type=float, default=0.2, help="seconds after a lookup")
    parser.add_argument(
        "--arxiv-delay", type=float, default=3.0, help="seconds after an arXiv lookup (its rule)"
    )
    parser.add_argument("--no-backfill", action="store_true", help="skip re-embedding and tagging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    svc = service_client()
    rows = _fetch_papers(svc)
    by_doi = {norm_doi(r["doi"]): r for r in rows if r.get("doi")}
    preprints = [r for r in rows if looks_like_preprint(r.get("doi"), r.get("url"), r.get("venue"))]
    if args.limit:
        preprints = preprints[: args.limit]
    print(f"Preprints to look up: {len(preprints)}")

    done = {"merge": 0, "promote": 0}
    failed = 0
    for row in preprints:
        doi, url = row.get("doi"), row.get("url")
        if not (doi or arxiv_id_for(doi, url)):
            continue
        try:
            outcome = handle_preprint(svc, row, by_doi, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001 -- one bad paper must not stop the run
            failed += 1
            print(f"  ! {row['id']} failed, left as is: {exc}")
            outcome = None
        if outcome:
            done[outcome] += 1
        time.sleep(args.arxiv_delay if arxiv_id_for(doi, url) else args.delay)

    suggested = 0
    if not args.dry_run:
        teams = svc.table("teams").select("id").execute().data or []
        for team in teams:
            try:
                suggested += merge_suggestions.suggest(svc, team["id"])
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ! suggestions for team {team['id']} failed: {exc}")

    verb = "would" if args.dry_run else "did"
    print(
        f"Done ({verb}): merged={done['merge']} promoted={done['promote']} "
        f"likely-pairs={suggested} failed={failed}"
    )
    if not (args.dry_run or args.no_backfill) and (done["merge"] or done["promote"]):
        # Merged and promoted papers may have a new title or abstract.
        from . import backfill_embeddings, backfill_enrichment

        steps = ((backfill_embeddings.main, []), (backfill_enrichment.main, ["--batch-size", "5"]))
        for step, step_args in steps:
            try:
                step(step_args)
            except Exception as exc:  # noqa: BLE001 -- the next run retries
                failed += 1
                print(f"  ! {step.__module__} failed: {exc}")
    if failed:
        # Red in GitHub Actions, so a broken run is noticed; the next run retries.
        raise SystemExit(1)


if __name__ == "__main__":
    main()
