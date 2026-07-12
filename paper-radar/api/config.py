"""API settings — Supabase connection, read from env / api/.env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file="api/.env", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Service-role/secret key — server-side only, bypasses RLS. Never ship to the browser.
    supabase_service_role_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_role_key)


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()
