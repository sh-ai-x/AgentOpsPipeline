"""TDD regression - step 6 OTel redaction + failure->regression + Docker smoke."""
from __future__ import annotations

from agentops_workbench.observability.otel import Tracer, redact, trace_to_jsonl

# ---- Redaction ----


def test_redact_api_key_in_string() -> None:
    s = "api_key=sk-cp-J5TPJ0MsBam0bI3oMiDhAWf0PyAX7RTWSrw4trQ8rwz0aORn9"
    out = redact(s)
    assert "sk-cp-" not in out
    assert "[REDACTED]" in out


def test_redact_jwt_in_string() -> None:
    s = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.signature123"
    out = redact(s)
    assert "eyJ" not in out
    assert "[REDACTED]" in out


def test_redact_password_in_string() -> None:
    s = "password=hunter2"
    out = redact(s)
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_redact_recursive_in_dict() -> None:
    payload = {
        "headers": {"authorization": "Bearer abc.def.ghi"},
        "body": {"api_key": "sk-secret", "user": "alice"},
    }
    out = redact(payload)
    assert "abc.def.ghi" not in str(out)
    assert "sk-secret" not in str(out)
    assert out["body"]["user"] == "alice"


def test_redact_recursive_in_list() -> None:
    out = redact(["api_key=secret1", "password=secret2", "harmless"])
    assert "secret1" not in str(out)
    assert "secret2" not in str(out)
    assert "harmless" in str(out)


def test_redact_passes_through_non_string() -> None:
    assert redact(42) == 42
    assert redact(None) is None
    assert redact(3.14) == 3.14


# ---- ADR-0011 §Context: redaction defects, verified by execution ----


def test_redact_bearer_token_survives_no_longer() -> None:
    """Pattern-ordering leak: `authorization`'s value class stopped at the
    first space, consuming only the literal word 'Bearer' and leaving the
    real token untouched. `bearer` now runs first and strips it whole."""
    out = redact("Authorization: Bearer abc123xyz")
    assert "abc123xyz" not in out
    assert "[REDACTED]" in out


def test_redact_github_token_via_token_key() -> None:
    out = redact("AGENTOPS_GITHUB_TOKEN=ghp_1234567890abcdef1234")
    assert "ghp_1234567890abcdef1234" not in out
    assert "[REDACTED]" in out


def test_redact_bare_github_token_without_key_prefix() -> None:
    out = redact("token leaked in a log line: ghp_1234567890abcdef1234 end")
    assert "ghp_1234567890abcdef1234" not in out


def test_redact_jwt_secret_env_value() -> None:
    out = redact("AGENTOPS_JWT_SECRET=supersecretvalue1234")
    assert "supersecretvalue1234" not in out
    assert "[REDACTED]" in out


def test_redact_database_dsn_userinfo() -> None:
    out = redact("postgresql://appuser:s3cr3tpw@db.internal:5432/agentops")
    assert "appuser" not in out
    assert "s3cr3tpw" not in out
    assert "db.internal:5432/agentops" in out  # host/db name is not a secret


# ---- Tracer ----


def test_tracer_records_spans() -> None:
    t = Tracer(trace_id="trace-1")
    s1 = t.start("model_call")
    t.end(s1, status="ok", extra={"tokens": 100})
    spans = t.export()
    assert len(spans) == 1
    assert spans[0]["name"] == "model_call"
    assert spans[0]["status"] == "ok"
    assert spans[0]["trace_id"] == "trace-1"
    assert spans[0]["attributes"]["tokens"] == 100


def test_tracer_parent_span_id() -> None:
    t = Tracer(trace_id="trace-2")
    parent = t.start("graph_run")
    child = t.start("tool_call", parent=parent)
    assert child.parent_span_id == parent.span_id
    t.end(child)
    t.end(parent)


def test_tracer_export_redacts_attributes() -> None:
    t = Tracer(trace_id="trace-3")
    s = t.start("api_call", attributes={"headers": {"authorization": "Bearer xyz"}})
    t.end(s)
    spans = t.export()
    assert "Bearer xyz" not in str(spans)


def test_trace_to_jsonl_is_one_per_line() -> None:
    t = Tracer(trace_id="trace-4")
    s1 = t.start("step1")
    t.end(s1)
    s2 = t.start("step2")
    t.end(s2)
    out = trace_to_jsonl(t)
    assert out.count("\n") == 1  # 2 spans -> 1 newline separator
    assert len([line for line in out.split("\n") if line.strip()]) == 2


# ---- Failure->regression (synthetic) ----


def test_seeded_failure_is_caught_by_red_test() -> None:
    """Reproduces the failure->regression pattern.

    If a future change re-introduces the bug 'always_answer_yes', the
    classifier below would fail. The test pins the desired behaviour.
    """
    def classifier(answer: str) -> str:
        # Bug history: an earlier build always returned 'answer' regardless
        # of content. The regression test below would have caught it.
        if "Insufficient evidence" in answer:
            return "refuse"
        if "?" in answer and len(answer.split()) < 5:
            return "clarify"
        return "answer"

    assert classifier("Insufficient evidence in the corpus to answer confidently.") == "refuse"
    assert classifier("Why?") == "clarify"
    assert classifier("Use Postgres with a connection string.") == "answer"


# ---- Docker smoke ----


def test_docker_compose_file_is_present() -> None:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "docker" / "docker-compose.yml"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "postgres" in text
    assert "api" in text
    assert "streamlit" in text
    assert "mcp-document" in text


def test_dockerfile_is_present() -> None:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "docker" / "Dockerfile"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "FROM python" in text
    assert "uv sync" in text
    assert "EXPOSE 8000" in text


def test_runbook_is_present() -> None:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "docs" / "RUNBOOK.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "Bring up the stack" in text
    assert "Switch provider" in text


def test_adr_0006_records_shipping_choice() -> None:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "docs" / "adr" / "0006-topology.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "fixed graph" in text.lower()
    assert "Decision" in text
    assert "Consequences" in text
