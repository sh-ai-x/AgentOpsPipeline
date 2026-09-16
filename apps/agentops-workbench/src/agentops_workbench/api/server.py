"""FastAPI surface — JWT auth + run creation/status/cancel + action approval.

Endpoints (proposal §"Contracts and APIs"):
  POST /v1/runs                   -> create run, returns {id, state: 'queued'}
  GET  /v1/runs/{id}              -> state, evidence, last error, token usage
  POST /v1/runs/{id}/cancel       -> state -> cancelling; refuses new tool calls
  POST /v1/actions/{id}/approve   -> action-bound approval
  POST /v1/wiki/index-files       -> upload .md files, returns corpus_id (AC1)
  GET  /v1/wiki/search            -> TF-IDF search over a corpus, with
                                     AC3 trust fields (source_path,
                                     evidence_span, coverage, etc.) (AC2/AC3)
  POST /v1/wiki/qa                -> search + LLM answer + per-sentence
                                     groundedness (AC3)

Auth: HS256 JWT (dev secret in .env). principal_id from the `sub` claim.
"""
from __future__ import annotations

import hashlib
import html as _html
import logging
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from fastapi import Depends, FastAPI, Form, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import dev_metrics, groundedness, oss_helper, wiki_corpus
from ..db.models import Action, Run, ToolCall
from ..db.session import session_scope
from ..graph.state import RunState, is_terminal, make_action_key
from ..graph.topology import run_topology
from ..llm.factory import make_adapter
from ..mocks.tickets import TicketLedger
from ..settings import get_settings
from ..wiki_metrics import (
    GroundednessRecorder,
    GroundednessSample,
    StageLatencyRecorder,
    StageSample,
)

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

# Module-level metrics aggregators. Singleton pattern matches the wiki
# corpus registry -- process-local, lifetime = process lifetime. Tests
# reset via `reset_for_tests()`. The 200-sample trailing window is small
# enough that p50/p95 stays cheap to compute on every dashboard poll,
# and large enough that the numbers don't jitter every refresh.
search_metrics = StageLatencyRecorder(window=200)
groundedness_metrics = GroundednessRecorder(window=200)

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
    # Per-run corpus override. When set, takes precedence over both
    # wiki_dir and docs_dir; wiki_mode stays False (treated as a plain
    # docs_dir override, not a wiki). Empty string means "use server
    # default" (= wiki_dir if set, else docs_dir).
    corpus_dir: str = ""


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
    _execute_run(run_id, corpus_dir_override=body.corpus_dir or None)
    return get_run(run_id, principal_id)


def _persist_tool_calls(session, run_id: str, tool_results: list[dict[str, Any]]) -> None:
    """One ToolCall row per executed planner_executor step.

    fixed/single_agent never produce tool_results, so this is a no-op for
    them -- their tool_calls count stays 0, by design. action_key reuses
    the existing state.make_action_key() dedup helper (run_id, tool_name,
    canonical-hash(args)), keyed on the REAL args the tool was invoked with
    (`entry["args"]` -- `{"query": task}` for search_docs, `{"doc_id": ...}`
    for read_document, `{}` otherwise), not a step-position placeholder --
    a retry that re-dispatches the same real call must land on the same
    action_key to satisfy the crash-recovery idempotency invariant
    documented in graph/state.py. args_canonical is stored as the dict
    itself (ToolCall.args_canonical is a JSON column, same shape as
    Action.args_canonical below -- not a double-encoded JSON string).
    """
    for entry in tool_results:
        tool_name = entry["tool_name"]
        args = entry.get("args") or {}
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
                args_canonical=args,
                outcome=outcome_payload,
                latency_ms=entry.get("latency_ms", 0),
            )
        )


