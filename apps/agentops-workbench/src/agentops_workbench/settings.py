"""Runtime settings — driven by env vars; .env is gitignored."""
from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_SECRETS = {"", "dev-only-please-rotate"}
_ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


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
    model: str = "MiniMax-M3"  # valid on api.minimax.io/v1
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

    # Document corpus (MCP document server + lexical retrieval)
    docs_dir: str = "fixtures/docs"

    # Trace export (OTel spans per run)
    runs_dir: str = "./runs"

    # Auth: principal for local dev
    dev_principal_id: str = "dev-user"

    @model_validator(mode="after")
    def _guard_jwt_algorithm(self) -> Settings:
        """Reject alg=none / unknown JWT algorithms (token-forgery guard)."""
        if self.jwt_algorithm not in _ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"AGENTOPS_JWT_ALGORITHM must be one of {sorted(_ALLOWED_JWT_ALGORITHMS)}; "
                f"got {self.jwt_algorithm!r}."
            )
        return self

    def has_insecure_jwt_secret(self) -> bool:
        """True when the JWT secret is the dev default, empty, or too short.

        The API server refuses to start in this state unless
        provider == "local-fake" (the offline CI / unit-test path, ADR-0003
        — no network, no real principals). See api.server:_lifespan.
        """
        return self.jwt_secret in _INSECURE_JWT_SECRETS or len(self.jwt_secret) < 32


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
