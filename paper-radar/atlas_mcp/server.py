"""Atlas MCP server — read-only tools over the lab paper database + mood board.

Run over stdio (the transport Claude Code / Claude for Life Sciences use):

    uv run --directory paper-radar --extra mcp python -m atlas_mcp

All logging goes to stderr; stdout carries JSON-RPC only.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP, Image

from api import embeddings

from . import lab, moodboard

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


# --- mood board -----------------------------------------------------------


def _format_figure(f: dict) -> str:
    """A figure as a text block: title, caption, meta, and origin/provenance."""
    lines = [f"**{f.get('title') or '(untitled figure)'}**  [{f['id']}]"]
    if f.get("caption"):
        lines.append(f["caption"])
    meta = []
    if f.get("category"):
        meta.append(f"category: {f['category']}")
    if f.get("tags"):
        meta.append("tags: " + ", ".join(f["tags"]))
    uploader = (f.get("uploader") or {}).get("display_name")
    if uploader:
        meta.append(f"by {uploader}")
    if meta:
        lines.append(" · ".join(meta))

    if f.get("origin") == "third_party":
        prov = []
        if f.get("attribution"):
            prov.append(f["attribution"])
        paper = f.get("papers")
        if paper and paper.get("title"):
            prov.append(paper["title"])
        if f.get("source_url"):
            prov.append(f["source_url"])
        if f.get("license"):
            prov.append(f"licence: {f['license']}")
        tail = f" ({'; '.join(prov)})" if prov else ""
        lines.append(
            "third-party — derive style/palette only, attribute the source, "
            "don't reproduce the figure." + tail
        )
    else:
        lines.append("own — the lab's unpublished work; treat as confidential.")
    return "\n".join(lines)


@mcp.tool()
def list_moodboard(
    category: str | None = None,
    tag: str | None = None,
    origin: str | None = None,
    mine_only: bool = False,
    limit: int = 20,
    team_id: str | None = None,
) -> str:
    """List the lab's mood-board figures (inspirational images), newest first.

    Args:
        category: Filter to a category (see moodboard_categories).
        tag: Filter to a tag.
        origin: Filter to "own" or "third_party".
        mine_only: Only figures you uploaded.
        limit: Maximum number of results (1-50).
        team_id: Which lab, if you belong to more than one.
    """
    try:
        team = lab.resolve_team(team_id)
        figs = moodboard.list_figures(
            team,
            category=category,
            tag=tag,
            origin=origin or None,
            mine_only=mine_only,
            limit=_clamp(limit),
        )
    except lab.LabError as exc:
        return f"Error: {exc}"
    if not figs:
        return f"No figures on {team['name']}'s mood board match that."
    return "\n\n".join(_format_figure(f) for f in figs)


@mcp.tool()
def moodboard_categories(team_id: str | None = None) -> str:
    """List the categories used on the lab's mood board, with counts."""
    try:
        team = lab.resolve_team(team_id)
        cats = moodboard.categories(team)
    except lab.LabError as exc:
        return f"Error: {exc}"
    if not cats:
        return f"{team['name']} has no categorised figures yet."
    return "\n".join(f"- {c['category']} ({c['n']})" for c in cats)


@mcp.tool()
def get_figure_image(figure_id: str, team_id: str | None = None) -> list:
    """Fetch a mood-board figure's image so you can see it, plus its details.

    Use this to match a plotting style to a specific figure. Returns the image
    and a text block (title, caption, origin, provenance). For third-party
    figures, derive style only and attribute the source — don't reproduce it.

    Args:
        figure_id: The figure's id (from list_moodboard).
        team_id: Which lab, if you belong to more than one.
    """
    try:
        team = lab.resolve_team(team_id)
        fig = moodboard.get_figure(team, figure_id)
        png, _, _ = moodboard.downscale_png(moodboard.download(fig))
    except lab.LabError as exc:
        return [f"Error: {exc}"]
    return [_format_figure(fig), Image(data=png, format="png")]


@mcp.tool()
def get_figure_palette(figure_id: str, n: int = 6, team_id: str | None = None) -> str:
    """Extract a mood-board figure's dominant colours as hex, for matching a palette.

    Args:
        figure_id: The figure's id (from list_moodboard).
        n: Number of colours (2-12).
        team_id: Which lab, if you belong to more than one.
    """
    try:
        team = lab.resolve_team(team_id)
        fig = moodboard.get_figure(team, figure_id)
        hexes = moodboard.palette(moodboard.download(fig), n=max(2, min(int(n), 12)))
    except lab.LabError as exc:
        return f"Error: {exc}"
    return f"Palette for “{fig.get('title') or fig['id']}”: " + ", ".join(hexes)


def main() -> None:
    """Entry point: serve over stdio."""
    log.info("Atlas MCP server starting (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
