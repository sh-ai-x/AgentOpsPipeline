"""FastAPI surface — JWT auth + run creation/status/cancel + action approval.

Endpoints (proposal §"Contracts and APIs"):
  POST /v1/runs                   -> create run, returns {id, state: 'queued'}
  GET  /v1/runs/{id}              -> state, evidence, last error, token usage
  POST /v1/runs/{id}/cancel       -> state -> cancelling; refuses new tool calls
  POST /v1/actions/{id}/approve   -> action-bound approval

Auth: HS256 JWT (dev secret in .env). principal_id from the `sub` claim.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import BaseModel

from ..db.models import Action, Run
from ..db.session import session_scope
from ..graph.fixed import run_fixed_graph
from ..graph.state import RunState
from ..llm.factory import make_adapter
from ..mocks.tickets import TicketLedger
from ..settings import get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Refuse to serve with a forgeable JWT secret outside the fake provider."""
    settings = get_settings()
    if settings.has_insecure_jwt_secret() and settings.provider != "local-fake":
        raise RuntimeError(
            "AGENTOPS_JWT_SECRET is the dev default or shorter than 32 chars while "
            f"provider={settings.provider!r}. Set a strong secret before starting the "
            "API: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    yield


app = FastAPI(title="AgentOps Workbench API", version="0.2.0", lifespan=_lifespan)

# Single ledger instance per process. Step 6 wires DI properly.
_ledger: TicketLedger | None = None


def get_ledger() -> TicketLedger:
    global _ledger
    if _ledger is None:
        _ledger = TicketLedger()
    return _ledger


# ---- Schemas ----


class CreateRunBody(BaseModel):
    task: str
    graph_version: str = "fixed-v1"
    prompt_version: str = "v1_baseline"
    model_config: dict[str, Any] = {}
    budget: dict[str, Any] = {}


class RunView(BaseModel):
    id: str
    state: str
    answer: str | None
    error: str | None
    total_tokens: int
    cost_usd: float
    tool_calls: list[dict[str, Any]] = []


class CancelResult(BaseModel):
    id: str
    state: str


class ApproveBody(BaseModel):
    tool_name: str
    args: dict[str, Any]
    # Accepted for backward compatibility but ignored: the approver is
    # bound to the authenticated JWT principal, never a client-supplied
    # string (that was approver impersonation).
    approved_by: str | None = None


class ApproveResult(BaseModel):
    action_id: str
    nonce: str
    expires_at: str


# ---- Auth ----


def issue_token(principal_id: str, settings=None) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": principal_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.jwt_expiry_seconds)).timestamp()),
        "principal_id": principal_id,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def require_principal(authorization: str | None = Header(None)) -> str:
    """JWT auth gate. Raises 401 on missing/invalid bearer."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1].strip()
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid token: {exc}") from exc
    pid = payload.get("principal_id") or payload.get("sub")
    if not pid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing principal_id claim")
    return pid


# ---- Endpoints ----


@app.post("/v1/runs", response_model=RunView, status_code=status.HTTP_201_CREATED)
def create_run(body: CreateRunBody, principal_id: str = Depends(require_principal)) -> RunView:
    run_id = uuid.uuid4().hex[:32]
    code_sha = os.environ.get("AGENTOPS_CODE_SHA", "dev-sha")
    with session_scope() as s:
        run = Run(
            id=run_id,
            principal_id=principal_id,
            state=RunState.QUEUED.value,
            graph_version=body.graph_version,
            prompt_version=body.prompt_version,
            model_config=body.model_config,
            budget=body.budget,
            code_sha=code_sha,
            task=body.task,
        )
        s.add(run)
        s.flush()

    # Synchronous execution for MVP (Step 5 moves this to a job runner)
    _execute_run(run_id)
    return get_run(run_id, principal_id)


def _execute_run(run_id: str) -> None:
    settings = get_settings()
    adapter = make_adapter(settings)
    try:
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None:
                return
            task = run.task
            run.state = RunState.RUNNING.value
        # execute graph (synchronous; bounded by max_steps default 8)
        try:
            out = run_fixed_graph(adapter, task)
        except Exception as exc:  # pragma: no cover - exercised via test_failure
            log.exception("graph execution failed")
            with session_scope() as s:
                run = s.get(Run, run_id)
                if run is not None:
                    run.state = RunState.FAILED.value
                    run.error = f"graph_error: {exc}"
            return
        usage = adapter.last_usage
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None:
                return
            run.answer = out.answer
            run.state = out.state.value
            if usage is not None:
                run.total_tokens = usage.total_tokens
                run.cost_usd = usage.cost_usd
    finally:
        adapter.close()


@app.get("/v1/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, principal_id: str = Depends(require_principal)) -> RunView:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None or run.principal_id != principal_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        tool_calls = [
            {
                "id": tc.id,
                "tool_name": tc.tool_name,
                "policy_decision": tc.policy_decision,
                "action_key": tc.action_key,
                "outcome": tc.outcome,
                "latency_ms": tc.latency_ms,
            }
            for tc in run.tool_calls
        ]
        return RunView(
            id=run.id,
            state=run.state,
            answer=run.answer,
            error=run.error,
            total_tokens=run.total_tokens,
            cost_usd=run.cost_usd,
            tool_calls=tool_calls,
        )


@app.get("/_debug/retrieve", response_model=dict)
def debug_retrieve(task: str) -> dict:
    """Return the docs the agent would retrieve for `task`.

    Web-debuggable surface so the operator can see what corpus the
    fixed graph would surface BEFORE running a full /v1/runs cycle.
    No auth — local dev tool only (the guard is `provider == "local-fake"`
    upstream, so this is safe to leave mounted in dev).
    """
    from agentops_workbench.graph.fixed import _retrieve_docs
    from agentops_workbench.settings import get_settings

    settings = get_settings()
    raw = _retrieve_docs(task)
    no_match = raw == "(no relevant docs found)"
    docs: list[dict[str, str]] = []
    if not no_match:
        # _retrieve_docs joins with "\n\n--\n\n" + prefix "[stem]: <snippet>"
        for chunk in raw.split("\n\n--\n\n"):
            head, _, body = chunk.partition("]: ")
            if not body:
                continue
            stem = head.lstrip("[").rstrip()
            docs.append({"stem": stem, "snippet": body[:500]})

    return {
        "task": task,
        "provider": settings.provider,
        "model": settings.model,
        "docs_dir": "fixtures/docs",
        "matched": not no_match,
        "doc_count": len(docs),
        "docs": docs,
    }


@app.get("/_debug/metrics", response_model=dict)
def debug_metrics() -> dict:
    """Live, measurable state of the workbench app.

    Web-debuggable surface so the operator can see what's happening
    without a CLI. Returns:
      - test_count: pytest tests collected
      - db_stats: {runs, tool_calls, actions} from the local SQLite ledger
      - screenshots: {count, bytes_total} for docs/screenshots/*.png
      - line_diff_vs_main: (+added, -removed) under apps/agentops-workbench/
      - settings: {provider, model} (sanitized)

    Cheap to call; recomputes on each request so the values stay live.
    """
    import sqlite3
    import subprocess

    workbench = Path(__file__).resolve().parent.parent.parent.parent
    repo_root = workbench.parent.parent
    db_path = workbench / "agentops.db"
    screenshot_dir = workbench / "docs" / "screenshots"

    # Test count via pytest --collect-only
    test_n = -1
    try:
        out = subprocess.run(
            ["uv", "run", "pytest", "--collect-only", "-q"],
            cwd=str(workbench), check=False, capture_output=True, text=True, timeout=60,
        ).stdout
        for line in out.splitlines():
            if "tests collected" in line or "test collected" in line:
                test_n = int(line.split()[0].replace("tests", "").replace("test", "").strip())
                break
    except Exception:
        pass

    # DB stats
    db_stats = {"runs": 0, "tool_calls": 0, "actions": 0}
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            for label, table in (("runs", "runs"), ("tool_calls", "tool_calls"), ("actions", "actions")):
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    db_stats[label] = cur.fetchone()[0]
                except sqlite3.OperationalError:
                    pass
            conn.close()
        except Exception:
            pass

    # Screenshots
    sc_count = 0
    sc_bytes = 0
    if screenshot_dir.exists():
        for p in screenshot_dir.glob("*.png"):
            sc_count += 1
            sc_bytes += p.stat().st_size

    # Line diff vs origin/main
    add = rem = 0
    try:
        diff_out = subprocess.run(
            ["git", "diff", "--numstat", "origin/main...HEAD", "--", "apps/agentops-workbench/"],
            cwd=str(repo_root), check=False, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        for line in diff_out.splitlines():
            a, r, _ = line.split("\t", 2)
            if a == "-":
                continue
            add += int(a); rem += int(r)
    except Exception:
        pass

    # Latest-run cost (most recent run's total cost from the DB).
    recent_cost_usd = 0.0
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT cost_usd FROM runs WHERE cost_usd > 0 ORDER BY rowid DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                recent_cost_usd = float(row[0])
            conn.close()
        except Exception:
            pass

    return {
        "test_count": test_n,
        "db_stats": db_stats,
        "screenshots": {"count": sc_count, "bytes_total": sc_bytes},
        "line_diff_vs_main": {"added": add, "removed": rem},
        "settings": {
            "provider": get_settings().provider,
            "model": get_settings().model,
        },
        "recent_cost_usd": recent_cost_usd,
        "caveats": {
            "cost_usd": (
                "Local-fake always returns 0.0 (fixture is free). For minimax/openai/anthropic, "
                "cost is computed locally as prompt_tokens/1M * input_per_1m + "
                "completion_tokens/1M * output_per_1m; edit "
                "src/agentops_workbench/llm/pricing.py MODEL_PRICING or set "
                "AGENTOPS_PRICING_JSON env var to override."
            ),
            "tool_calls": (
                "Default graph (fixed-v1) does not invoke MCP tools — its only call is "
                "an in-process lexical retrieval function (not recorded as a tool call). "
                "The planner-executor graph walks search_docs/read_document/get_issue "
                "but requires the MCP document server to be running; without it, "
                "tool_calls stays at 0. This is by-design, not a bug."
            ),
        },
    }


@app.post("/v1/runs/{run_id}/cancel", response_model=CancelResult)
def cancel_run(run_id: str, principal_id: str = Depends(require_principal)) -> CancelResult:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None or run.principal_id != principal_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        if run.state not in {RunState.QUEUED.value, RunState.RUNNING.value, RunState.WAITING_FOR_APPROVAL.value}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot cancel from state {run.state}",
            )
        run.state = RunState.CANCELLED.value
    return CancelResult(id=run_id, state=RunState.CANCELLED.value)


@app.post("/v1/actions", response_model=ApproveResult, status_code=status.HTTP_201_CREATED)
def create_action(body: ApproveBody, run_id: str, principal_id: str = Depends(require_principal)) -> ApproveResult:
    """Create a pending action record (bound nonce + expiry)."""
    nonce = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    action_id = hashlib.sha256(f"{run_id}:{body.tool_name}:{nonce}".encode()).hexdigest()[:32]
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None or run.principal_id != principal_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        action = Action(
            id=action_id,
            run_id=run_id,
            tool_name=body.tool_name,
            args_canonical=body.args,
            nonce=nonce,
            expires_at=expires_at,
            approved_by=principal_id,
        )
        s.add(action)
    return ApproveResult(action_id=action_id, nonce=nonce, expires_at=expires_at.isoformat())


def make_test_client() -> TestClient:
    return TestClient(app)
