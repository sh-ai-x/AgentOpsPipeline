"""Streamlit UI - submit a task, view evidence, approve or cancel a run.

Calls the FastAPI surface over HTTP. The UI never mints an auth token for
an arbitrary principal: the operator pastes a bearer token issued
out-of-band (or, for the offline fake provider only, opts into a local
dev token via AGENTOPS_ALLOW_DEV_TOKEN=1).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

# Make the package importable when streamlit runs this file directly
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import streamlit as st  # noqa: E402 - after sys.path bootstrap above

from agentops_workbench.settings import get_settings  # noqa: E402

_DEFAULT_API_BASE = "http://127.0.0.1:8000"


def _default_api_base() -> str:
    return os.environ.get("AGENTOPS_API_BASE", _DEFAULT_API_BASE)


def _dev_token_allowed() -> bool:
    """Local dev-token minting is offered only for the offline fake provider."""
    if os.environ.get("AGENTOPS_ALLOW_DEV_TOKEN", "").lower() not in {"1", "true", "yes"}:
        return False
    try:
        return get_settings().provider == "local-fake"
    except Exception:
        return False


def _post_run(
    api_base: str,
    token: str,
    task: str,
    graph_version: str = "fixed-v1",
    prompt_version: str = "v1_baseline",
) -> dict:
    body = json.dumps(
        {"task": task, "graph_version": graph_version, "prompt_version": prompt_version}
    ).encode()
    req = urllib.request.Request(
        f"{api_base}/v1/runs",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)  # noqa: S310 - operator-supplied base
    return json.loads(resp.read())


def _get_run(api_base: str, token: str, run_id: str) -> dict:
    req = urllib.request.Request(
        f"{api_base}/v1/runs/{run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = urllib.request.urlopen(req, timeout=30)  # noqa: S310 - operator-supplied base
    return json.loads(resp.read())


def _strip_think(text: str) -> str:
    import re

    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def _resolve_token() -> str:
    with st.sidebar:
        st.header("Identity")
        token = st.text_input(
            "Bearer token (JWT)",
            type="password",
            help="Paste a token issued by the API operator.",
        ).strip()
        if not token and _dev_token_allowed():
            from agentops_workbench.api.server import issue_token

            principal = st.text_input("dev principal_id", value="demo-user")
            if principal.strip():
                token = issue_token(principal.strip())
                st.caption("local dev token (provider=local-fake only)")
    return token


def main() -> None:
    st.set_page_config(page_title="AgentOps Workbench", page_icon="🛠️", layout="wide")
    st.title("AgentOps Workbench")
    st.caption("Submit a software issue. Inspect evidence. Approve or cancel a run.")

    token = _resolve_token()

    with st.sidebar:
        st.divider()
        st.header("API endpoint")
        api_base = st.text_input("base URL", value=_default_api_base()).strip() or _DEFAULT_API_BASE
        st.caption(f"Submit -> {api_base}/v1/runs")

    if not token:
        st.info("Enter a bearer token in the sidebar to submit a run.")
        return

    st.header("New run")
    task = st.text_area(
        "Task",
        value="How do I configure LangGraph checkpointing with PostgreSQL?",
        height=120,
    )

    if st.button("Submit", type="primary") and task.strip():
        with st.spinner("Calling FastAPI /v1/runs ..."):
            try:
                resp = _post_run(api_base, token, task.strip())
            except Exception as exc:
                st.error(f"API call failed: {exc}")
                return

        st.divider()
        st.subheader(f"Run {str(resp.get('id', '?'))[:12]}")
        st.caption(f"state = `{resp.get('state')}`")

        col1, col2, col3 = st.columns(3)
        col1.metric("tokens", resp.get("total_tokens", 0))
        col2.metric("cost (USD)", f"${resp.get('cost_usd', 0.0):.4f}")
        col3.metric("tool calls", len(resp.get("tool_calls", [])))

        cleaned = _strip_think(resp.get("answer") or "")
        if cleaned:
            st.markdown("### Answer")
            st.markdown(cleaned)

        if resp.get("error"):
            st.error(f"error: {resp['error']}")


if __name__ == "__main__":
    main()
