"""The hosted connector, end to end: the real API process, a real OAuth token.

Starts `uvicorn api.app:app` with MCP_PUBLIC_URL pointing at it and the local
Supabase, then talks to it the way Claude does — the MCP SDK's own client over
Streamable HTTP with a connector token from the full OAuth flow:

  * unauthenticated → the 401 + protected-resource metadata that starts sign-in;
  * the web app's own token → refused;
  * a connector token → the 9 read tools, answering from its lab;
  * the API's own host is unaffected;
  * revoking the connection → the next tool call says so.

Opt-in, local only, and needs `[auth.oauth_server] enabled = true` in config.toml:

    ATLAS_INTEGRATION=1 uv run --extra api --extra mcp --extra dev \\
        pytest tests/test_mcp_http_integration.py
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("mcp")

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

import httpx  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

from atlas_mcp.papers import READ_TOOLS  # noqa: E402
from tests.local_supabase import (  # noqa: E402
    ANON,
    AUTH,
    LOCAL_URL,
    REST,
    SERVICE,
    bearer,
    connector_token,
    oauth_server_on,
)

PASSWORD = "mcp-http-test-only"
ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def world():
    if not oauth_server_on():
        pytest.skip("local Supabase OAuth server is off ([auth.oauth_server] in config.toml)")
    admin = bearer(SERVICE)
    marker = f"MCPHTTP-{uuid.uuid4().hex[:8]}"
    team_id, paper_id = str(uuid.uuid4()), str(uuid.uuid4())
    email = f"mcphttp-{uuid.uuid4().hex[:8]}@example.test"
    user_id = httpx.post(
        f"{AUTH}/admin/users",
        headers=admin,
        json={"email": email, "password": PASSWORD, "email_confirm": True},
    ).json()["id"]
    port = _free_port()
    server = None
    try:
        for table, row in (
            (
                "teams",
                {
                    "id": team_id,
                    "name": f"Lab {marker}",
                    "slug": marker.lower(),
                    "created_by": user_id,
                },
            ),
            ("team_members", {"team_id": team_id, "user_id": user_id, "role": "owner"}),
            (
                "papers",
                {
                    "id": paper_id,
                    "url": f"https://example.test/{marker}",
                    "url_norm": marker.lower(),
                    "title": f"{marker} stromal study",
                    "authors": ["A One"],
                },
            ),
            (
                "paper_posts",
                {"paper_id": paper_id, "team_id": team_id, "posted_by": user_id, "source": "web"},
            ),
        ):
            httpx.post(f"{REST}/{table}", headers=admin, json=row).raise_for_status()
        web = httpx.post(
            f"{AUTH}/token?grant_type=password",
            headers={"apikey": ANON},
            json={"email": email, "password": PASSWORD},
        ).json()["access_token"]
        httpx.post(
            f"{REST}/rpc/set_mcp_access",
            headers=bearer(web),
            json={"p_team": team_id, "p_enabled": True},
        ).raise_for_status()
        connector, client_id = connector_token(web)

        # The real API process, serving the connector on 127.0.0.1 (the API itself
        # answers on any other host name, e.g. localhost). Env beats api/.env, so this
        # never touches a real project — and no Voyage key, so nothing is spent.
        env = {
            **os.environ,
            "SUPABASE_URL": LOCAL_URL,
            "SUPABASE_ANON_KEY": ANON,
            "SUPABASE_SERVICE_ROLE_KEY": SERVICE,
            "MCP_PUBLIC_URL": f"http://127.0.0.1:{port}",
            "VOYAGE_API_KEY": "",
        }
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.app:app", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for _ in range(100):
            try:
                if httpx.get(f"http://localhost:{port}/health").status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            server.kill()
            raise RuntimeError(server.stderr.read().decode()[-2000:])
        yield {
            "url": f"http://127.0.0.1:{port}/mcp",
            "api": f"http://localhost:{port}",
            "issuer": AUTH,
            "web": web,
            "connector": connector,
            "client_id": client_id,
            "paper_id": paper_id,
            "marker": marker,
        }
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
        httpx.delete(f"{REST}/teams?id=eq.{team_id}", headers=admin)
        httpx.delete(f"{REST}/papers?id=eq.{paper_id}", headers=admin)
        httpx.delete(f"{AUTH}/admin/users/{user_id}", headers=admin)


def _call(world, token: str, calls: list[tuple[str, dict]]) -> tuple[set[str], list[str]]:
    """List the tools and make `calls` over one MCP connection, as the given token."""

    async def run():
        headers = {"Authorization": f"Bearer {token}"}
        async with streamablehttp_client(world["url"], headers=headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                texts = []
                for name, args in calls:
                    result = await session.call_tool(name, args)
                    texts.append(result.content[0].text)
                return names, texts

    return asyncio.run(run())


def test_unauthenticated_callers_are_sent_to_sign_in(world):
    r = httpx.post(
        world["url"],
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 401
    meta_url = r.headers["www-authenticate"].split('resource_metadata="')[1].rstrip('"')
    meta = httpx.get(meta_url).json()
    assert [s.rstrip("/") for s in meta["authorization_servers"]] == [world["issuer"]]


def test_the_web_apps_own_token_is_refused(world):
    r = httpx.post(
        world["url"],
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={
            "accept": "application/json, text/event-stream",
            "authorization": f"Bearer {world['web']}",
        },
    )
    assert r.status_code == 401


def test_a_connector_token_gets_the_read_tools_answering_from_its_lab(world):
    names, (recent, paper, search) = _call(
        world,
        world["connector"],
        [
            ("list_recent_papers", {}),
            ("get_paper", {"paper_id": world["paper_id"]}),
            ("search_lab_papers", {"query": "stromal"}),
        ],
    )
    assert names == {t.__name__ for t in READ_TOOLS}
    for text in (recent, paper, search):
        assert world["paper_id"] in text, text


def test_the_api_host_is_unaffected(world):
    assert httpx.get(f"{world['api']}/health").status_code == 200
    assert httpx.post(f"{world['api']}/mcp").status_code == 404  # no MCP on the API host


def test_revoking_shows_up_on_the_next_call(world):
    """Runs last in this module: it revokes the connection the others use."""
    httpx.delete(
        f"{AUTH}/user/oauth/grants",
        params={"client_id": world["client_id"]},
        headers=bearer(world["web"]),
    ).raise_for_status()
    _, (text,) = _call(world, world["connector"], [("list_recent_papers", {})])
    assert text.startswith("Error:") and "revoked" in text, text
