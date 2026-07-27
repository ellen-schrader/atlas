"""Compute + persist a map layout in an ephemeral process (issue #103).

The serving API never imports scikit-learn: on a layout miss it spawns

    python -m api.layout_job lab <team_id>
    python -m api.layout_job map <map_id>

which fetches the paper set fresh (service role), runs t-SNE + KMeans via
``overview.compute_layout`` (the only process that ever imports sklearn),
persists the coordinates to ``map_layouts``, and exits — so the ~300 MB the
sklearn import keeps resident never lands in the always-on serving process.

Idempotent by construction: the layout is deterministic for a signature
(fixed seeds) and the job skips signatures already persisted, so duplicate,
concurrent, or suspend-interrupted runs are harmless — the next viewer's miss
just spawns it again. Cluster *names* are persisted by ``compute_layout``
itself (the existing signature-keyed ``trends`` path), so a completed job
leaves nothing for serving to compute.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from . import overview as ov
from .layout_store import load_layout, store_layout
from .maps import MAP_MEMBER_LIMIT
from .supa import service_client

log = logging.getLogger(__name__)

_PAGE = 500

# The paper fields the layout needs: id + embedded_at form the signature,
# embedding feeds t-SNE/KMeans, title feeds cluster naming.
_JOB_COLS = "paper_id, papers(id, title, embedding, embedded_at)"


def _embedded_papers(rows: list[dict]) -> list[dict]:
    """The joined papers that have an embedding, in the same deterministic order
    as app._build_overview — the signatures must agree or serving never hits."""
    papers = [r["papers"] for r in rows if r.get("papers") and r["papers"].get("embedding")]
    papers.sort(key=lambda p: p["id"])
    return papers


def _fetch_lab_papers(svc, team_id: str) -> list[dict]:
    """Every embedded paper posted to the lab (paged; stable order)."""
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            svc.table("paper_posts")
            .select(_JOB_COLS)
            .eq("team_id", team_id)
            .order("id")
            .range(start, start + _PAGE - 1)
            .execute()
            .data
            or []
        )
        if not page:
            return _embedded_papers(rows)
        rows.extend(page)
        start += len(page)


def _fetch_map_papers(svc, map_id: str) -> tuple[str, list[dict]]:
    """(team_id, embedded member papers) for a map — the same member set the
    serving endpoint uses (map_members RPC at the same limit)."""
    maps = svc.table("maps").select("id, team_id").eq("id", map_id).limit(1).execute().data or []
    if not maps:
        raise SystemExit(f"no such map: {map_id}")
    team_id = maps[0]["team_id"]
    members = (
        svc.rpc("map_members", {"p_map": map_id, "p_limit": MAP_MEMBER_LIMIT}).execute().data
        or []
    )
    member_ids = [m["paper_id"] for m in members]
    if not member_ids:
        return team_id, []
    rows = (
        svc.table("paper_posts")
        .select(_JOB_COLS)
        .eq("team_id", team_id)
        .in_("paper_id", member_ids)
        .execute()
        .data
        or []
    )
    return team_id, _embedded_papers(rows)


def compute_and_store(team_id: str, papers: list[dict], *, force: bool = False) -> str:
    """Compute this paper set's layout and persist it; returns what happened
    ("empty" | "skipped" | "stored"). The heavy imports happen inside
    ``compute_layout``, never at module level, so importing this module (the
    serving process does, for :func:`spawn`) stays sklearn-free."""
    if not papers:
        return "empty"
    signature = ov._signature(papers)
    if not force and load_layout(team_id, signature) is not None:
        return "skipped"
    point_by_id, _clusters = ov.compute_layout(team_id, papers)
    store_layout(team_id, signature, point_by_id)
    return "stored"


def spawn(mode: str, target_id: str) -> subprocess.Popen:
    """Fire-and-forget recompute in a child process (stdio inherited, so its
    logs land in the API's stream). The caller dedupes; the job itself is
    idempotent, so a stray duplicate only wastes a few seconds of CPU."""
    return subprocess.Popen([sys.executable, "-m", "api.layout_job", mode, target_id])


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="layout_job: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("lab", "map"))
    parser.add_argument("target_id", help="team id (lab mode) or map id (map mode)")
    parser.add_argument("--force", action="store_true", help="recompute even if persisted")
    args = parser.parse_args(argv)

    svc = service_client()
    if args.mode == "lab":
        team_id, papers = args.target_id, _fetch_lab_papers(svc, args.target_id)
    else:
        team_id, papers = _fetch_map_papers(svc, args.target_id)
    result = compute_and_store(team_id, papers, force=args.force)
    log.info("%s %s: %s (%d papers)", args.mode, args.target_id, result, len(papers))


if __name__ == "__main__":
    main()