def _execute_run(run_id: str, *, corpus_dir_override: str | None = None) -> None:
    settings = get_settings()
    adapter = make_adapter(settings)
    try:
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is None:
                return
            task = run.task
            run.state = RunState.RUNNING.value

        topology_name = GRAPH_VERSION_TO_TOPOLOGY.get(run.graph_version)
        if topology_name is None:  # pragma: no cover - guarded at create_run time
            with session_scope() as s:
                run = s.get(Run, run_id)
                if run is not None:
                    run.state = RunState.FAILED.value
                    run.error = f"unknown graph_version: {run.graph_version!r}"
            return

        # When wiki_dir is set, the agent reads from that directory
        # instead of the fixture docs. `corpus_dir_override` (passed by
        # create_run from the per-run `corpus_dir` body field) wins over
        # both env-derived fields. `wiki_mode` is True only when wiki_dir
        # was the resolver's source — a per-run override forces
        # wiki_mode=False so the operator gets the original
        # InMemoryDocumentClient (substring scan), not a silent
        # retrieval-algorithm swap.
        corpus_dir, wiki_mode = settings.resolved_corpus(override=corpus_dir_override)
        # execute graph (synchronous; bounded by each topology's own step budget)
        try:
            result = run_topology(
                topology_name, adapter, task, corpus_dir=corpus_dir, wiki_mode=wiki_mode
            )
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
            run.answer = result["answer"]
            state_val = result["state"]
            run.state = state_val.value if isinstance(state_val, RunState) else state_val
            if usage is not None:
                run.total_tokens = usage.total_tokens
                run.cost_usd = usage.cost_usd
            tool_results = result.get("tool_results", [])
            if tool_results:
                _persist_tool_calls(s, run_id, tool_results)
    finally:
        adapter.close()


def get_run(run_id: str, principal_id: str) -> RunView:
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


@app.get("/v1/runs/{run_id}", response_model=RunView)
def get_run_endpoint(run_id: str, principal_id: str = Depends(require_principal)) -> RunView:
    return get_run(run_id, principal_id)


@app.post("/v1/runs/{run_id}/cancel", response_model=CancelResult)
def cancel_run(run_id: str, principal_id: str = Depends(require_principal)) -> CancelResult:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None or run.principal_id != principal_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        if is_terminal(RunState(run.state)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot cancel run in terminal state {run.state!r}",
            )
        run.state = RunState.CANCELLED.value
    return CancelResult(id=run_id, state=RunState.CANCELLED.value)


# ---- Dev-mode auto-mint (Phase 9 UX fix) ----
#
# Without this, every request to the web UI has to carry a hand-pasted
# JWT — an awful UX for local dev. Streamlit already has the same
# capability gated by AGENTOPS_ALLOW_DEV_TOKEN=1; the web UI needs
# the equivalent.
#
# Gate: this endpoint is ONLY served when
#   provider == "local-fake"   (the offline fake provider)
# AND settings.allow_dev_token is True (operator opt-in via env).
# Production deployments with a real LLM and a real ID provider
# never expose this — the auth path is `require_principal`.


class DevTokenResponse(BaseModel):
    token: str
    principal_id: str
    expires_in: int


def _dev_token_allowed() -> bool:
    """Return True iff GET /v1/auth/dev-token should be served."""
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - dev-only probe
        return False
    return settings.provider == "local-fake" and settings.allow_dev_token


@app.get("/v1/auth/dev-token", response_model=DevTokenResponse)
def dev_token(principal_id: str = "dev-user") -> DevTokenResponse:
    """Mint a fresh JWT for `principal_id`. Dev-only.

    Disabled by default. Enable with `AGENTOPS_ALLOW_DEV_TOKEN=1` AND
    `AGENTOPS_PROVIDER=local-fake` (the latter is the dev default).
    A real deployment with `provider=minimax|openai|anthropic` will
    get a 403 even if the env var is set — prevents accidentally
    shipping dev-mode auth to prod.
    """
    if not _dev_token_allowed():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "/v1/auth/dev-token is dev-only. Set provider=local-fake "
                "and AGENTOPS_ALLOW_DEV_TOKEN=1 to enable."
            ),
        )
    settings = get_settings()
    pid = principal_id.strip() or settings.dev_principal_id
    tok = issue_token(pid, settings)
    return DevTokenResponse(
        token=tok,
        principal_id=pid,
        expires_in=settings.jwt_expiry_seconds,
    )


