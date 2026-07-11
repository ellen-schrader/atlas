"""Supabase clients for the API.

Two access levels:
  * ``service_client()`` — service-role key, bypasses RLS. Used to write the
    global ``papers`` corpus, which users may not write directly.
  * ``user_client(token)`` — anon key with the caller's JWT attached, so RLS
    applies. Used to insert ``paper_posts`` as that user (enforces membership).
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from .config import get_api_settings


@lru_cache
def service_client() -> Client:
    s = get_api_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


@lru_cache
def _anon_client() -> Client:
    s = get_api_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)


def get_user_id(access_token: str) -> str | None:
    """Validate a Supabase access token and return its user id, or None."""
    try:
        resp = _anon_client().auth.get_user(access_token)
    except Exception:
        return None
    return resp.user.id if resp and resp.user else None


def user_client(access_token: str) -> Client:
    """A client that acts as the given user, so RLS applies to its writes."""
    s = get_api_settings()
    client = create_client(s.supabase_url, s.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
