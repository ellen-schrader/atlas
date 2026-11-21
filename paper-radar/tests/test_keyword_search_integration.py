"""Keyword search (search_papers over prefix_tsquery), end to end against a real
(local) Supabase.

Issue #193: a paper's own title found nothing, because "the" brought in its
British/American alternatives (theatre, theater, …) after to_tsquery had
dropped "the" itself as a stopword. Stopwords now bring no alternatives;
other words still find both spellings.

Opt-in, because it creates (and removes) rows in the database:

    ATLAS_INTEGRATION=1 uv run --extra api --extra dev \\
        pytest tests/test_keyword_search_integration.py
"""

from __future__ import annotations

import os
import uuid

import pytest

if os.environ.get("ATLAS_INTEGRATION") != "1":
    pytest.skip("set ATLAS_INTEGRATION=1 to run (needs local Supabase)", allow_module_level=True)

from supabase import create_client  # noqa: E402
from tests.local_supabase import LOCAL_URL, SERVICE  # noqa: E402

TITLE = "Conservation of the tumour microenvironment across organs and species"


@pytest.fixture(scope="module")
def world():
    admin = create_client(LOCAL_URL, SERVICE)
    tag = uuid.uuid4().hex[:8]
    team = str(uuid.uuid4())
    paper = str(uuid.uuid4())
    user = admin.auth.admin.create_user(
        {"email": f"kw-{tag}@example.test", "password": uuid.uuid4().hex, "email_confirm": True}
    ).user.id
    try:
        admin.table("teams").insert(
            {"id": team, "name": f"Keyword lab {tag}", "slug": f"kw-{tag}", "created_by": user}
        ).execute()
        admin.table("team_members").insert(
            {"team_id": team, "user_id": user, "role": "owner"}
        ).execute()
        admin.table("papers").insert(
            {
                "id": paper,
                "url": f"https://keyword.test/{tag}",
                "url_norm": f"keyword-{tag}",
                "title": TITLE,
                "abstract": "Fibroblasts and immune cells in human and mouse tumours.",
            }
        ).execute()
        admin.table("paper_posts").insert(
            {"paper_id": paper, "team_id": team, "posted_by": user, "source": "web"}
        ).execute()
        yield {"admin": admin, "team": team, "paper": paper}
    finally:
        admin.table("teams").delete().eq("id", team).execute()
        admin.table("papers").delete().eq("id", paper).execute()
        admin.auth.admin.delete_user(user)


def _found(world, q: str) -> bool:
    args = {"p_team": world["team"], "p_q": q}
    rows = world["admin"].rpc("search_papers", args).execute().data
    count = world["admin"].rpc("search_papers_count", args).execute().data
    ids = {r["paper_id"] for r in rows}
    assert len(ids) == count  # the "N results" label agrees with the list
    return world["paper"] in ids


def test_the_stopwords_have_longer_listed_words(world):
    # The precondition for the bug: without the VarCon load (a local stack built
    # from another branch), "the" brings no alternatives and the tests below
    # would pass with or without the fix.
    for word, alt in (("the", "theatre"), ("for", "formalise")):
        alts = world["admin"].rpc("spelling_matches", {"p_word": word}).execute().data
        assert alt in {a["alt"] for a in alts}


@pytest.mark.parametrize(
    "q",
    [
        TITLE,  # the issue: the full title
        "conservation of the tumour",
        "the tumour",
        "microenvironment for organs",  # "for" also has listed longer words (formalise)
    ],
)
def test_stopwords_do_not_hide_the_paper(world, q):
    assert _found(world, q)


@pytest.mark.parametrize("q", ["the", "for", "of the"])
def test_a_query_of_only_stopwords_filters_nothing(world, q):
    # Typing "for" on the way to "formalin" shows the lab's papers, not "No papers".
    assert _found(world, q)


def test_other_spellings_still_match(world):
    assert _found(world, "tumor microenvironment")
    assert _found(world, "tumou")


def test_a_missing_word_still_excludes(world):
    assert not _found(world, "conservation of the theatre")
