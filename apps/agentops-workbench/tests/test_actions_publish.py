"""TDD tests for POST /v1/actions/{action_id}/execute -> TicketLedger.publish().

Covers the run -> ticket draft -> /v1/actions approve -> TicketLedger.publish()
flow named as unfinished in build-report.md's step 2 AC. Kept as its own
file (not merged into test_api_runs.py) -- a different PR is independently
touching test_api_runs.py in this same area and this avoids a merge
conflict.

Mirrors test_api_runs.py's fixture style: `_isolate_db` (fresh sqlite file
per test via AGENTOPS_DATABASE_URL + reset_for_tests), `client` (a fresh
TestClient per test), and `_bearer` (issues a real JWT for a principal).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import agentops_workbench.api.server as server_module
from agentops_workbench.api.server import app, get_ledger, issue_token
from agentops_workbench.db.models import Action
from agentops_workbench.db.session import reset_for_tests, session_scope


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("AGENTOPS_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    reset_for_tests()
    # The ledger is a module-level singleton (server._ledger) shared across
    # the whole process -- reset it too so each test starts from an empty
    # ledger instead of accumulating tickets from earlier tests/files.
    monkeypatch.setattr(server_module, "_ledger", None)
    yield
    reset_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _bearer(principal: str = "alice") -> dict[str, str]:
    tok = issue_token(principal)
    return {"Authorization": f"Bearer {tok}"}


def _create_run(client: TestClient, principal: str = "alice") -> str:
    r = client.post("/v1/runs", json={"task": "x"}, headers=_bearer(principal))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_action(
    client: TestClient,
    run_id: str,
    principal: str = "alice",
    args: dict | None = None,
) -> str:
    a = client.post(
        f"/v1/actions?run_id={run_id}",
        json={"tool_name": "publish_ticket", "args": args or {"title": "t", "body": "b"}},
        headers=_bearer(principal),
    )
    assert a.status_code == 201, a.text
    return a.json()["action_id"]


# ---- Happy path ----


def test_execute_publishes_ticket_and_stamps_used_at(client: TestClient) -> None:
    run_id = _create_run(client)
    action_id = _create_action(client, run_id, args={"title": "Ship it", "body": "Body text"})

    r = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action_id"] == action_id
    assert body["ticket_id"]
    assert body["used_at"]

    # Ticket actually landed in the ledger.
    assert get_ledger().count() == 1

    # used_at persisted on the Action row.
    with session_scope() as s:
        action = s.get(Action, action_id)
        assert action.used_at is not None


def test_execute_derives_title_body_defaults_when_args_missing(client: TestClient) -> None:
    run_id = _create_run(client)
    # No title/body in args -- endpoint must fall back defensively, not 500.
    action_id = _create_action(client, run_id, args={})

    r = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r.status_code == 200, r.text
    assert r.json()["ticket_id"]


# ---- Idempotency ----


def test_execute_twice_is_idempotent(client: TestClient) -> None:
    run_id = _create_run(client)
    action_id = _create_action(client, run_id)

    r1 = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    r2 = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["ticket_id"] == r2.json()["ticket_id"]

    # No double-publish: the ledger count did not grow on the replay.
    assert get_ledger().count() == 1


# ---- Expiry ----


def test_execute_refuses_expired_action(client: TestClient) -> None:
    run_id = _create_run(client)
    action_id = _create_action(client, run_id)

    with session_scope() as s:
        action = s.get(Action, action_id)
        action.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    r = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r.status_code == 409, r.text
    assert "expir" in r.json()["detail"].lower()

    # Nothing published for a refused action.
    assert get_ledger().count() == 0


# ---- Cancellation ----


def test_execute_refuses_cancelled_action(client: TestClient) -> None:
    run_id = _create_run(client)
    action_id = _create_action(client, run_id)

    with session_scope() as s:
        action = s.get(Action, action_id)
        action.cancelled = True

    r = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r.status_code == 409, r.text
    assert "cancel" in r.json()["detail"].lower()

    assert get_ledger().count() == 0


# ---- Wrong principal ----


def test_execute_by_wrong_principal_returns_404(client: TestClient) -> None:
    run_id = _create_run(client, principal="alice")
    action_id = _create_action(client, run_id, principal="alice")

    r = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer("bob"))
    assert r.status_code == 404, r.text

    assert get_ledger().count() == 0


def test_execute_missing_action_returns_404(client: TestClient) -> None:
    r = client.post("/v1/actions/does-not-exist/execute", headers=_bearer())
    assert r.status_code == 404, r.text


# ---- Mutated-args replay ----


def test_execute_replay_with_mutated_args_is_clean_4xx_not_500(client: TestClient) -> None:
    run_id = _create_run(client)
    action_id = _create_action(client, run_id, args={"title": "Original", "body": "Body"})

    r1 = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r1.status_code == 200, r1.text

    # Mutate the stored args directly (simulating a replay with different
    # canonical args under the same action_key) -- the endpoint derives
    # args from the stored Action row, so this is the only way to force
    # DuplicateArgsError through the HTTP surface.
    with session_scope() as s:
        action = s.get(Action, action_id)
        action.args_canonical = {"title": "Mutated", "body": "Different body"}

    r2 = client.post(f"/v1/actions/{action_id}/execute", headers=_bearer())
    assert r2.status_code in (409, 422), r2.text
    detail = r2.json()["detail"]
    assert detail
    assert "different args" in detail.lower() or "duplicate" in detail.lower() or "mutated" in detail.lower()

    # Still only the one, original ticket in the ledger.
    assert get_ledger().count() == 1
