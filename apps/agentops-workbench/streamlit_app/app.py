"""Streamlit UI — submit a task, view evidence, approve or cancel a run.

Step 2 ships a minimal skeleton. Step 6 layers in OTel viewer + run diff.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the package importable when streamlit runs this file directly
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import streamlit as st  # noqa: E402

from agentops_workbench.api.server import issue_token  # noqa: E402


def _api_base() -> str:
    return os.environ.get("AGENTOPS_API_BASE", "http://127.0.0.1:8000")


def main() -> None:
    st.set_page_config(page_title="AgentOps Workbench", page_icon="🛠️", layout="wide")
    st.title("AgentOps Workbench")
    st.caption("Submit a software issue. Inspect evidence. Approve or cancel a run.")

    with st.sidebar:
        st.header("Identity")
        principal = st.text_input("principal_id", value=os.environ.get("DEV_PRINCIPAL_ID", "dev-user"))
        st.code(issue_token(principal), language="text")
        st.caption("Use the token above as a Bearer token against the API.")

    st.header("New run")
    task = st.text_area("Task", placeholder="e.g. How do I configure LangGraph checkpointing with Postgres?")
    if st.button("Submit", type="primary") and task:
        st.info(f"POST {_api_base()}/v1/runs — implementation lands when the API worker is wired in step 6.")


if __name__ == "__main__":
    main()
