"""Atlas MCP settings.

Read from ``api/.env`` (the same file the API uses) or real environment
variables — env vars win over the file. Keeping this file-based avoids relying
on an MCP client to expand ``${VAR}`` references in its config, which is not
portable across clients.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AtlasSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file="api/.env", extra="ignore")

    # Auth: a token, or an email/password we sign in with.
    atlas_token: str = ""
    atlas_email: str = ""
    atlas_password: str = ""
    # Default lab when the user is in more than one.
    atlas_team_id: str = ""
    # Base for the ?paper= deep links.
    atlas_web_url: str = "http://localhost:5173"


@lru_cache
def get_atlas_settings() -> AtlasSettings:
    return AtlasSettings()
