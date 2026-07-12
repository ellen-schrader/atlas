"""Atlas MCP server — exposes the lab paper database to Claude over MCP.

A thin stdio MCP adapter over the same Supabase (JWT + RLS) access the FastAPI
service uses. See docs/CLAUDE_INTEGRATION_PLAN.md. Named ``atlas_mcp`` (not
``mcp``) so it never shadows the ``mcp`` SDK package.
"""
