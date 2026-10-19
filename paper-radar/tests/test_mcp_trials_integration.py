"""The clinical trials tools on the hosted connector, end to end against a local
Supabase (real OAuth connector tokens, the real API process).

    ATLAS_INTEGRATION=1 uv run --extra api --extra mcp --extra dev \\
        pytest tests/test_mcp_trials_integration.py

Two labs, each with a member connected through Claude: the Ali-like lab has
clinical trials switched on, the other doesn't. The other lab's member must not
see the tools at all, nor be able to call them by name, nor reach the first
lab's trials; the database lockdown must still refuse connector tokens on the
trial tables directly.
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

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

import httpx  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

from atlas_mcp.trials import TRIAL_TOOL_NAMES  # noqa: E402
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

PASSWORD = "mcp-trials-test-only"
ROOT = Path(__file__).resolve().parents[1]

EXTRACTION = {
    "pico": {
        "population": "Early TNBC",
        "intervention": "IO + chemo",
        "comparator": "Chemo",
        "outcome": "pCR",
    },
    "design": {
        "phase": "Phase III",
        "randomisation_ratio": "1:1",
        "blinding": "double-blind",
        "analysis_population": "Intention-to-treat",
        "data_cutoff": None,
        "source": {"doc": 1, "where": "Table 1", "page": None},
    },
    "arms": [],
    "schedule": [],
    "endpoints": [
        {
            "name": "pCR",
            "role": "primary",
            "kind": "rate",
            "definition": "ypT0/is ypN0",
            "timepoint": None,
            "exp_value": 58.0,
            "ctrl_value": 41.0,
            "difference": 17.0,
            "difference_ci_low": None,
            "difference_ci_high": None,
            "hr": None,
            "hr_ci_low": None,
            "hr_ci_high": None,
            "events": None,
            "median_followup_months": None,
            "p_value": None,
            "source": None,
        }
    ],
    "adverse_events": [],
    "enrolment": {
        "n_screened": 455,
        "n_randomised": 333,
        "n_analysed": 333,
        "dimensions": [],
        "source": None,
    },
    "context": [],
    "caveats": None,
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _member(admin, marker: str, team: str, with_trials: bool) -> tuple[str, str]:
    """A user in `team`, connected through Claude: (user id, connector token)."""
    email = f"{marker}-{uuid.uuid4().hex[:6]}@example.test"
    user_id = httpx.post(
        f"{AUTH}/admin/users",
        headers=admin,
        json={"email": email, "password": PASSWORD, "email_confirm": True},
    ).json()["id"]
    httpx.post(
        f"{REST}/teams",
        headers=admin,
        json={
            "id": team,
            "name": f"Lab {marker}",
            "slug": f"{marker}-{team[:6]}",
            "created_by": user_id,
        },
    ).raise_for_status()
    httpx.post(
        f"{REST}/team_members",
        headers=admin,
        json={"team_id": team, "user_id": user_id, "role": "owner"},
    ).raise_for_status()
    if with_trials:
        httpx.post(
            f"{REST}/team_features",
            headers=admin,
            json={"team_id": team, "feature": "clinical_trials"},
        ).raise_for_status()
    web = httpx.post(
        f"{AUTH}/token?grant_type=password",
        headers={"apikey": ANON},
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]
    httpx.post(
        f"{REST}/rpc/set_mcp_access", headers=bearer(web), json={"p_team": team, "p_enabled": True}
    ).raise_for_status()
    connector, _client_id = connector_token(web)
    return user_id, connector


@pytest.fixture(scope="module")
def world():
    if not oauth_server_on():
        pytest.skip("local Supabase OAuth server is off ([auth.oauth_server] in config.toml)")
    admin = bearer(SERVICE)
    marker = f"mcptrials{uuid.uuid4().hex[:6]}"
    on_team, off_team, trial_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    nct = f"NCT9{uuid.uuid4().int % 10**7:07d}"
    users: list[str] = []
    port = _free_port()
    server = None
    try:
        on_user, on_token = _member(admin, marker, on_team, with_trials=True)
        off_user, off_token = _member(admin, marker, off_team, with_trials=False)
        users += [on_user, off_user]
        httpx.post(
            f"{REST}/trials",
            headers=admin,
            json={
                "id": trial_id,
                "nct_id": nct,
                "acronym": f"TRIAL-{marker}",
                "title": "A breast cancer trial",
                "registry": {},
                "breast_cancer": True,
            },
        ).raise_for_status()
        httpx.post(
            f"{REST}/trial_posts",
            headers=admin,
            json={"trial_id": trial_id, "team_id": on_team, "source": "paper"},
        ).raise_for_status()

        env = {
            **os.environ,
            "SUPABASE_URL": LOCAL_URL,
            "SUPABASE_ANON_KEY": ANON,
            "SUPABASE_SERVICE_ROLE_KEY": SERVICE,
            "MCP_PUBLIC_URL": f"http://127.0.0.1:{port}",
            "VOYAGE_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
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
            "on": on_token,
            "off": off_token,
            "on_team": on_team,
            "off_team": off_team,
            "trial_id": trial_id,
            "nct": nct,
        }
    finally:
        if server:
            server.terminate()
            server.wait(timeout=10)
        for team in (on_team, off_team):
            httpx.delete(f"{REST}/teams?id=eq.{team}", headers=admin)
        httpx.delete(f"{REST}/trials?id=eq.{trial_id}", headers=admin)
        for user in users:
            httpx.delete(f"{AUTH}/admin/users/{user}", headers=admin)


def _session(world, token: str, calls: list[tuple[str, dict]]):
    """(tool names, [(is_error, text)]) over one MCP connection as `token`."""

    async def run():
        async with streamablehttp_client(
            world["url"], headers={"Authorization": f"Bearer {token}"}
        ) as (
            r,
            w,
            _,
        ):
            async with ClientSession(r, w) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                out = []
                for name, args in calls:
                    res = await session.call_tool(name, args)
                    out.append((res.isError, res.content[0].text if res.content else ""))
                return names, out

    return asyncio.run(run())


def test_a_lab_without_the_feature_never_sees_the_tools(world):
    names, [(err, text)] = _session(world, world["off"], [("list_lab_trials", {})])
    assert not names & TRIAL_TOOL_NAMES
    assert err and "Unknown tool" in text


def test_the_lab_with_the_feature_reads_its_trials(world):
    names, [(_, listing), (_, one)] = _session(
        world, world["on"], [("list_lab_trials", {}), ("get_trial", {"trial": world["nct"]})]
    )
    assert TRIAL_TOOL_NAMES <= names
    assert world["nct"] in listing and world["nct"] in one
    assert "No extracted data yet" in one


def test_it_cant_reach_another_labs_trials(world):
    _names, [(_, text)] = _session(
        world, world["on"], [("get_trial", {"trial": world["nct"], "team_id": world["off_team"]})]
    )
    assert text.startswith("Error:")


def test_recording_an_extraction_previews_then_saves(world):
    args = {"trial": world["nct"], "extraction": EXTRACTION}
    _names, [(_, preview), (_, saved)] = _session(
        world,
        world["on"],
        [("record_trial_extraction", args), ("record_trial_extraction", {**args, "confirm": True})],
    )
    assert "Nothing saved yet" in preview and "pCR 58.0 vs 41.0%" in preview
    assert saved.startswith("Saved."), saved
    row = httpx.get(
        f"{REST}/trial_facts?trial_id=eq.{world['trial_id']}&team_id=eq.{world['on_team']}"
        "&select=extraction_status,extraction_mode,extraction_cost_usd",
        headers=bearer(SERVICE),
    ).json()[0]
    assert row == {
        "extraction_status": "done",
        "extraction_mode": "claude",
        "extraction_cost_usd": 0,
    }
    # A second recording needs replace=true: it would clear the lab's checks.
    _names, [(_, again)] = _session(
        world, world["on"], [("record_trial_extraction", {**args, "confirm": True})]
    )
    assert "already has extracted data" in again


def test_connector_tokens_still_cant_touch_trial_tables_directly(world):
    r = httpx.get(f"{REST}/trials?select=id", headers=bearer(world["on"]))
    assert r.status_code == 403
