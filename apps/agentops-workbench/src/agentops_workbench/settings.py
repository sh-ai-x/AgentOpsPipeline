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

    # Document corpus (MCP document server + lexical retrieval).
    # Set wiki_dir to point the agent at any directory of *.md files
    # (e.g. an exported personal wiki); falls back to docs_dir when empty.
    # Uses WikiRagAdapter (TF-IDF over *.md) for the planner topology and
    # the same lexical scan as docs_dir for the fixed topology.
    #
    # Multi-tenant caveat (Major 6 in PR #39 review, marked PLAUSIBLE):
    # wiki_dir is read from process-global settings, NOT per principal_id.
    # In a multi-tenant deployment every authenticated principal reads the
    # same wiki tree. Either scope by principal_id (deferred — needs an
    # auth-aware corpus resolution path) or document this caveat to the
    # operator. This docstring is the documentation half; scoping is a
    # separate ADR-level decision.
    docs_dir: str = "fixtures/docs"
    wiki_dir: str = ""

    # Trace export (OTel spans per run)
    runs_dir: str = "./runs"

    # Auth: principal for local dev
    dev_principal_id: str = "dev-user"

    # Dev-mode auto-mint: when True AND provider=local-fake, the API
    # exposes GET /v1/auth/dev-token that mints a fresh JWT on demand
    # so the web UI (and Streamlit) can authenticate without a
    # hand-pasted bearer. Production deployments leave this False
    # (default) and route JWTs through an ID provider (Auth0/Cognito/etc).
    allow_dev_token: bool = False

    def resolved_corpus(self, override: str | None = None) -> tuple[str, bool]:
        """Resolve the (corpus_dir, wiki_mode) tuple for a single run.

        `override` is the per-run `corpus_dir` field on `CreateRunBody`;
        when set, it takes precedence over both env-derived fields.
        `wiki_mode` is True only when the resolved corpus was explicitly
        marked as a wiki directory (i.e. `wiki_dir` was set AND no per-run
        override replaced it). The planner/single_agent topologies use
        WikiRagAdapter only when wiki_mode is True; the fixed topology
        uses `_retrieve_docs` regardless.
        """
        if override:
            return (override, False)
        if self.wiki_dir:
            return (self.wiki_dir, True)
        return (self.docs_dir, False)

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


# Single source of truth for the default corpus directory. Imported
# wherever the literal would otherwise be duplicated; renaming the
# default now requires a single edit. Mirrors `Settings.docs_dir`'s
# default value, intentionally module-level so non-Settings callers
# (graph/topology.py etc.) don't need a Settings instance to get it.
DEFAULT_CORPUS_DIR = "fixtures/docs"
