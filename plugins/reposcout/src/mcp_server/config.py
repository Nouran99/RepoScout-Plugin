"""Plugin settings loaded from environment variables via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """RepoScout plugin configuration.

    All values are optional — the plugin works in free/anonymous mode when
    neither GITHUB_TOKEN nor REPOSCOUT_API_KEY are set.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    github_token: str | None = None
    reposcout_api_key: str | None = None
    reposcout_backend_url: str = "https://reposcout-api.nouran-darwish-ai.dev"
    # Fail closed by default so backend outages cannot bypass paid-plan limits.
    # Local development can opt into fail-open behavior explicitly.
    reposcout_license_fail_open: bool = False


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()
