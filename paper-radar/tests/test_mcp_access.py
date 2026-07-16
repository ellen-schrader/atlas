"""The MCP access gate and audit log (offline — no Supabase needed).

These cover the parts that are easy to get subtly wrong and impossible to notice:
a refused call that logs as a success, or a call attributed to the wrong lab.
"""

from __future__ import annotations

import pytest

from atlas_mcp import lab, server


@pytest.fixture(autouse=True)
def _clean_context():
    lab.clear_team()
    yield
    lab.clear_team()


def test_error_returns_are_not_counted_as_success():
    """Tools return `f"Error: {exc}"` rather than raising, so an exception check
    alone would record a refused call as a success."""
    assert server._succeeded("**A paper**\nsome authors") is True
    assert server._succeeded("Error: Claude access is off for TME Lab.") is False
    assert server._succeeded(["image", "parts"]) is True  # get_figure_image returns a list


def test_audited_logs_the_resolved_lab(monkeypatch):
    calls: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        lab, "log_tool_call", lambda team, tool, ok: calls.append((team["id"], tool, ok))
    )

    @server.audited
    def a_tool():
        lab._current_team.set({"id": "team-1", "name": "TME Lab"})
        return "ok"

    a_tool()
    assert calls == [("team-1", "a_tool", True)]


def test_audited_records_a_refused_call_as_a_failure(monkeypatch):
    """A blocked attempt is the single most interesting row in an audit log — it must
    not be invisible, and it must not read as a success."""
    calls: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        lab, "log_tool_call", lambda team, tool, ok: calls.append((team["id"], tool, ok))
    )

    @server.audited
    def blocked_tool():
        # What resolve_team does: attribute first, then refuse.
        lab._current_team.set({"id": "team-1", "name": "TME Lab"})
        return "Error: Claude access is off for TME Lab."

    blocked_tool()
    assert calls == [("team-1", "blocked_tool", False)]


def test_audited_does_not_inherit_a_previous_calls_lab(monkeypatch):
    """Without clearing, a tool that resolves no lab would be logged against whatever
    the last call left in the contextvar — an audit trail that misattributes is worse
    than none."""
    logged: list[object] = []
    monkeypatch.setattr(lab, "log_tool_call", lambda team, tool, ok: logged.append(team))

    @server.audited
    def resolves_a_lab():
        lab._current_team.set({"id": "team-1", "name": "TME Lab"})
        return "ok"

    @server.audited
    def resolves_nothing():
        return "ok"

    resolves_a_lab()
    resolves_nothing()

    assert logged[0]["id"] == "team-1"
    assert logged[1] is None, "second call inherited the first call's lab"


def test_audited_preserves_the_tool_signature():
    """FastMCP builds each tool's JSON schema from its signature — if @audited hid it
    behind (*args, **kwargs), every tool would register with no parameters."""
    import inspect

    @server.audited
    def a_tool(query: str, limit: int = 10) -> str:
        return "ok"

    params = inspect.signature(a_tool).parameters
    assert list(params) == ["query", "limit"]
    assert params["limit"].default == 10
