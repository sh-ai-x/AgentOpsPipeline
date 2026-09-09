"""Streamlit UI - submit a task, view evidence, approve or cancel a run.

Step 6 wires the API worker. For now this calls the FastAPI surface directly.
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

import streamlit as st

from agentops_workbench.api.server import issue_token


def _api_base() -> str:
    return os.environ.get("AGENTOPS_API_BASE", "http://127.0.0.1:8000")


def _post_run(token: str, task: str, graph_version: str = "fixed-v1", prompt_version: str = "v1_baseline") -> dict:
    body = json.dumps({
        "task": task,
        "graph_version": graph_version,
        "prompt_version": prompt_version,
    }).encode()
    req = urllib.request.Request(
        f"{_api_base()}/v1/runs",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read())


def _get_run(token: str, run_id: str) -> dict:
    req = urllib.request.Request(
        f"{_api_base()}/v1/runs/{run_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def _strip_think(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def main() -> None:
    st.set_page_config(page_title="AgentOps Workbench", page_icon="🛠️", layout="wide")
    st.title("AgentOps Workbench")
    st.caption("Submit a software issue. Inspect evidence. Approve or cancel a run.")

    with st.sidebar:
        st.header("Identity")
        principal = st.text_input(
            "principal_id",
            value=os.environ.get("DEV_PRINCIPAL_ID", "demo-user"),
        )
        token = issue_token(principal)
        st.code(token, language="text")
        st.caption("Bearer token (HS256 JWT, dev secret)")
        st.divider()
        st.header("API endpoint")
        api_base = st.text_input("base URL", value=_api_base())
        os.environ["AGENTOPS_API_BASE"] = api_base
        st.caption(f"Submit -> {api_base}/v1/runs")

    st.header("New run")
    task = st.text_area(
        "Task",
        value="How do I configure LangGraph checkpointing with PostgreSQL?",
        height=120,
    )

    if st.button("Submit", type="primary") and task.strip():
        with st.spinner("Calling FastAPI /v1/runs ..."):
            try:
                resp = _post_run(token, task.strip())
            except Exception as exc:
                st.error(f"API call failed: {exc}")
                return

        st.divider()
        st.subheader(f"Run {resp.get('id', '?')[:12]}")
        st.caption(f"state = `{resp.get('state')}`")

        col1, col2, col3 = st.columns(3)
        col1.metric("tokens", resp.get("total_tokens", 0))
        col2.metric("cost (USD)", f"${resp.get.get('cost_usd', 0.0):.4f}" if hasattr(resp.get, "get") else f"${resp.get('cost_usd', 0.0):.4f}")
        col3.metric("tool calls", len(resp.get("tool_calls", [])))

        answer = resp.get("answer") or ""
        cleaned = _strip_think(answer)
        if cleaned:
            st.markdown("### Answer")
            st.markdown(cleaned)

        if resp.get("error"):
            st.error(f"error: {resp['error']}")


if __name__ == "__main__":
    main()
