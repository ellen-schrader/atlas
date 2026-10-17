"""Atlas MCP server over stdio — every tool, acting as the user in ``api/.env``.

Mostly read; ``post_paper`` and ``add_plot_to_moodboard`` write (both preview
unless confirmed).

Run over stdio (the transport Claude Code / Claude for Life Sciences use):

    uv run --directory paper-radar --extra mcp python -m atlas_mcp

Access is lab-wide and owner-controlled: `lab.resolve_team` refuses a lab that
hasn't opted in, and every call is logged to `mcp_tool_calls` where the whole lab
can see it. See supabase/migrations/20260713090000_mcp_access.sql.

All logging goes to stderr; stdout carries JSON-RPC only.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from . import lab
from .figures import FIGURE_TOOLS
from .papers import READ_TOOLS, WRITE_TOOLS

# stderr only — a single stray write to stdout would corrupt the JSON-RPC stream.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("atlas_mcp")

mcp = FastMCP("atlas")
for _tool in READ_TOOLS + WRITE_TOOLS + FIGURE_TOOLS:
    mcp.add_tool(_tool)


def main() -> None:
    """Entry point: serve over stdio, as the one user configured in ``api/.env``."""
    lab.allow_env_session()
    log.info("Atlas MCP server starting (stdio)")
    mcp.run()


if __name__ == "__main__":
    main()
