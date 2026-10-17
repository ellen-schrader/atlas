"""One paper, several identifiers: the lookups and preprint links ingest shares.

A paper is found by its url_norm, then its DOI, then a ``paper_aliases`` row --
what a merged-away duplicate or preprint was (20261017120000_paper_aliases.sql).
Every path that adds papers (web, BibTeX, Teams, the PDF importer, MCP) goes
through :func:`find_paper`, so a preprint posted after its merge lands on the
published paper instead of coming back as a new row.

A preprint whose published version exists is stored *as* that version
(:func:`swap_to_published`) and remembered as an alias, which the card shows as
a "Preprint" link. See docs/preprint-dedup-plan.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from paper_radar.ingest.metadata import PaperMetadata, preprint_server, published_record
from paper_radar.ingest.urls import _normalize_key, norm_doi

log = logging.getLogger(__name__)


@dataclass
class PreprintRef:
    """A preprint version of a paper: what an alias row records."""

    doi: str | None
    url: str | None
    venue: str | None
    reason: str  # "crossref" | "biorxiv" | "arxiv"


def _paper_by(svc, column: str, value: str | None, columns: str) -> dict | None:
    if not value:
        return None
    rows = svc.table("papers").select(columns).eq(column, value).limit(1).execute().data
    return rows[0] if rows else None


def _alias_target(svc, column: str, value: str | None) -> str | None:
    if not value:
        return None
    rows = svc.table("paper_aliases").select("paper_id").eq(column, value).limit(1).execute().data
    return rows[0]["paper_id"] if rows else None


def find_paper(svc, url_norm: str | None, doi: str | None, columns: str = "id") -> dict | None:
    """The paper these identifiers belong to: url_norm, then DOI, then an alias."""
    doi = norm_doi(doi)
    row = _paper_by(svc, "url_norm", url_norm, columns) or _paper_by(svc, "doi", doi, columns)
    if row:
        return row
    target = _alias_target(svc, "url_norm", url_norm) or _alias_target(svc, "doi", doi)
    return _paper_by(svc, "id", target, columns)


def swap_to_published(
    meta: PaperMetadata, url: str
) -> tuple[PaperMetadata, str, PreprintRef | None]:
    """The record to store for ``meta``: its published version, if it has one.

    Returns ``(meta, url, preprint)``. ``preprint`` is None and nothing changes
    for a paper that is not a preprint or has not been published; otherwise the
    published record and its doi.org URL come back, with the preprint that was
    posted, for :func:`link_preprints` to record and the poster to be told about.
    """
    found = published_record(meta)
    if found is None:
        return meta, url, None
    record, reason = found
    preprint = PreprintRef(doi=norm_doi(meta.doi), url=url, venue=meta.venue, reason=reason)
    return record, record.url, preprint


def preprint_refs(meta: PaperMetadata) -> list[PreprintRef]:
    """The preprints a published record names (Crossref's has-preprint)."""
    return [
        PreprintRef(doi=d, url=None, venue=preprint_server(d, None), reason="crossref")
        for d in meta.preprint_dois
    ]


def link_preprints(svc, paper_id: str, preprints: list[PreprintRef]) -> None:
    """Record each preprint of ``paper_id``, merging any that Atlas holds as a paper.

    Never raises: the paper is already stored, and a link that fails to record
    costs only the card's preprint link -- merge_preprints.py finds the pair later.
    """
    for ref in preprints:
        url_norm = _normalize_key(ref.url) if ref.url else None
        doi = norm_doi(ref.doi)
        try:
            row = _paper_by(svc, "url_norm", url_norm, "id") or _paper_by(svc, "doi", doi, "id")
            if row and row["id"] == paper_id:
                continue
            if row:
                svc.rpc(
                    "merge_papers",
                    {"p_from": row["id"], "p_into": paper_id, "p_reason": ref.reason},
                ).execute()
                continue
            if _alias_target(svc, "doi", doi) or _alias_target(svc, "url_norm", url_norm):
                continue
            svc.table("paper_aliases").insert(
                {
                    "paper_id": paper_id,
                    "kind": "preprint",
                    "reason": ref.reason,
                    "doi": doi,
                    "url": ref.url,
                    "url_norm": url_norm,
                    "venue": ref.venue,
                }
            ).execute()
        except Exception as exc:  # noqa: BLE001 -- see docstring
            log.warning(
                "linking preprint %s to paper %s failed: %s", ref.doi or ref.url, paper_id, exc
            )