@app.get("/v1/auth/dev-mode", response_model=dict)
def dev_mode() -> dict:
    """Report whether dev-mode auto-mint is on, so the web UI can
    know to skip the manual Bearer field."""
    return {
        "enabled": _dev_token_allowed(),
        "provider": get_settings().provider,
        "default_principal": get_settings().dev_principal_id,
    }


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


# ---- debug endpoints ----


@app.get("/_debug/retrieve", response_model=dict)
def debug_retrieve(task: str) -> dict:
    settings = get_settings()
    if settings.provider != "local-fake" and not os.environ.get("AGENTOPS_ALLOW_DEBUG_METRICS"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "/_debug/retrieve is dev-only. Set provider=local-fake or "
                "AGENTOPS_ALLOW_DEBUG_METRICS=1 to enable on a real provider."
            ),
        )
    docs_dir = (Path(__file__).parent.parent.parent / "fixtures" / "docs")
    from ..mcp import InMemoryDocumentClient
    client = InMemoryDocumentClient(docs_dir=str(docs_dir))
    return client.search_docs(task, top_k=5)


@app.get("/_debug/metrics", response_model=dict)
def debug_metrics() -> dict:
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
                "fixed-v1/single-agent-v1 stay at 0 by design; planner-executor-v1 "
                "executes a real TF-IDF search over the target repo's docs/README "
                "and surfaces the top-k matches as wiki evidence refs. "
                "With provider=local-fake (the CI default), the planner produces "
                "an 'I have no direct evidence' answer because the LLM has no real "
                "grounding context."
            ),
        },
    }


# ---- oss-helper (PR #36) web form ----
#
# The oss-helper form is intentionally a thin HTML page so the whole flow
# is reachable without Streamlit installed (per ADR-0008 exit criterion 2).
# All UI is self-contained CSS + a <form> POST; no JS, no client-side
# framework.

_OSS_HELPER_HTML = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>agentops-oss-helper</title>
<style>
:root {
  --bg: #fafafa;
  --fg: #1a1a1a;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #2563eb;
  --accent-bg: #eff6ff;
  --warn-bg: #fef3c7;
  --warn-fg: #92400e;
  --code-bg: #f3f4f6;
}
* { box-sizing: border-box }
body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
       max-width: 960px; margin: 0 auto; padding: 32px 24px; color: var(--fg);
       background: var(--bg) }
header { margin-bottom: 24px }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em }
.tagline { color: var(--muted); font-size: 13px; margin: 0 }
.repo-badge { display: inline-flex; align-items: center; gap: 6px;
              background: var(--accent-bg); color: var(--accent);
              font-weight: 600; padding: 4px 10px; border-radius: 6px;
              font-family: ui-monospace, monospace; font-size: 13px;
              margin: 16px 0 0 }
.repo-badge .octicon { font-size: 12px }
.meta-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
            margin: 16px 0; font-size: 13px; color: var(--muted) }
.meta-chip { background: white; border: 1px solid var(--border); border-radius: 999px;
            padding: 3px 10px; font-size: 12px }
