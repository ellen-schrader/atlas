"""Atlas MCP server — read-only tools over the lab paper database (P1).

Run over stdio (the transport Claude Code / Claude for Life Sciences use):

    uv run --directory paper-radar --extra mcp python -m atlas_mcp

All logging goes to stderr; stdout carries JSON-RPC only.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from api import embeddings

from . import lab

# stderr only — a single stray write to stdout would corrupt the JSON-RPC stream.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("atlas_mcp")

mcp = FastMCP("atlas")


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), 50))


def _format_hit(h: dict) -> str:
    """One paper as a citation-ready block: title, authors, venue/year, DOI, link."""
    p = h["paper"]
    lines = [f"**{p.get('title') or p.get('url')}**"]
    authors = ", ".join(p.get("authors") or [])
    if authors:
        lines.append(authors)
    meta = " · ".join(str(x) for x in (p.get("venue"), p.get("year")) if x)
    if meta:
        lines.append(meta)
    if p.get("doi"):
        lines.append(f"doi:{p['doi']}")
    lines.append(lab.paper_link(p["id"]))
    if h.get("similarity") is not None:
        lines.append(f"similarity {h['similarity']:.3f}")
    tags = h.get("tags") or []
    if tags:
        lines.append("tags: " + ", ".join(tags))
    return "\n".join(lines)


def _render(hits: list[dict], empty: str) -> str:
    if not hits:
        return empty
    return "\n\n".join(_format_hit(h) for h in hits)


@mcp.tool()
def list_labs() -> str:
    """List the labs (teams) you belong to in Atlas, with their ids and join codes."""
    try:
        teams = lab.list_teams()
    except lab.LabError as exc:
        return f"Error: {exc}"
    if not teams:
        return "You don't belong to any lab."
    return "\n".join(f"- {t['name']} — id {t['id']}, join code {t['slug']}" for t in teams)


@mcp.tool()
def search_lab_papers(
    query: str, mode: str = "keyword", limit: int = 10, team_id: str | None = None
) -> str:
    """Search your lab's posted papers and return citation-ready results.

    Args:
        query: Free-text search terms.
        mode: "keyword" for full-text search, or "semantic" for embedding
            similarity (needs the embedding service configured).
        limit: Maximum number of results (1-50).
        team_id: Which lab to search, if you belong to more than one.
    """
    try:
        team = lab.resolve_team(team_id)
        hits = lab.search(team, query.strip(), mode, _clamp(limit))
    except embeddings.EmbeddingError as exc:
        return f"Semantic search is unavailable ({exc}). Try mode=\"keyword\"."
    except lab.LabError as exc:
        return f"Error: {exc}"
    return _render(hits, f"No papers in {team['name']} match {query!r}.")


@mcp.tool()
def list_recent_papers(limit: int = 10, team_id: str | None = None) -> str:
    """List the most recently posted papers in your lab.

    Args:
        limit: Maximum number of results (1-50).
        team_id: Which lab, if you belong to more than one.
    """
    try:
        team = lab.resolve_team(team_id)
        hits = lab.recent(team, _clamp(limit))
    except lab.LabError as exc:
        return f"Error: {exc}"
    return _render(hits, f"No papers posted in {team['name']} yet.")


@mcp.tool()
def get_paper(paper_id: str, team_id: str | None = None) -> str:
    """Get full details for one paper posted in your lab, including its abstract.

    Args:
        paper_id: The paper's id (as returned by the search tools).
        team_id: Which lab, if you belong to more than one.
    """
    try:
        team = lab.resolve_team(team_id)
        hit = lab.get_post(team, paper_id)
    except lab.LabError as exc:
        return f"Error: {exc}"
    block = _format_hit(hit)
    abstract = hit["paper"].get("abstract")
    note = hit.get("note")
    parts = [block, "", "Abstract:", abstract or "(no abstract available)"]
    if note:
        parts += ["", f"Lab note: “{note}”"]
    return "\n".join(parts)


def main() -> None:
    """Entry point: serve over stdio."""
    log.info("Atlas MCP server starting (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
