"""Regression — auth hardening for the review criticals on the import PR.

Covers:
  - JWT algorithm allowlist (alg=none / unknown rejected at Settings build).
  - API server refuses to start with a forgeable JWT secret unless
    provider == "local-fake".
  - create_action binds approved_by to the JWT principal, not the body.
  - _execute_run persists real token usage / cost onto the Run row.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentops_workbench.api import server
from agentops_workbench.api.server import app, issue_token
from agentops_workbench.db.session import reset_for_tests
from agentops_workbench.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    # Ignore the developer's local .env — these tests assert on Settings defaults
    # (e.g. the dev-default JWT secret), which a real .env would silently override.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("AGENTOPS_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    reset_for_tests()
    yield
    reset_for_tests()


def _bearer(principal: str = "alice") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(principal)}"}


# ---- JWT algorithm allowlist ----


@pytest.mark.parametrize("alg", ["none", "None", "RS256", "bogus"])
def test_settings_rejects_non_hmac_jwt_algorithm(alg: str) -> None:
    with pytest.raises(ValueError, match="AGENTOPS_JWT_ALGORITHM"):
        Settings(provider="local-fake", jwt_algorithm=alg)


def test_settings_allows_hs_family() -> None:
    for alg in ("HS256", "HS384", "HS512"):
        assert Settings(provider="local-fake", jwt_algorithm=alg).jwt_algorithm == alg


# ---- insecure-secret startup guard ----


def test_has_insecure_jwt_secret_flags_default_and_short() -> None:
    assert Settings(provider="local-fake").has_insecure_jwt_secret() is True
    assert Settings(provider="local-fake", jwt_secret="short").has_insecure_jwt_secret() is True
    strong = "x" * 40
    assert Settings(provider="local-fake", jwt_secret=strong).has_insecure_jwt_secret() is False


def test_server_refuses_to_start_with_forgeable_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    insecure_live = Settings(provider="minimax", jwt_secret="dev-only-please-rotate")
    monkeypatch.setattr(server, "get_settings", lambda: insecure_live)
    with pytest.raises(RuntimeError, match="AGENTOPS_JWT_SECRET"):
        with TestClient(app):
            pass


def test_server_starts_for_local_fake_with_dev_secret() -> None:
    # The autouse fixture pins provider=local-fake; default dev secret is OK.
    with TestClient(app) as c:
        assert c.post("/v1/runs", json={"task": "hi"}).status_code == 401


# ---- approver binding ----


def test_create_action_ignores_body_approved_by() -> None:
    with TestClient(app) as c:
        run_id = c.post("/v1/runs", json={"task": "x"}, headers=_bearer("alice")).json()["id"]
        c.post(
            f"/v1/actions?run_id={run_id}",
            json={"tool_name": "publish_ticket", "args": {}, "approved_by": "mallory"},
            headers=_bearer("alice"),
        )
    from agentops_workbench.db.models import Action
    from agentops_workbench.db.session import session_scope

    with session_scope() as s:
        action = s.query(Action).filter_by(run_id=run_id).one()
        assert action.approved_by == "alice"


# ---- usage persistence ----


def test_execute_run_persists_token_usage() -> None:
    with TestClient(app) as c:
        body = c.post(
            "/v1/runs",
            json={"task": "How do I configure LangGraph checkpointing with PostgreSQL?"},
            headers=_bearer("alice"),
        ).json()
    assert body["total_tokens"] > 0
    assert body["cost_usd"] >= 0.0
