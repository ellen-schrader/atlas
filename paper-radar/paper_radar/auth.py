"""Email/password authentication and team membership.

Passwords are hashed with PBKDF2-SHA256 (stdlib only, no extra dependencies)
and stored as ``pbkdf2_sha256$<iterations>$<salt>$<hex digest>``. Signing up
with a team name that does not exist yet creates the team; otherwise the user
joins the existing team.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlmodel import select

from .db import get_session, init_db
from .models import Team, User

_PBKDF2_ITERATIONS = 240_000
_MIN_PASSWORD_LEN = 8


class AuthError(ValueError):
    """Signup/login failed for a reason the user should see."""


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def signup(
    name: str,
    email: str,
    password: str,
    team_name: str,
    db_url: str | None = None,
) -> User:
    """Create a user (and their team, if new). Raises :class:`AuthError` on bad input."""
    name, team_name = name.strip(), team_name.strip()
    email = email.strip().lower()
    if not (name and email and password and team_name):
        raise AuthError("All fields are required.")
    if "@" not in email:
        raise AuthError("Please enter a valid email address.")
    if len(password) < _MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {_MIN_PASSWORD_LEN} characters.")

    init_db(db_url)
    with get_session(db_url) as session:
        if session.get(User, email) is not None:
            raise AuthError("An account with this email already exists.")
        team = session.exec(select(Team).where(Team.name == team_name)).first()
        if team is None:
            team = Team(name=team_name)
            session.add(team)
            session.flush()  # populate team.id before referencing it
        user = User(
            id=email,
            name=name,
            password_hash=hash_password(password),
            team_id=team.id,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def login(email: str, password: str, db_url: str | None = None) -> User:
    """Return the matching user, or raise :class:`AuthError`."""
    email = email.strip().lower()
    init_db(db_url)
    with get_session(db_url) as session:
        user = session.get(User, email)
        # Users without a password hash (e.g. the legacy "lab" user) cannot log in.
        if user is None or not user.password_hash or not verify_password(
            password, user.password_hash
        ):
            raise AuthError("Invalid email or password.")
        return user


def get_team_name(team_id: int | None, db_url: str | None = None) -> str | None:
    if team_id is None:
        return None
    with get_session(db_url) as session:
        team = session.get(Team, team_id)
        return team.name if team else None