.meta-chip strong { color: var(--fg); font-weight: 600 }
.warn { background: var(--warn-bg); color: var(--warn-fg);
         padding: 10px 14px; border-radius: 6px; margin: 12px 0;
         font-size: 13px; border-left: 3px solid #f59e0b }
.section { background: white; border: 1px solid var(--border); border-radius: 10px;
          padding: 20px; margin: 16px 0 }
.section-title { font-size: 15px; font-weight: 700; color: var(--fg);
                margin: 0 0 14px; padding-bottom: 8px;
                border-bottom: 1px solid var(--border) }
.section-title .count { color: var(--muted); font-weight: 500; font-size: 13px;
                    margin-left: 6px; padding: 2px 8px;
                    border: 1px solid var(--border); border-radius: 999px;
                    vertical-align: 1px }
.ref-list { list-style: none; padding: 0; margin: 0 }
.ref-list li { padding: 10px 0; border-bottom: 1px solid var(--border);
              display: flex; gap: 10px; align-items: flex-start }
.ref-list li:last-child { border-bottom: 0 }
.ref-badge { flex-shrink: 0; font-family: ui-monospace, monospace; font-size: 12px;
             padding: 3px 8px; border-radius: 4px; font-weight: 600;
             text-decoration: none; min-width: 80px; text-align: center }
.ref-badge.wiki { background: var(--code-bg); color: var(--fg) }
.ref-content { flex: 1; min-width: 0 }
.ref-title { font-size: 14px; line-height: 1.35; margin: 0 0 4px; word-wrap: break-word }
.ref-score { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace }
.answer { white-space: pre-wrap; background: var(--code-bg); padding: 16px;
          border-radius: 8px; font: 14px/1.55 ui-monospace, monospace;
          border: 1px solid var(--border); margin: 0 }
.empty { color: var(--muted); padding: 16px;
          background: #f9fafb; border: 1px dashed var(--border);
          border-radius: 6px; text-align: center; font-size: 13px }
@media (max-width: 640px) {
  form { grid-template-columns: 1fr; }
  .ref-list li { flex-direction: column; gap: 6px }
  .ref-badge { align-self: flex-start }
}
</style></head><body>
<header>
<h1>agentops-oss-helper</h1>
<p class="tagline">Open Source Maintainer Helper Agent &mdash; paste a public
GitHub repo URL. The tool retrieves that repo's own docs/README (via
<code>git sparse-checkout</code>) and answers your question with citations.
No login, no write-back to the target repo.</p>
</header>
{repo_header}
<form method="post" action="/oss-helper">
  <input type="text" name="repo_url" required autofocus
         placeholder="https://github.com/<owner>/<repo>"
         value="{repo_url_value}">
  <input type="text" name="question"
         placeholder="optional free-text question">
  <button type="submit">Run</button>
