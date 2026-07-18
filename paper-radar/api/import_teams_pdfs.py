"""Bulk-import papers from Teams-exported PDFs into a lab (service role).

Poster/date attribution from these exports is unreliable — mixed timestamp
formats (some without a year) and long single-page captures smear one stamp
across many unrelated links (see the ingest troubleshooting). So every post is
recorded as ``posted_by_label='Unknown'`` with ``posted_at`` derived from the
PDF *filename* date-window, which is reliable and matches the in-doc dates:

    0903_2303.pdf  ->  window starts 09/03  ->  2026-03-09

Year rule: months 1–7 are 2026, months 8–12 are 2025 (the export period ends
mid-2026, so an autumn/winter file belongs to the prior year — this also avoids
future-dating). Override the base year with --year.

Only URLs whose metadata resolves as a real paper (a title or DOI) are kept, so
social/code/demo links are dropped. Idempotent: re-runs skip papers already
posted into the team.

Target DB + Voyage come from env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
embedding is a separate step (`python -m api.backfill_embeddings`).

Usage (from paper-radar/):
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
      uv run python -m api.import_teams_pdfs <pdf_dir> --team-slug ali-lab [--dry-run]
"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from paper_radar.ingest.metadata import fetch_metadata
from paper_radar.ingest.pdf_extract import extract_urls_from_dir  # needs the `legacy` extra
from paper_radar.ingest.urls import _clean_url, _normalize_key, is_skip_host
from supabase import Client, create_client

from .config import get_api_settings


def window_date(filename: str, base_year: int) -> datetime | None:
    """Start-of-window datetime from a ``DDMM_DDMM`` (or ``DMM``) filename stem.

    Year: months 1–7 → ``base_year``; months 8–12 → ``base_year - 1``.
    """
    stem = filename.rsplit(".", 1)[0]
    token = stem.split("_", 1)[0]
    if not token.isdigit() or len(token) < 3:
        return None
    day, month = int(token[:-2]), int(token[-2:])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = base_year if month <= 7 else base_year - 1
    try:
        return datetime(year, month, day, 12, 0, tzinfo=UTC)
    except ValueError:
        return None


def _team_id(svc: Client, slug: str) -> str:
    rows = svc.table("teams").select("id").eq("slug", slug).limit(1).execute().data
    if not rows:
        raise SystemExit(f"No team with slug {slug!r} on the target database.")
    return rows[0]["id"]


def _upsert_paper(svc: Client, meta, url: str, url_norm: str) -> str:
    """Find the canonical paper (by url_norm, then DOI) or insert it. Returns its id."""
    found = svc.table("papers").select("id").eq("url_norm", url_norm).limit(1).execute()
    if found.data:
        return found.data[0]["id"]
    if meta.doi:
        by_doi = svc.table("papers").select("id").eq("doi", meta.doi).limit(1).execute()
        if by_doi.data:
            return by_doi.data[0]["id"]
    row = {
        "url": url,
        "url_norm": url_norm,
        "doi": meta.doi,
        "title": meta.title,
        "authors": meta.authors,
        "abstract": meta.abstract,
        "venue": meta.venue,
        "year": meta.year,
        "keywords": meta.keywords,
        "metadata_source": meta.source,
    }
    try:
        return svc.table("papers").insert(row).execute().data[0]["id"]
    except Exception:
        again = svc.table("papers").select("id").eq("url_norm", url_norm).limit(1).execute()
        if again.data:
            return again.data[0]["id"]
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf_dir", help="Directory of Teams-exported PDFs")
    parser.add_argument("--team-slug", required=True, help="Target lab slug, e.g. ali-lab")
    parser.add_argument("--year", type=int, default=2026, help="Base year for filename dates")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between lookups")
    parser.add_argument("--dry-run", action="store_true", help="Resolve + report, write nothing")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N URLs (0=all)")
    args = parser.parse_args(argv)

    s = get_api_settings()
    svc = create_client(s.supabase_url, s.supabase_service_role_key)
    team_id = _team_id(svc, args.team_slug)

    items = extract_urls_from_dir(args.pdf_dir)
    if args.limit:
        items = items[: args.limit]
    print(f"{len(items)} URLs from {args.pdf_dir} → team {args.team_slug} ({team_id[:8]})")

    posted = skipped_host = skipped_unresolved = already = failed = 0
    for n, item in enumerate(items, 1):
        if is_skip_host(item.url):
            skipped_host += 1
            continue

        posted_at = window_date(item.source_pdf.rsplit("/", 1)[-1], args.year)
        url = _clean_url(item.url)
        url_norm = _normalize_key(url)
        try:
            meta = fetch_metadata(url)
        except Exception:
            failed += 1
            continue
        if not (meta.title or meta.doi):
            skipped_unresolved += 1
            continue

        if args.dry_run:
            posted += 1
            if posted <= 15:
                print(f"  [{posted}] {str(posted_at)[:10]}  {(meta.title or url)[:60]}")
            time.sleep(args.delay)
            continue

        paper_id = _upsert_paper(svc, meta, url, url_norm)
        exists = (
            svc.table("paper_posts")
            .select("id")
            .eq("team_id", team_id)
            .eq("paper_id", paper_id)
            .limit(1)
            .execute()
        )
        if exists.data:
            already += 1
        else:
            svc.table("paper_posts").insert(
                {
                    "paper_id": paper_id,
                    "team_id": team_id,
                    "posted_by": None,
                    "posted_by_label": "Unknown",
                    "posted_at": (posted_at or datetime.now(UTC)).isoformat(),
                    "source": "teams_pdf",
                    "source_pdf": item.source_pdf.rsplit("/", 1)[-1],
                    "page": item.page,
                    "via": item.via,
                }
            ).execute()
            posted += 1
        if n % 25 == 0:
            print(f"  {n}/{len(items)}  posted={posted} dup={already} "
                  f"skip_host={skipped_host} skip_unresolved={skipped_unresolved} fail={failed}")
        time.sleep(args.delay)

    verb = "would post" if args.dry_run else "posted"
    print(
        f"\nDone. {verb}={posted}  already={already}  "
        f"skipped_host={skipped_host}  skipped_unresolved={skipped_unresolved}  failed={failed}"
    )
    if not args.dry_run:
        print("Next: embed the new papers →  uv run python -m api.backfill_embeddings")


if __name__ == "__main__":
    main()
