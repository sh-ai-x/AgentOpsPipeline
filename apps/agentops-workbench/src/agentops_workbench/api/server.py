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
import html as _html
import json
import logging
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Form, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

from .. import dev_metrics, oss_helper
from ..db.models import Action, Run, ToolCall
from ..db.session import session_scope
from ..graph.state import RunState, make_action_key
from ..graph.topology import run_topology
from ..llm.factory import make_adapter
from ..mocks.tickets import DuplicateArgsError, TicketLedger
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


# Maps the API-facing graph_version string to a topology.TOPOLOGIES key.
# README documents these three graph_version strings; keep both in sync.
GRAPH_VERSION_TO_TOPOLOGY: dict[str, str] = {
    "fixed-v1": "fixed",
    "single-agent-v1": "single_agent",
    "planner-executor-v1": "planner_executor",
}


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


class ExecuteResult(BaseModel):
    action_id: str
    ticket_id: str
    used_at: str


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
    if body.graph_version not in GRAPH_VERSION_TO_TOPOLOGY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"unknown graph_version: {body.graph_version!r}. "
                f"Supported: {sorted(GRAPH_VERSION_TO_TOPOLOGY)}"
            ),
        )
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


def _persist_tool_calls(session, run_id: str, tool_results: list[dict[str, Any]]) -> None:
    """One ToolCall row per executed planner_executor step.

    fixed/single_agent never produce tool_results, so this is a no-op for
    them -- their tool_calls count stays 0, by design. action_key reuses
    the existing state.make_action_key() dedup helper (run_id, tool_name,
    canonical-hash(args)); args_canonical is the canonical JSON string of
    the args dict, mirroring mocks.tickets.TicketLedger.canonicalize().
    """
    for idx, entry in enumerate(tool_results):
        tool_name = entry["tool_name"]
        args = {"tool_name": tool_name, "step_index": idx}
        args_canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
        action_key = make_action_key(run_id, tool_name, args)
        outcome_payload: dict[str, Any] = {"status": entry["outcome"]}
        if entry.get("error_kind"):
            outcome_payload["error_kind"] = entry["error_kind"]
        session.add(
            ToolCall(
                id=uuid.uuid4().hex[:32],
                run_id=run_id,
                tool_name=tool_name,
                # No approval gate applies to read-only retrieval tools
                # (search_docs/read_document/get_issue); only
                # create_ticket_draft/publish_ticket go through
                # POST /v1/actions. "auto" records that this call was
                # dispatched without a human-in-the-loop approval step.
                policy_decision="auto",
                action_key=action_key,
                args_canonical=args_canonical,
                outcome=outcome_payload,
                latency_ms=entry.get("latency_ms", 0),
            )
        )


def _execute_run(run_id: str) -> None:
    settings = get_settings()
    adapter = make_adapter(settings)
    try:
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None:
                return
            task = run.task
            graph_version = run.graph_version
            run.state = RunState.RUNNING.value

        topology_name = GRAPH_VERSION_TO_TOPOLOGY.get(graph_version)
        if topology_name is None:  # pragma: no cover - guarded at create_run time
            with session_scope() as s:
                run = s.get(Run, run_id)
                if run is not None:
                    run.state = RunState.FAILED.value
                    run.error = f"unknown graph_version: {graph_version!r}"
            return

        # execute graph (synchronous; bounded by each topology's own step budget)
        try:
            result = run_topology(topology_name, adapter, task)
        except Exception as exc:  # pragma: no cover - exercised via test_failure
            log.exception("graph execution failed")
            with session_scope() as s:
                run = s.get(Run, run_id)
                if run is not None:
                    run.state = RunState.FAILED.value
                    run.error = f"graph_error: {exc}"
            return
        usage = adapter.last_usage
        tool_results = result.get("tool_results", [])
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None:
                return
            run.answer = result["answer"]
            state_val = result["state"]
            run.state = state_val.value if isinstance(state_val, RunState) else state_val
            if usage is not None:
                run.total_tokens = usage.total_tokens
                run.cost_usd = usage.cost_usd
            _persist_tool_calls(s, run_id, tool_results)
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



_OSS_HELPER_HTML = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>agentops-oss-helper</title>
<style>
body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, sans-serif;
       max-width: 920px; margin: 24px auto; padding: 0 16px; color: #1a1a1a }
