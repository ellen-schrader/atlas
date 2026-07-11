"""Application configuration via pydantic-settings.

Secrets and tunables are read from the environment (and a local ``.env`` file).
Never hardcode the Anthropic API key -- it is read from ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (paper_radar/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings. Field names map to upper-case env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Anthropic ---
    anthropic_api_key: str = Field(default="", description="Anthropic API key (from env).")
    anthropic_model: str = Field(default="claude-sonnet-5", description="Model for enrichment.")

    # --- Embeddings ---
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="sentence-transformers model id (runs locally).",
    )
    # bge models want this prefix on the *query* side for retrieval.
    query_prefix: str = "Represent this sentence for searching relevant passages: "

    # --- Paths (all resolved relative to the repo root by default) ---
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path = REPO_ROOT / "data" / "paper_radar.sqlite"
    faiss_index_path: Path = REPO_ROOT / "data" / "faiss.index"
    umap_coords_path: Path = REPO_ROOT / "data" / "umap.npy"
    fixtures_dir: Path = REPO_ROOT / "data" / "fixtures"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
