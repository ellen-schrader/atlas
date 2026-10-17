"""Who a tool call acts as, once one server process serves many users (offline).

The hosted server binds each request's user with `lab.act_as`. These pin down the
ways that could go wrong silently: a request seeing another request's user, a
request with no user falling back to the environment's, or a "refresh" that signs
in as somebody else.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("mcp")

from atlas_mcp import lab  # noqa: E402


@pytest.fixture(autouse=True)
def _hosted(monkeypatch):
    """Hosted-server defaults: no environment user, and a fake client per token."""
    reset = lab._env_session_allowed.set(False)
    monkeypatch.setattr(lab, "_user_client", lambda token: f"client-for-{token}")
    yield
    lab._env_session_allowed.reset(reset)


def test_no_bound_user_fails_closed(monkeypatch):
    """A hosted call without a user must not quietly act as whoever is in api/.env."""
    monkeypatch.setattr(lab, "_env_session", lambda: pytest.fail("used the env user"))
    with pytest.raises(lab.LabError, match="Not signed in"):
        lab.current_user_id()
    with pytest.raises(lab.LabError):
        lab.get_client()


def test_stdio_uses_the_env_user_once_allowed(monkeypatch):
    monkeypatch.setattr(lab, "_env_session", lambda: ("env-client", "env-user"))
    lab.allow_env_session()
    assert lab.current_user_id() == "env-user"


def test_act_as_binds_for_the_block_only():
    with lab.act_as("tok-a", "user-a"):
        assert lab.current_user_id() == "user-a"
        assert lab.get_client() == "client-for-tok-a"
        with lab.act_as("tok-b", "user-b"):
            assert lab.current_user_id() == "user-b"
        assert lab.current_user_id() == "user-a"
    with pytest.raises(lab.LabError):
        lab.current_user_id()


def test_act_as_unbinds_even_when_the_tool_raises():
    with pytest.raises(RuntimeError):
        with lab.act_as("tok-a", "user-a"):
            raise RuntimeError("tool blew up")
    with pytest.raises(lab.LabError):
        lab.current_user_id()


def test_concurrent_requests_each_see_their_own_user():
    """Interleave many requests at every await point; none may see another's user."""
    seen: list[tuple[str, str]] = []

    async def request(user: str) -> None:
        with lab.act_as(f"tok-{user}", user):
            for _ in range(5):
                await asyncio.sleep(0)  # hand the loop to the other requests
                seen.append((user, lab.current_user_id()))

    async def main() -> None:
        await asyncio.gather(*(request(f"user-{i}") for i in range(20)))

    asyncio.run(main())
    assert len(seen) == 100
    assert all(expected == actual for expected, actual in seen)


