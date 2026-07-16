"""Shared FastAPI dependencies.

Kept out of ``app.py`` so routers (e.g. ``maps.py``) can depend on the same token
extraction without importing the app module and creating a cycle.
"""

from __future__ import annotations

from fastapi import Header, HTTPException


def require_token(authorization: str | None = Header(default=None)) -> str:
    """Extract the bearer token from the Authorization header (401 if absent)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1]
