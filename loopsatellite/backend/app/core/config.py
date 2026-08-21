"""Application settings, read from the environment / repo-root .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> repo root
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
PRECOMPUTED_DIR = BACKEND_DIR / "precomputed"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -------------------------------------------------------
    # Optional: the demo read path serves precomputed/ and does not need a DB.
    # The DB backs officer verifications, which are the only writes in the MVP.
    database_url: str | None = None

    # --- LLM (OpenRouter) ----------------------------------------------
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "LoopSatellite"

    # --- Web search (evidence corroboration) ----------------------------
    search_provider: str = "openrouter_online"  # openrouter_online | tavily | serper | none
    search_api_key: str | None = None

    # --- Paths ----------------------------------------------------------
    precomputed_dir: Path = PRECOMPUTED_DIR

    # --- CORS -----------------------------------------------------------
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def db_configured(self) -> bool:
        return bool(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