h1 { font-size: 18px; margin: 0 0 4px } small { color: #777; font-weight: 400 }
form { display: flex; gap: 8px; margin: 12px 0 16px }
input[type=text] { flex: 1; padding: 8px; border: 1px solid #ccc;
                   border-radius: 4px; font: inherit }
button { padding: 8px 16px; border: 0; border-radius: 4px;
         background: #1a1a1a; color: #fff; cursor: pointer; font: inherit }
.meta { color: #666; font-size: 12px; margin-bottom: 12px }
pre.answer { white-space: pre-wrap; background: #f6f6f6;
             padding: 12px; border-radius: 4px; font: 13px/1.45 ui-monospace, monospace }
details { margin-top: 12px } details summary { cursor: pointer; color: #1a1a1a }
.warn { color: #a85; background: #fff8e8; padding: 8px; border-radius: 4px; margin: 8px 0 }
.ref { background: #eef; padding: 1px 4px; border-radius: 3px; font: 12px ui-monospace }
</style></head><body>
<h1>agentops-oss-helper <small>Open Source Maintainer Helper Agent</small></h1>
<p class="meta">Paste a public GitHub repo URL. The tool retrieves that
  repo's own docs/README (via <code>git sparse-checkout</code>) and
  Issues/PRs (via the GitHub REST API), then answers your question
  with citations. No login, no write-back to the target repo.</p>
<form method="post" action="/oss-helper">
  <input type="text" name="repo_url" required autofocus
         placeholder="https://github.com/<owner>/<repo>"
         value="''' + "{}" + '''">
  <input type="text" name="question"
         placeholder="optional free-text question">
  <input type="text" name="issue_number"
         placeholder="optional issue #">
  <button type="submit">Run</button>
</form>
''' + '{repo_url_value}' + '''
</body></html>'''

# No global state needed: repo_url_value is interpolated per-request below

@app.get("/oss-helper", response_class=HTMLResponse)
def oss_helper_form() -> HTMLResponse:
    """Minimal HTML form. No Streamlit dependency -- works in any browser.
    Proves the backend/frontend split: this whole flow is reachable
    without streamlit installed (per ADR-0008 exit criterion 2)."""
    return HTMLResponse(_format_oss_helper_html(""))

@app.post("/oss-helper", response_class=HTMLResponse)
async def oss_helper_run(
    repo_url: str = Form(...),
    question: str = Form(""),
    issue_number: str = Form(""),
) -> HTMLResponse:
    """Run the OSS Maintainer Helper flow and render an HTML report."""
    try:
        issue_n = int(issue_number) if issue_number.strip() else None
        result = oss_helper.run_oss_helper(
            repo_url=repo_url,
            question=question.strip() or None,
            issue_number=issue_n,
        )
    except ValueError as exc:
        body = _format_oss_helper_html(repo_url)
        return HTMLResponse(
            body + f'<p class="warn">{exc}</p></body></html>'
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("oss-helper run failed")
        body = _format_oss_helper_html(repo_url)
        return HTMLResponse(
            body + f'<p class="warn">Internal error: {exc!r}</p></body></html>'
        )
    return HTMLResponse(_render_oss_helper_report(repo_url, result))

def _render_oss_helper_report(repo_url: str, result: oss_helper.TriageResult) -> str:
    """Render the TriageResult as HTML. Inline-only -- no client-side JS,
    no external assets, no Streamlit dependency."""
    warns = "".join(f'<p class="warn">{w}</p>' for w in result.warnings)
    refs_wiki = _render_refs(result.wiki_refs)
    refs_issue = _render_refs(result.issue_refs)
    return (
        _format_oss_helper_html(repo_url)
        + f'<p class="meta">{result.owner}/{result.repo}'
        + (f' &middot; issue #{result.issue_number}' if result.issue_number else "")
        + f' &middot; {len(result.wiki_refs)} doc refs, {len(result.issue_refs)} issue/PR refs'
        + f' &middot; {result.duration_ms}ms</p>'
        + warns
        + '<h2 style="font-size:15px;margin:16px 0 4px">Answer</h2>'
        + f'<pre class="answer">{_html.escape(result.answer)}</pre>'
        + '<details><summary>Docs evidence (' + str(len(result.wiki_refs)) + ')</summary>'
        + refs_wiki + '</details>'
        + '<details><summary>Issue/PR evidence (' + str(len(result.issue_refs)) + ')</summary>'
        + refs_issue + '</details>'
        + '</body></html>'
    )

def _render_refs(refs: list[dict]) -> str:
    out = []
    for r in refs:
        rid = _html.escape(str(r.get('ref_id', '')))
        title = _html.escape(str(r.get('title', '')))
        sk = _html.escape(str(r.get('source_kind', '')))
        score = r.get('score', 0)
        out.append(
            f'<div style="margin:6px 0">'
            f'<span class="ref">{rid}</span> {title}'
            f' <span class="meta">[{sk}, score={score:.2f}]</span></div>'
        )
    return "".join(out)

def _format_oss_helper_html(repo_url: str) -> str:
    """Substitute the per-request URL into the HTML template.

    Uses str.replace (not str.format) because the template's CSS contains
    brace literals that str.format would mis-parse as placeholders.
    """
    return _OSS_HELPER_HTML.replace("{repo_url_value}", _html.escape(repo_url or ""))



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

    Provider-guard: only serves when `provider=local-fake` or when
    `AGENTOPS_ALLOW_DEBUG_METRICS=1` is set. Production deployments
    with a real LLM should require an authenticated principal here;
    left as the explicit opt-in to keep the dev path frictionless.
    """
    settings = get_settings()
    if settings.provider != "local-fake" and not os.environ.get("AGENTOPS_ALLOW_DEBUG_METRICS"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "/_debug/metrics is dev-only. Set provider=local-fake or "
                "AGENTOPS_ALLOW_DEBUG_METRICS=1 to enable on a real provider."
            ),
        )

    return {
        "test_count": dev_metrics.test_count(),
        "db_stats": dev_metrics.db_stats(),
        "screenshots": dev_metrics.screenshot_stats(),
        "line_diff_vs_main": dev_metrics.line_diff_vs_main(),
        "settings": {
            "provider": settings.provider,
            "model": settings.model,
        },
        "recent_cost_usd": dev_metrics.recent_cost_usd(),
        "caveats": {
            "cost_usd": (
                "Local-fake always returns 0.0 (fixture is free). For minimax/openai/anthropic, "
                "cost is computed locally as prompt_tokens/1M * input_per_1m + "
                "completion_tokens/1M * output_per_1m; edit "
                "src/agentops_workbench/llm/pricing.py DEFAULT_PRICING or set "
                "AGENTOPS_PRICING_JSON env var to override. Unknown models return 0.0."
            ),
            "tool_calls": (
                "fixed-v1 and single-agent-v1 never make MCP tool calls: fixed-v1's only "
                "call is an in-process lexical retrieval function (not recorded as a tool "
                "call), and single-agent-v1's TOOL branch is still a stub. tool_calls "
                "stays at 0 for both, by design. planner-executor-v1 executes its plan "
                "against a real DocumentClient (InMemoryDocumentClient, reading "
                "fixtures/docs/*.md) and persists one ToolCall row per executed step: "
                "search_docs/read_document record outcome.status='ok' with real "
                "fixture-corpus results; get_issue has no real backend anywhere in this "
                "repo and always records outcome.status='error' with "
                "outcome.error_kind='unsupported_capability'. With provider=local-fake "
                "(the CI default) the planner LLM cannot produce a parseable plan, so "
                "planner-executor-v1 still short-circuits to 0 tool_calls under CI; a "
                "live provider (minimax/openai/anthropic) that emits a real plan "
                "produces non-zero tool_calls."
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


@app.post("/v1/actions/{action_id}/execute", response_model=ExecuteResult)
def execute_action(action_id: str, principal_id: str = Depends(require_principal)) -> ExecuteResult:
    """Execute an approved action: run -> ticket draft -> TicketLedger.publish().

    Idempotent by design, not by an explicit guard: TicketLedger.publish()
    is itself idempotent on action_key (== action_id here), so re-executing
    an already-used_at-stamped action naturally returns the same
    TicketRecord instead of double-publishing. A DuplicateArgsError (a
    replay with mutated args under the same action_key) surfaces as a
    clean 409, never a raw 500 -- the "failed tool is visible" half of
    step 2's AC.
    """
    with session_scope() as s:
        action = s.get(Action, action_id)
        if action is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="action not found")
        run = s.get(Run, action.run_id)
        if run is None or run.principal_id != principal_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="action not found")

        if action.cancelled:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="action is cancelled")

        expires_at = action.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now > expires_at:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="action has expired")

        args = action.args_canonical or {}
        title = args.get("title") or f"Ticket for run {action.run_id}"
        body = args.get("body") or run.answer or run.task or f"Ticket for run {action.run_id}"

        try:
            ticket = get_ledger().publish(
                action_key=action.id,
                title=title,
                body=body,
                published_by=principal_id,
                args=args,
            )
        except DuplicateArgsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"action replay with mutated args: {exc}",
            ) from exc

        action.used_at = now
        s.add(action)
        return ExecuteResult(action_id=action.id, ticket_id=ticket.id, used_at=now.isoformat())


def make_test_client() -> TestClient:
    return TestClient(app)