</form>
</body></html>'''


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
) -> HTMLResponse:
    """Run the OSS Maintainer Helper flow and render an HTML report."""
    try:
        result = oss_helper.run_oss_helper(
            repo_url=repo_url,
            question=question.strip() or None,
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


def _title(label: str, count: int) -> str:
    """Section title with a count badge."""
    return (
        f'<div class="section-title">{label}'
        f'<span class="count">{count}</span></div>'
    )


def _render_ref(ref: dict) -> str:
    """Render a single evidence ref link to its source."""
    rid = _html.escape(str(ref.get("ref_id", "")))
    title_text = _html.escape(str(ref.get("title", "")))
    score = ref.get("score", 0)
    return (
        f'<li>'
        f'<span class="ref-badge wiki">{rid}</span>'
        f'<div class="ref-content">'
        f'<div class="ref-title">{title_text}</div>'
        f'<div class="ref-score">score: {score:.2f}</div>'
        f'</div>'
        f'</li>'
    )


def _render_refs_section(title: str, refs: list[dict]) -> str:
    """Render one evidence section: header + list of clickable refs."""
    empty = (
        f'<div class="empty">No matching {title.lower()} found.</div>'
    ) if not refs else ''
    return (
        f'<section class="section">'
        f'{_title(title, len(refs))}'
        + empty
        + '<ul class="ref-list">' + "".join(_render_ref(r) for r in refs) + '</ul>'
        + '</section>'
    )


def _render_oss_helper_report(repo_url: str, result: oss_helper.TriageResult) -> str:
    """Render the TriageResult as HTML. Inline-only -- no client-side JS,
    no external assets, no Streamlit dependency."""
    warns = "".join(f'<p class="warn">{w}</p>' for w in result.warnings)
    meta_row = (
        f'<div class="meta-row">'
        f'<span class="meta-chip">docs: <strong>{len(result.wiki_refs)}</strong></span>'
        f'<span class="meta-chip">duration: <strong>{result.duration_ms}ms</strong></span>'
        f'<span class="meta-chip">provider: <strong>{_html.escape(_provider_name())}</strong></span>'
        f'</div>'
    )
    answer_section = (
        '<section class="section">'
        f'{_title("Answer", "")}'
        f'<div class="answer">{_html.escape(result.answer)}</div>'
        '</section>'
    )
    wiki_section = _render_refs_section(
        "Docs evidence (from the repo's own README/docs)",
        result.wiki_refs,
    )

    return (
        _format_oss_helper_html(repo_url, repo_header="")
        + warns
        + meta_row
        + answer_section
        + wiki_section
        + '</body></html>'
    )


def _provider_name() -> str:
    """Best-effort read of the current provider setting for the status row.
    Falls back to '?' if Settings isn't reachable (e.g. during a probe)."""
    try:
        return get_settings().provider
    except Exception:  # noqa: BLE001
        return "?"


def _format_oss_helper_html(repo_url: str, *, repo_header: str = "") -> str:
    """Substitute the per-request URL into the HTML template.

    Uses str.replace (not str.format) because the template's CSS contains
    brace literals that str.format would mis-parse as placeholders.
    """
    return _OSS_HELPER_HTML.replace(
        "{repo_url_value}", _html.escape(repo_url or "")
    ).replace(
        "{repo_header}", repo_header or ""
    )


# ---- Wiki corpus (Phase 9: browser-native directory picker) ----
#
# The browser File System Access API lets a reviewer pick a directory
# and read its .md files client-side. The browser POSTs each file's
# {path, content, mtime} here; the server writes them to a temp dir,
# builds a WikiRagAdapter (the same TF-IDF + cosine retrieval the
# planner_executor and single_agent topologies already use), and
# returns a corpus_id. corpus_id is process-local + LRU-capped;
# persistent storage is intentionally NOT supported (would mean
# keeping user files on server disk — a privacy regression).


class _WikiFileUpload(BaseModel):
    path: str
    content: str
    mtime: int = 0


class IndexFilesBody(BaseModel):
    files: list[_WikiFileUpload]
    # When the picked directory was an Obsidian vault, the browser
    # supplies the vault name so the server can construct
    # `obsidian://open?vault=<vault>&file=<path>` deep links for every
    # search hit. Optional: missing -> no deep links emitted (avoids
    # guessing a vault to open).
    vault_name: str | None = None


class IndexFilesResponse(BaseModel):
    corpus_id: str
    doc_count: int
    duration_ms: int


class WikiHit(BaseModel):
    ref_id: str
    title: str
    score: float
    # AC3 trust fields.
    source_path: str
    evidence_span: str
    match_offsets: list[list[int]]
    coverage: float
    contributing_terms: list[str]
    mtime: int
    # Set only when the indexed directory was an Obsidian vault (browser
    # supplied vault_name on upload). The frontend uses this for a
    # one-click "open in vault" link on every hit.
    obsidian_uri: str | None = None


class WikiSearchResponse(BaseModel):
    query: str
    corpus_id: str
    top_k: int
    results: list[WikiHit]


class QaBody(BaseModel):
    corpus_id: str
    query: str
    top_k: int = 5


class SentenceScore(BaseModel):
    sentence: str
    cited_refs: list[str]
    unresolved_refs: list[str]
    # Three published metrics per sentence.
    rouge_l_f1: float
    rouge_l_precision: float
    rouge_l_recall: float
    sentence_tokens: int
    evidence_tokens: int
    lcs_length: int


class QaResponse(BaseModel):
    query: str
    corpus_id: str
    answer: str
    # Three answer-level published metrics.
    overall_rouge_l_f1: float
    citation_recall: float
    citation_precision: float
    sentences: list[SentenceScore]
    hits: list[WikiHit]


@app.post("/v1/wiki/index-files", response_model=IndexFilesResponse)
def index_files(
    body: IndexFilesBody,
    principal_id: str = Depends(require_principal),
) -> IndexFilesResponse:
    """Accept the browser-uploaded {path, content, mtime} list, write
    them to a temp dir, and build a WikiRagAdapter. Returns corpus_id.

    Path validation: rejects absolute paths and any path containing
    `..` segments. The browser can technically read anywhere on the
    user's filesystem once the OS picker is approved; the server still
    refuses to write outside the temp dir even if the client is buggy
    or malicious.
    """
    import time as _time

    started = _time.monotonic()
    files_payload = [
        {"path": f.path, "content": f.content, "mtime": f.mtime}
        for f in body.files
    ]
    try:
        corpus_id, _work_dir, doc_count = wiki_corpus.index_uploaded_files(
            files_payload, vault_name=body.vault_name
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    duration_ms = int((_time.monotonic() - started) * 1000)
    log.info(
        "wiki index: principal=%s corpus_id=%s doc_count=%d files=%d duration_ms=%d",
        principal_id, corpus_id, doc_count, len(files_payload), duration_ms,
    )
    return IndexFilesResponse(
        corpus_id=corpus_id,
        doc_count=doc_count,
        duration_ms=duration_ms,
    )


@app.get("/v1/wiki/search", response_model=WikiSearchResponse)
def wiki_search_endpoint(
    corpus_id: str,
    q: str,
    top_k: int = 5,
    principal_id: str = Depends(require_principal),
) -> WikiSearchResponse:
    """TF-IDF search scoped to `corpus_id`. Returns AC3 trust fields
    on every hit. 404 if the corpus_id is unknown (evicted from LRU
    or never existed)."""
    effective_top_k = max(1, min(top_k, 20))
    try:
        hits, timing_ms = wiki_corpus.search_with_timing(
            corpus_id, q, top_k=effective_top_k
        )
    except wiki_corpus.UnknownCorpusError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"corpus_id not found: {exc.corpus_id}",
        ) from exc
    # Record one latency sample per call -- the dashboard's p50/p95
    # bars are built off this rolling window.
    search_metrics.record(
        StageSample(
            tokenize_ms=timing_ms.get("tokenize_ms", 0.0),
            score_ms=timing_ms.get("score_ms", 0.0),
            sort_and_return_ms=timing_ms.get("sort_and_return_ms", 0.0),
            total_ms=timing_ms.get("total_ms", 0.0),
        )
    )
    return WikiSearchResponse(
        query=q,
        corpus_id=corpus_id,
        top_k=effective_top_k,
        results=[WikiHit(**h.to_dict()) for h in hits],
    )


@app.get("/v1/wiki/metrics")
def wiki_metrics_endpoint(
    principal_id: str = Depends(require_principal),
) -> dict[str, Any]:
    """Aggregate observability for the wiki chat surface.

    Two views, both covering the trailing 200-call window:
      - `latency`: per-stage p50/p95 ms from /v1/wiki/search calls
        (tokenize / score / sort+return / total).
      - `groundedness`: per-call ROUGE-L F1, Citation Recall, Citation
        Precision averages from /v1/wiki/qa calls -- the
        "is the model hallucinating?" signal the operator watches.

    Same dev-only-ish posture as `/_debug/metrics`: the data here is
    operational, not customer-facing, but it is still behind the JWT
    gate so an unauthenticated probe can't enumerate timing."""
    return {
        "latency": search_metrics.stats(),
        "groundedness": groundedness_metrics.stats(),
    }


@app.post("/v1/wiki/qa", response_model=QaResponse)
def wiki_qa(
    body: QaBody,
    principal_id: str = Depends(require_principal),
) -> QaResponse:
    """Search + LLM answer + per-sentence groundedness via three
    published metrics: ROUGE-L F1 (Lin, 2004), Citation Recall and
    Citation Precision (Honovich et al., 2022).

    The LLM is prompted to ground every claim with a `[ref_id]`
    citation. Each sentence is then scored by ROUGE-L F1 over the
    union of its cited evidence; per-sentence P/R are reported so a
    reviewer can see *why* a sentence scored as it did.
    """
    import time as _time

    started = _time.monotonic()
    # 1. Search the corpus for top-k evidence.
    try:
        hits = wiki_corpus.search(body.corpus_id, body.query, top_k=body.top_k)
    except wiki_corpus.UnknownCorpusError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"corpus_id not found: {exc.corpus_id}",
        ) from exc

    # 2. Build an evidence map keyed by ref_id so the groundedness
    #    scorer can resolve `[ref-x]` citations to their text.
    entry = wiki_corpus.get_registry().get(body.corpus_id)
    evidence_map: dict[str, str] = {}
    for h in hits:
        try:
            evidence_map[h.ref_id] = entry.adapter.read_evidence(h.ref_id, limit=2000)
        except Exception:  # noqa: BLE001
            evidence_map[h.ref_id] = ""

    # 3. Compose the prompt. Force `[ref_id]` citations by example and
    #    require a refusal if no relevant evidence was found.
    if not hits:
        # The empty-hits case is itself a metric: a high rate of
        # queries returning no evidence means the corpus is being
        # queried for things it doesn't contain, OR the index is
        # broken. Record it the same way as a normal answer so the
        # dashboard's "accuracy / hallucination" panel reflects the
        # true state of the system.
        groundedness_metrics.record(
            GroundednessSample(
                rouge_l_f1=0.0,
                citation_recall=0.0,
                citation_precision=0.0,
            )
        )
        return QaResponse(
            query=body.query,
            corpus_id=body.corpus_id,
            answer=(
                "I could not find relevant evidence in the picked wiki "
                "directory for that question."
            ),
            overall_rouge_l_f1=0.0,
            citation_recall=0.0,
            citation_precision=0.0,
            sentences=[],
            hits=[],
        )

    evidence_blob = "\n\n--\n\n".join(
        f"[{h.ref_id}] (source: {h.source_path}, score: {h.score:.3f})\n"
        f"{evidence_map[h.ref_id]}"
        for h in hits
    )
    prompt = (
        "You are an OSS-maintainer assistant. Answer the question using "
        "ONLY the evidence below. Cite every claim with a bracketed "
        "[ref_id] matching one of the evidence entries. If the evidence "
        "does not support a claim, refuse explicitly rather than guessing.\n\n"
        f"Question: {body.query}\n\n## Evidence\n\n{evidence_blob}\n\n## Answer\n"
    )

    settings = get_settings()
    adapter = make_adapter(settings)
    try:
        chat = adapter.chat([{"role": "user", "content": prompt}])
        answer = (chat.content or "").strip()
    finally:
        adapter.close()

    # 4. Per-sentence attribution via three published metrics.
    #    - ROUGE-L F1 (Lin, 2004) — sentence ↔ cited-evidence overlap
    #    - Citation Recall + Precision (Honovich et al., 2022)
    scores = groundedness.groundedness_for_answer(answer, evidence_map)
    overall_rouge_l = groundedness.answer_overall_rouge_l(scores)
    cit_recall = groundedness.answer_citation_recall(scores)
    cit_precision = groundedness.answer_citation_precision(scores)
    # Record one groundedness sample per call -- the dashboard's
    # "Accuracy / hallucination" panel aggregates these over the
    # trailing 200-call window so a reviewer can see whether the
    # model is drifting, not just what one turn did.
    groundedness_metrics.record(
        GroundednessSample(
            rouge_l_f1=overall_rouge_l,
            citation_recall=cit_recall,
            citation_precision=cit_precision,
        )
    )
    duration_ms = int((_time.monotonic() - started) * 1000)
    log.info(
        "wiki qa: principal=%s corpus_id=%s hits=%d sentences=%d "
        "rouge_l=%.3f cite_recall=%.3f cite_prec=%.3f duration_ms=%d",
        principal_id, body.corpus_id, len(hits), len(scores),
        overall_rouge_l, cit_recall, cit_precision, duration_ms,
    )
    return QaResponse(
        query=body.query,
        corpus_id=body.corpus_id,
        answer=answer,
        overall_rouge_l_f1=overall_rouge_l,
        citation_recall=cit_recall,
        citation_precision=cit_precision,
        sentences=[SentenceScore(**s.to_dict()) for s in scores],
        hits=[WikiHit(**h.to_dict()) for h in hits],
    )
