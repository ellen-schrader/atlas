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

    # Comma-separated allowed CORS origins (dev alt-port / deployed frontend).
    cors_origins: str = "http://localhost:5173"

    # --- Embeddings (see docs/EMBEDDINGS_PLAN.md) ---
    # "voyage" is the only provider today; the field is the swap point for a
    # local scientific model (SPECTER2/SciNCL) after the phase-7 benchmark.
    embedding_provider: str = "voyage"
    voyage_api_key: str = ""
    embedding_model: str = "voyage-4"
    # Must match the vector(N) columns in the schema (init migration).
    embedding_dim: int = 1024

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_role_key)


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()
