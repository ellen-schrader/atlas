"""Cross-lab isolation, end to end against a real (local) Supabase.

Two labs, one member each, with papers whose embeddings are nearly identical — so
any scoping bug would surface the other lab's papers at the top of every ranking.
Both users then run every read tool *concurrently* in one process, the way the
hosted server will. Neither may ever see the other lab's papers, ids or name.

Opt-in, because it creates (and removes) users in the database:

    ATLAS_INTEGRATION=1 uv run --extra mcp --extra dev \
        pytest tests/test_mcp_isolation_integration.py

It refuses to run against anything but a local Supabase (127.0.0.1 / localhost).
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid

import pytest

pytest.importorskip("mcp")

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

from api import embeddings  # noqa: E402
from api.config import get_api_settings  # noqa: E402
from atlas_mcp import lab, papers  # noqa: E402
from supabase import create_client  # noqa: E402

# The standard local-stack demo keys (`supabase status`) — never a real project's.
LOCAL_URL = os.environ.get("ATLAS_IT_SUPABASE_URL", "http://127.0.0.1:54321")
ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24i"
    "LCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)
SERVICE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZp"
    "Y2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
PASSWORD = "isolation-test-only"
DIM = 1024

assert LOCAL_URL.startswith(("http://127.0.0.1", "http://localhost")), "local Supabase only"


def _vec(seed: int) -> list[float]:
    """A unit vector very close to every other `_vec` — maximally confusable."""
    rng = random.Random(seed)
    v = [1.0] + [rng.uniform(-0.01, 0.01) for _ in range(DIM - 1)]
    s = sum(x * x for x in v) ** 0.5
    return [x / s for x in v]


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


class Lab:
    def __init__(self, tag: str) -> None:
        self.tag = tag  # "A" / "B"
        self.marker = f"ISOLATION-{tag}-{uuid.uuid4().hex[:8]}"
        self.team_id = str(uuid.uuid4())
        self.name = f"Isolation Lab {tag} {self.marker}"
        self.email = f"isolation-{tag.lower()}-{uuid.uuid4().hex[:8]}@example.test"
        self.paper_ids = [str(uuid.uuid4()) for _ in range(3)]
        self.user_id = ""
        self.token = ""

    def forbidden(self) -> list[str]:
        """Strings that must never appear in the *other* lab's tool output."""
        return [self.marker, self.team_id, *self.paper_ids]


@pytest.fixture(scope="module")
def labs():
    admin = create_client(LOCAL_URL, SERVICE)
    a, b = Lab("A"), Lab("B")
    try:
        for i, L in enumerate((a, b)):
            user = admin.auth.admin.create_user(
                {"email": L.email, "password": PASSWORD, "email_confirm": True}
            ).user
            L.user_id = user.id
            admin.table("teams").insert(
                {
                    "id": L.team_id,
                    "name": L.name,
                    "slug": f"iso-{L.marker.lower()}",
                    "created_by": L.user_id,
                }
            ).execute()
            admin.table("team_members").insert(
                {"team_id": L.team_id, "user_id": L.user_id, "role": "owner"}
            ).execute()
            for j, pid in enumerate(L.paper_ids):
                admin.table("papers").insert(
                    {
                        "id": pid,
                        "url": f"https://example.test/{L.marker}/{j}",
                        "url_norm": f"{L.marker}-{j}".lower(),
                        "title": f"{L.marker} isolation study {j}",
                        "abstract": f"Spatial isolation abstract {L.marker}.",
                        "authors": [f"Author {L.tag}{j}", "Second Author"],
                        "embedding": _vec_literal(_vec(i * 10 + j)),
                    }
                ).execute()
                admin.table("paper_posts").insert(
                    {"paper_id": pid, "team_id": L.team_id, "posted_by": L.user_id, "source": "web"}
                ).execute()
            # Reading history, so recommend_reading takes its personalised path.
            admin.table("paper_status").insert(
                {
                    "paper_id": L.paper_ids[0],
                    "team_id": L.team_id,
                    "user_id": L.user_id,
                    "status": "read",
                }
            ).execute()
            anon = create_client(LOCAL_URL, ANON)
            L.token = anon.auth.sign_in_with_password(
                {"email": L.email, "password": PASSWORD}
            ).session.access_token
            # As the owner, the way the web app's Connect screen does it.
            create_client(
                LOCAL_URL,
                ANON,
                options=lab.ClientOptions(headers={"Authorization": f"Bearer {L.token}"}),
            ).rpc("set_mcp_access", {"p_team": L.team_id, "p_enabled": True}).execute()
        yield a, b
    finally:
        for L in (a, b):
            # Deleting the lab cascades to mcp_access and mcp_tool_calls, which the
            # service role deliberately can't touch directly.
            for table, col in (
                ("paper_status", "team_id"),
                ("paper_posts", "team_id"),
                ("team_members", "team_id"),
                ("teams", "id"),
            ):
                admin.table(table).delete().eq(col, L.team_id).execute()
            admin.table("papers").delete().in_("id", L.paper_ids).execute()
            if L.user_id:
                admin.auth.admin.delete_user(L.user_id)


