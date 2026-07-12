"""Tests for signup/login and team membership."""

from __future__ import annotations

import pytest

from paper_radar.auth import AuthError, get_team_name, hash_password, login, signup, verify_password

# The in-memory engine is cached per-URL, so all tests in a run share it;
# use distinct emails/teams per test.
INMEM = "sqlite://"


def test_password_hash_roundtrip():
    stored = hash_password("hunter2hunter2")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("hunter2hunter2", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("anything", "")  # legacy users can't log in


def test_signup_creates_team_and_login_works():
    user = signup("Ada", "Ada@Example.org", "correct horse", "TME Lab", db_url=INMEM)
    assert user.id == "ada@example.org"  # email normalized
    assert user.team_id is not None
    assert get_team_name(user.team_id, db_url=INMEM) == "TME Lab"

    got = login("ada@example.org", "correct horse", db_url=INMEM)
    assert got.id == user.id

    with pytest.raises(AuthError):
        login("ada@example.org", "wrong", db_url=INMEM)
    with pytest.raises(AuthError):
        login("nobody@example.org", "correct horse", db_url=INMEM)


def test_signup_joins_existing_team():
    first = signup("Bea", "bea@example.org", "password-1", "Shared Lab", db_url=INMEM)
    second = signup("Cid", "cid@example.org", "password-2", "Shared Lab", db_url=INMEM)
    assert first.team_id == second.team_id


def test_signup_rejects_duplicates_and_bad_input():
    signup("Dee", "dee@example.org", "long enough", "Dee Lab", db_url=INMEM)
    with pytest.raises(AuthError):
        signup("Dee again", "dee@example.org", "long enough", "Dee Lab", db_url=INMEM)
    with pytest.raises(AuthError):
        signup("Eve", "eve@example.org", "short", "Eve Lab", db_url=INMEM)
    with pytest.raises(AuthError):
        signup("", "fay@example.org", "long enough", "Fay Lab", db_url=INMEM)
    with pytest.raises(AuthError):
        signup("Gus", "not-an-email", "long enough", "Gus Lab", db_url=INMEM)
