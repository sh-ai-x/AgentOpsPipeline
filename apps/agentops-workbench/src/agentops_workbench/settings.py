"""Runtime settings — driven by env vars; .env is gitignored."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from environment (and .env if present). All env vars are prefixed AGENTOPS_."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTOPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Provider
    provider: str = "local-fake"
    model: str = "local-fake-v1"
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # App
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    jwt_secret: str = "dev-only-please-rotate"
    jwt_algorithm: str = "HS256"
    jwt_expiry_seconds: int = 3600

    # DB
    database_url: str = "sqlite:///./agentops.db"

    # Auth: principal for local dev
    dev_principal_id: str = "dev-user"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