def test_threads_each_see_their_own_user():
    """Same, for tool bodies run in worker threads."""
    barrier = threading.Barrier(8)
    mismatches: list[tuple[str, str]] = []

    def worker(user: str) -> None:
        with lab.act_as(f"tok-{user}", user):
            barrier.wait()  # everyone is bound at once
            got = lab.current_user_id()
            if got != user:
                mismatches.append((user, got))

    threads = [threading.Thread(target=worker, args=(f"user-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert mismatches == []


def test_with_refresh_never_signs_in_again_for_a_hosted_request(monkeypatch):
    """An expired caller token must surface as a clean, actionable error — re-signing
    in could only mean signing in as the environment's user, and a raw PostgREST 401
    would escape the tools (they only catch LabError)."""
    monkeypatch.setattr(lab, "_env_session", lambda: pytest.fail("signed in as the env user"))
    calls = {"n": 0}

    @lab.with_refresh
    def read():
        calls["n"] += 1
        raise RuntimeError("JWT expired")

    with lab.act_as("tok-a", "user-a"):
        with pytest.raises(lab.LabError, match="expired — reconnect"):
            read()
    assert calls["n"] == 1


def test_with_refresh_still_retries_for_stdio(monkeypatch):
    lab.allow_env_session()
    calls = {"n": 0}

    @lab.with_refresh
    def read():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("JWT expired")
        return "ok"

    assert read() == "ok"
    assert calls["n"] == 2


def test_hosted_caller_ignores_the_env_default_lab(monkeypatch):
    """ATLAS_TEAM_ID is the stdio user's setting; for a hosted caller in two labs it
    must not silently pick one."""
    monkeypatch.setenv("ATLAS_TEAM_ID", "lab-b")
    lab.get_atlas_settings.cache_clear()
    monkeypatch.setattr(
        lab, "list_teams", lambda: [{"id": "lab-a", "name": "A"}, {"id": "lab-b", "name": "B"}]
    )
    try:
        with lab.act_as("tok-a", "user-a"):
            with pytest.raises(lab.LabError, match="multiple labs"):
                lab._pick_team(None)
        lab.allow_env_session()
        assert lab._pick_team(None)["id"] == "lab-b"  # stdio still honours it
    finally:
        lab.get_atlas_settings.cache_clear()


def test_rate_limit_is_per_user():
    """One user hitting the cap must not lock out everyone else on the server."""
    rl = lab._RateLimiter(max_events=2, window_seconds=100)
    rl.check("user-a", now=0)
    rl.check("user-a", now=1)
    with pytest.raises(lab.LabError):
        rl.check("user-a", now=2)
    rl.check("user-b", now=2)  # unaffected


def test_env_permission_does_not_leak_into_other_contexts():
    """allow_env_session switches on the env user for the stdio server's own context
    only; a context started elsewhere in the process stays fail-closed."""
    import contextvars

    outside = contextvars.copy_context()  # taken before the stdio server switches it on
    lab.allow_env_session()
    assert outside.run(lab._env_session_allowed.get) is False


def test_worker_thread_tools_run_as_the_bound_user():
    """Tools are served from worker threads; the request's user must come along."""
    from atlas_mcp.tools import in_worker_thread

    tool = in_worker_thread(lambda: lab.current_user_id())

    async def request(user: str) -> str:
        with lab.act_as(f"tok-{user}", user):
            return await tool()

    async def main() -> list[str]:
        return await asyncio.gather(*(request(f"user-{i}") for i in range(20)))

    assert asyncio.run(main()) == [f"user-{i}" for i in range(20)]


def test_threaded_tools_keep_their_schema():
    """Wrapping must not change a tool's name or parameters as clients see them."""
    from mcp.server.fastmcp import FastMCP

    from atlas_mcp.papers import READ_TOOLS

    mcp = FastMCP("t")
    for t in READ_TOOLS:
        mcp.add_tool(t)
    tool = mcp._tool_manager.get_tool("search_lab_papers")
    assert tool.is_async
    assert list(tool.parameters["properties"]) == ["query", "mode", "limit", "team_id"]


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("ATLAS_CONNECTOR_REVOKED", "This Claude connection has been revoked."),
        ("ATLAS_CONNECTOR_FORBIDDEN", "Claude connections can only read papers."),
    ],
)
def test_connector_gate_refusals_reach_the_user_cleanly(code, message):
    """The database gate's refusals arrive as PostgREST errors; tools only catch
    LabError, so they must be translated — with the gate's own wording."""

    class GateError(Exception):
        def __init__(self) -> None:
            super().__init__(message)
            self.code, self.message = code, message

    @lab.with_refresh
    def read():
        raise GateError()

    with lab.act_as("tok-a", "user-a"):
        with pytest.raises(lab.LabError, match=message):
            read()


def test_access_check_passes_gate_refusals_through_cleanly(monkeypatch):
    """require_access wraps its own errors ("Could not check Claude access…"); a gate
    refusal must still read as the gate's message, not a dict dumped into that."""

    class GateError(Exception):
        code, message = "ATLAS_CONNECTOR_REVOKED", "This Claude connection has been revoked."

    class Query:
        def __getattr__(self, _name):
            return lambda *a, **k: self

        def execute(self):
            raise GateError()

    class Client:
        def table(self, _name):
            return Query()

    monkeypatch.setattr(lab, "_user_client", lambda token: Client())
    with lab.act_as("tok-a", "user-a"):
        with pytest.raises(lab.LabError) as info:
            lab.require_access({"id": "t", "name": "Lab A"})
    assert str(info.value) == "This Claude connection has been revoked."
