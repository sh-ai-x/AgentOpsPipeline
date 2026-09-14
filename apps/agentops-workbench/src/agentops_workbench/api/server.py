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
:root {
  --bg: #fafafa;
  --fg: #1a1a1a;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #2563eb;
  --accent-bg: #eff6ff;
  --warn-bg: #fef3c7;
  --warn-fg: #92400e;
  --issue-bg: #fef2f2;
  --issue-fg: #b91c1c;
  --wiki-bg: #f0fdf4;
  --wiki-fg: #166534;
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
.status-pill { display: inline-flex; align-items: center; gap: 6px;
                padding: 3px 9px; border-radius: 999px; font-size: 11px;
                font-weight: 500; margin-left: 8px; background: #f0fdf4; color: #166534 }
form { background: white; border: 1px solid var(--border); border-radius: 10px;
       padding: 16px; margin: 16px 0; display: grid;
       grid-template-columns: 1fr 2fr 1fr auto; gap: 8px }
input[type=text] { padding: 9px 12px; border: 1px solid var(--border);
                   border-radius: 6px; font: inherit; background: white }
input[type=text]:focus { outline: 2px solid var(--accent); outline-offset: -1px;
                         border-color: transparent }
input[type=text]::placeholder { color: #9ca3af }
button { padding: 9px 18px; border: 0; border-radius: 6px; background: var(--fg);
         color: white; cursor: pointer; font: inherit; font-weight: 500 }
button:hover { background: #000 }
button:disabled { background: var(--muted); cursor: progress }
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
.banner-auth { background: #fef2f2; color: #991b1b;
               padding: 14px 18px; border-radius: 8px; margin: 16px 0;
               font-size: 14px; border: 1px solid #fca5a5;
               border-left: 4px solid #dc2626 }
.banner-auth strong { font-weight: 600 }
.banner-auth code { background: rgba(0,0,0,0.06); padding: 1px 6px;
                  border-radius: 3px; font-family: ui-monospace, monospace;
                  font-size: 13px }
.ref-list { list-style: none; padding: 0; margin: 0 }
.ref-list li { padding: 10px 0; border-bottom: 1px solid var(--border);
              display: flex; gap: 10px; align-items: flex-start }
.ref-list li:last-child { border-bottom: 0 }
.ref-badge { flex-shrink: 0; font-family: ui-monospace, monospace; font-size: 12px;
             padding: 3px 8px; border-radius: 4px; font-weight: 600;
             text-decoration: none; min-width: 80px; text-align: center }
.ref-badge.github-issue { background: var(--issue-bg); color: var(--issue-fg) }
.ref-badge.wiki { background: var(--wiki-bg); color: var(--wiki-fg) }
.ref-content { flex: 1; min-width: 0 }
.ref-title { font-size: 14px; line-height: 1.35; margin: 0 0 4px; word-wrap: break-word }
.ref-title a { color: var(--fg); text-decoration: none }
.ref-title a:hover { text-decoration: underline }
.ref-score { font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace }
.answer { white-space: pre-wrap; background: var(--code-bg); padding: 16px;
          border-radius: 8px; font: 14px/1.55 ui-monospace, monospace;
          border: 1px solid var(--border); margin: 0 }
.empty { color: var(--muted); padding: 16px;
          background: #f9fafb; border: 1px dashed var(--border);
          border-radius: 6px; text-align: center; font-size: 13px }
.empty code { background: rgba(0,0,0,0.05); padding: 1px 5px;
            border-radius: 3px; font-family: ui-monospace, monospace;
            font-size: 12px }
.loading { display: inline-block; padding: 9px 18px; background: var(--muted);
           color: white; border-radius: 6px; opacity: 0.7;
           font: 14px/1 inherit; font-weight: 500 }
@media (max-width: 640px) {
  form { grid-template-columns: 1fr; }
  .ref-list li { flex-direction: column; gap: 6px }
  .ref-badge { align-self: flex-start }
}
</style></head><body>
<header>
<h1>agentops-oss-helper</h1>
<p class="tagline">Open Source Maintainer Helper Agent &mdash; paste a public
GitHub repo, get a grounded triage with citations from that repo's own
docs and issues/PRs.</p>
</header>
{repo_header}
<form method="post" action="/oss-helper">
  <input type="text" name="repo_url" required autofocus
         placeholder="https://github.com/<owner>/<repo>"
         value="{repo_url_value}">
  <input type="text" name="question"
         placeholder="optional question">
  <input type="text" name="issue_number"
         placeholder="issue #">
  <button type="submit">Run</button>
</form>
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
        body = _format_oss_helper_html(repo_url) + (
            f'<p class="warn">{_html.escape(str(exc))}</p></body></html>'
        )
        return HTMLResponse(body)
    except Exception as exc:  # noqa: BLE001
        log.exception("oss-helper run failed")
        body = _format_oss_helper_html(repo_url) + (
            f'<p class="warn">Internal error: {_html.escape(repr(exc))}</p></body></html>'
        )
        return HTMLResponse(body)
    return HTMLResponse(_render_oss_helper_report(repo_url, result))


def _title(label: str, count: int) -> str:
    """Section title with a count badge."""
    return (
        f'<div class="section-title">{label}'
        f'<span class="count">{count}</span></div>'
    )


def _render_oss_helper_report(repo_url: str, result: oss_helper.TriageResult) -> str:
    """Render the TriageResult as HTML. Inline-only -- no client-side JS,
    no external assets, no Streamlit dependency."""
    # Top-of-result hero: the repo the user is looking at, with a status
    # pill showing how many citations the agent found.
    github_url = f"https://github.com/{result.owner}/{result.repo}"
    repo_header = (
        f'<div class="repo-badge">'
        f'<span class="octicon">&#9737;</span>'
        f'<a href="{_html.escape(github_url)}" style="color:inherit;text-decoration:none">'
        f'{_html.escape(result.owner)}/{_html.escape(result.repo)}</a>'
        f'<span class="status-pill">'
        f'{len(result.wiki_refs)} docs &middot; {len(result.issue_refs)} issues '
        f'&middot; {result.duration_ms}ms</span>'
        f'</div>'
    )

    warns = "".join(
        f'<p class="warn">{_html.escape(w)}</p>' for w in result.warnings
    )

    issue_n = result.issue_number
    issue_label = f" &middot; focused on issue #{issue_n}" if issue_n else ""

    # If GitHub auth was missing OR the search itself failed, surface a
    # prominent banner so the user knows the 0-issue-refs result was a
    # permission/availability problem, not an empty repo. (Per ADR-0008
    # / phase 8 exit criterion 2: visible failure modes for a triage tool.)
    auth_warning = next(
        (w for w in result.warnings
         if "AGENTOPS_GITHUB_TOKEN" in w or "Validation Failed" in w
         or "github issues search failed" in w.lower()),
        None,
    )
    if auth_warning:
        banner = (
            '<div class="banner-auth">'
            '<strong>GitHub auth required for issue/PR search.</strong><br>'
            'Set <code>AGENTOPS_GITHUB_TOKEN</code> in the server '
            'environment, or pass <code>github_token=...</code> to the '
            f'flow.<br><em style="font-size:12px;opacity:0.85">{_html.escape(auth_warning)}</em>'
            '</div>'
        )
    else:
        banner = ""

    meta_row = (
        f'<div class="meta-row">'
        f'<span class="meta-chip">docs: <strong>{len(result.wiki_refs)}</strong></span>'
        f'<span class="meta-chip">issues/PRs: <strong>{len(result.issue_refs)}</strong></span>'
        f'<span class="meta-chip">duration: <strong>{result.duration_ms}ms</strong></span>'
        f'<span class="meta-chip">provider: <strong>{_html.escape(_provider_name())}</strong></span>'
        f'{issue_label}'
        f'</div>'
    )

    answer_section = (
        '<section class="section">'
        f'{_title("Answer", "")}'
        f'<div class="answer">{_html.escape(result.answer)}</div>'
        '</section>'
    )

    issue_section = _render_refs_section(
        "Issue / PR evidence",
        result.issue_refs,
        owner=result.owner, repo=result.repo,
    )
    wiki_section = _render_refs_section(
        "Docs evidence (from repo's own docs/README)",
        result.wiki_refs,
        owner=result.owner, repo=result.repo,
    )

    return (
        _format_oss_helper_html(repo_url, repo_header=repo_header)
        + warns
        + meta_row
        + banner
        + answer_section
        + issue_section
        + wiki_section
        + '</body></html>'
    )


def _render_refs_section(
    title: str, refs: list[dict], *, owner: str, repo: str
) -> str:
    """Render one evidence section: header + list of clickable refs.

    Issue/PR refs link to the actual GitHub page; wiki refs link to the
    blob at HEAD on the repo (the wiki adapter doesn't track an exact
    file path because paths get flattened during acquisition, so we point
    at the repo root and the user can browse from there)."""
    if not refs:
        return (
            f'<section class="section">'
            f'<h3 class="section-title">{_html.escape(title)}</h3>'
            f'<p class="empty">No matching evidence found.</p>'
            f'</section>'
        )
    items = []
    for r in refs:
        rid = str(r.get("ref_id", ""))
        title_text = str(r.get("title", ""))
        source_kind = str(r.get("source_kind", ""))
        score = r.get("score", 0)
        if source_kind == "github-issue" and rid.isdigit():
            url = f"https://github.com/{owner}/{repo}/issues/{rid}"
            badge_cls = "github-issue"
            badge_text = f"#{rid}"
        else:
            url = f"https://github.com/{owner}/{repo}"
            badge_cls = "wiki"
            badge_text = rid or "wiki"
        items.append(
            f'<li>'
            f'<a class="ref-badge {badge_cls}" href="{_html.escape(url)}" '
            f'target="_blank" rel="noopener">{_html.escape(badge_text)}</a>'
            f'<div class="ref-content">'
            f'<div class="ref-title"><a href="{_html.escape(url)}" '
            f'target="_blank" rel="noopener">{_html.escape(title_text)}</a></div>'
            f'<div class="ref-score">score: {score:.2f}</div>'
            f'</div>'
            f'</li>'
        )
    empty = (
        f'<div class="empty">No matching {_html.escape(title).lower()} found. '
        f'This may be a permission/availability issue, not an empty repo '
        f'— check the warnings above for AGENTOPS_GITHUB_TOKEN / '
        f'GitHub API errors.</div>'
    ) if not refs else ''
    return (
        f'<section class="section">'
        f'{_title(_html.escape(title), len(refs))}'
        + empty
        + '<ul class="ref-list">' + "".join(items) + '</ul>'
        + '</section>'
    )


def _provider_name() -> str:
    """Best-effort read of the current provider setting for the status row.
    Falls back to '?' if Settings isn't reachable (e.g. during a probe)."""
    try:
        from ..settings import get_settings
        return get_settings().provider
    except Exception:  # noqa: BLE001
        return "?"


def _format_oss_helper_html(
    repo_url: str, *, repo_header: str = ""
) -> str:
    """Substitute the per-request URL into the HTML template.

    Uses str.replace (not str.format) because the template's CSS contains
    brace literals that str.format would mis-parse as placeholders.
    """
    return _OSS_HELPER_HTML.replace(
        "{repo_url_value}", _html.escape(repo_url or "")
    ).replace(
        "{repo_header}", repo_header or ""
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


def make_test_client() -> TestClient:
    return TestClient(app)