@pytest.fixture(autouse=True)
def _local_settings(monkeypatch):
    """Point the data layer at the local stack (api/.env may name a real project), as
    the hosted server would: no environment user, a fake query embedder."""
    monkeypatch.setenv("SUPABASE_URL", LOCAL_URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    get_api_settings.cache_clear()
    reset = lab._env_session_allowed.set(False)
    monkeypatch.setattr(embeddings, "embed_query", lambda text, **_: _vec(999))
    yield
    lab._env_session_allowed.reset(reset)
    get_api_settings.cache_clear()


def _run_every_read_tool(me: Lab, other: Lab) -> dict[str, str]:
    """Each read tool as `me`; returns {label: output}."""
    with lab.act_as(me.token, me.user_id):
        out = {
            "list_labs": papers.list_labs(),
            "search keyword": papers.search_lab_papers("isolation study"),
            "search semantic": papers.search_lab_papers("isolation study", mode="semantic"),
            "recent": papers.list_recent_papers(limit=50),
            "recommend": papers.recommend_reading(limit=50),
            "similar": papers.similar_papers(me.paper_ids[0], limit=50),
            "digest": papers.lab_digest(days=7),
            "novelty": papers.novelty_check(text="spatial isolation"),
            "related work": papers.draft_related_work(topic="isolation", limit=20),
            "get own": papers.get_paper(me.paper_ids[1]),
            # Reaching for the other lab, explicitly:
            "get other": papers.get_paper(other.paper_ids[0]),
            "search other lab": papers.search_lab_papers("isolation", team_id=other.team_id),
            "similar other": papers.similar_papers(other.paper_ids[0]),
            "recent other lab": papers.list_recent_papers(team_id=other.team_id),
        }
    return out


REACHING = ("get other", "search other lab", "similar other", "recent other lab")


def _assert_isolated(me: Lab, other: Lab, out: dict[str, str], check_own: bool = True) -> None:
    for label, text in out.items():
        # A refusal may echo back the id the caller passed in; it must not add any of
        # the other lab's data (its marker is in every title, abstract and its name).
        forbidden = [other.marker] if label in REACHING else other.forbidden()
        for s in forbidden:
            assert s not in text, f"{me.tag} saw {other.tag}'s {s!r} via {label}:\n{text}"
    if not check_own:
        return
    # And the tools really did return this lab's own data (not just errors).
    for label in (
        "list_labs",
        "search keyword",
        "search semantic",
        "recent",
        "similar",
        "digest",
        "novelty",
        "related work",
        "get own",
    ):
        assert me.marker in out[label], f"{label} returned no {me.tag} data:\n{out[label]}"
    for label in REACHING:
        assert out[label].startswith("Error:"), f"{label} wasn't refused:\n{out[label]}"


def test_each_lab_sees_only_itself(labs):
    a, b = labs
    _assert_isolated(a, b, _run_every_read_tool(a, b))
    _assert_isolated(b, a, _run_every_read_tool(b, a))


def test_isolation_holds_under_concurrency(labs):
    """Both users hammering one server at once — the hosted server's normal day.

    Driven through FastMCP's own call path with the tools as registered (each served
    from a worker thread), and `act_as` entered per task the way the auth layer will:
    so a user lost between the request task and the tool's thread fails here too.
    """
    from mcp.server.fastmcp import FastMCP

    a, b = labs
    mcp = FastMCP("isolation")
    for t in papers.READ_TOOLS:
        mcp.add_tool(t)

    async def call(me: Lab, tool: str, args: dict) -> str:
        with lab.act_as(me.token, me.user_id):
            result = await mcp.call_tool(tool, args)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(getattr(c, "text", "") for c in blocks)

    def calls(me: Lab, other: Lab) -> list[tuple[Lab, Lab, str, str, dict]]:
        plan = [
            ("list_labs", "list_labs", {}),
            ("search keyword", "search_lab_papers", {"query": "isolation study"}),
            ("search semantic", "search_lab_papers", {"query": "isolation", "mode": "semantic"}),
            ("recent", "list_recent_papers", {"limit": 50}),
            ("recommend", "recommend_reading", {"limit": 50}),
            ("similar", "similar_papers", {"paper_id": me.paper_ids[0], "limit": 50}),
            ("digest", "lab_digest", {"days": 7}),
            ("novelty", "novelty_check", {"text": "spatial isolation"}),
            ("related work", "draft_related_work", {"topic": "isolation", "limit": 20}),
            ("get own", "get_paper", {"paper_id": me.paper_ids[1]}),
            ("get other", "get_paper", {"paper_id": other.paper_ids[0]}),
            (
                "search other lab",
                "search_lab_papers",
                {"query": "isolation", "team_id": other.team_id},
            ),
            ("similar other", "similar_papers", {"paper_id": other.paper_ids[0]}),
            ("recent other lab", "list_recent_papers", {"team_id": other.team_id}),
        ]
        return [(me, other, label, tool, args) for label, tool, args in plan]

    async def main() -> None:
        jobs = (calls(a, b) + calls(b, a)) * 3
        random.Random(0).shuffle(jobs)  # interleave the two users' calls
        outputs = await asyncio.gather(*(call(me, tool, args) for me, _, _, tool, args in jobs))
        by_user: dict[str, dict[str, str]] = {a.tag: {}, b.tag: {}}
        for (me, other, label, _, _), text in zip(jobs, outputs, strict=True):
            by_user[me.tag][label] = text
            _assert_isolated(me, other, {label: text}, check_own=False)
        _assert_isolated(a, b, by_user[a.tag])
        _assert_isolated(b, a, by_user[b.tag])

    asyncio.run(main())


def test_rpcs_refuse_another_labs_id_directly(labs):
    """The tools stop a foreign team_id in resolve_team — but a connector token can
    call these RPCs directly too, so each must scope by membership on its own."""
    a, b = labs
    client = create_client(
        LOCAL_URL, ANON, options=lab.ClientOptions(headers={"Authorization": f"Bearer {a.token}"})
    )
    vec = _vec(999)
    probes = {
        "search_papers": client.rpc(
            "search_papers", {"p_team": b.team_id, "p_q": "", "p_limit": 50}
        ),
        "match_papers": client.rpc(
            "match_papers", {"p_team": b.team_id, "p_query": vec, "p_limit": 50}
        ),
        "recommend_papers": client.rpc(
            "recommend_papers", {"p_team": b.team_id, "p_query": vec, "p_limit": 50}
        ),
        "similar_papers": client.rpc(
            "similar_papers", {"p_team": b.team_id, "p_paper": b.paper_ids[0], "p_limit": 50}
        ),
        "paper_posts": client.table("paper_posts").select("id").eq("team_id", b.team_id),
        "papers": client.table("papers").select("id").in_("id", b.paper_ids),
        "teams": client.table("teams").select("id").eq("id", b.team_id),
    }
    for name, query in probes.items():
        rows = query.execute().data or []
        assert rows == [], f"{name} returned lab B rows to lab A: {rows}"
