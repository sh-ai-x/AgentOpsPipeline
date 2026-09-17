"""ADR-0011 §Decision 6: the API layer wires a real Tracer into wiki_qa /
index_files. These tests drive real requests through the FastAPI app and
assert on the actual span tree an InMemorySpanExporter captured -- the
absence of a test like this is why the untraced call at server.py:1152
(pre-ADR-0011) survived undetected.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentops_workbench import wiki_corpus
from agentops_workbench.api import server as server_mod
from agentops_workbench.api.server import app, issue_token
from agentops_workbench.observability.otel import JsonlFileSpanExporter, RedactingSpanExporter


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    wiki_corpus.reset_registry_for_tests()
    yield
    wiki_corpus.reset_registry_for_tests()


@pytest.fixture(autouse=True)
def _reset_tracer_provider():
    """`_TRACER_PROVIDER` is normally built by `_lifespan`; these tests
    wire it directly so they don't need the app's full startup/shutdown
    cycle. Always restored to None afterwards so other test modules --
    which construct `TestClient(app)` without the lifespan context -- see
    the same untraced-by-default state they always have."""
    yield
    server_mod._TRACER_PROVIDER = None


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('tester')}"}


class _StubAdapter:
    def chat(self, messages, **kwargs):
        class _Result:
            content = "PostgresSaver writes durable checkpoints. [1]"

        return _Result()

    last_usage = None

    def close(self) -> None:
        pass


def _index_one_doc(client: TestClient, bearer: dict) -> str:
    r = client.post(
        "/v1/wiki/index-files",
        json={
            "files": [
                {
                    "path": "ref.md",
                    "content": (
                        "PostgresSaver writes durable checkpoints to a "
                        "PostgreSQL table for long-running agents."
                    ),
                    "mtime": 0,
                }
            ]
        },
        headers=bearer,
    )
    assert r.status_code == 200, r.text
    return r.json()["corpus_id"]


def test_wiki_qa_produces_the_full_span_tree(
    client: TestClient, bearer: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_id = _index_one_doc(client, bearer)
    monkeypatch.setattr(server_mod, "make_adapter", lambda *_a, **_k: _StubAdapter())

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    server_mod._TRACER_PROVIDER = provider

    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": corpus_id, "query": "what is PostgresSaver"},
        headers=bearer,
    )
    assert r.status_code == 200, r.text

    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    assert set(by_name) == {
        "wiki.qa",
        "wiki.qa.search_resample",
        "wiki.search",
        "wiki.qa.llm_chat",
    }

    root = by_name["wiki.qa"]
    assert root.parent is None
    root_span_id = root.get_span_context().span_id
    for child_name in ("wiki.qa.search_resample", "wiki.search", "wiki.qa.llm_chat"):
        child = by_name[child_name]
        assert child.parent is not None
        assert child.parent.span_id == root_span_id, f"{child_name} is not a child of wiki.qa"

    assert root.attributes["corpus_id"] == corpus_id
    assert root.attributes["thread_id"]
    # trace_content defaults to False -- raw query text must not appear,
    # only its length + a hash prefix (ADR-0011 §Decision 5).
    search_span = by_name["wiki.search"]
    assert "query" not in search_span.attributes
    assert search_span.attributes["query_len"] == len("what is PostgresSaver")


def test_wiki_qa_marks_the_root_span_on_unknown_corpus(
    client: TestClient, bearer: dict
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    server_mod._TRACER_PROVIDER = provider

    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": "does-not-exist", "query": "anything"},
        headers=bearer,
    )
    assert r.status_code == 404

    spans = exporter.get_finished_spans()
    by_name = {s.name: s for s in spans}
    root = by_name["wiki.qa"]
    assert root.status.status_code.name == "ERROR"
    assert root.attributes["error_kind"] == "unknown_corpus"


def test_wiki_qa_trace_never_leaks_a_synthetic_secret_to_jsonl(
    client: TestClient, bearer: dict, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Phase 5's exit criterion ("traces do not expose synthetic secrets"),
    demonstrated as an artifact rather than an unfalsifiable claim
    (ADR-0011 §Consequences): drive a turn whose query carries a synthetic
    credential, with AGENTOPS_TRACE_CONTENT=1 so the raw query would
    otherwise reach the span, and assert it is absent from every byte of
    the exported JSONL."""
    import agentops_workbench.settings as settings_mod

    corpus_id = _index_one_doc(client, bearer)
    monkeypatch.setattr(server_mod, "make_adapter", lambda *_a, **_k: _StubAdapter())
    monkeypatch.setenv("AGENTOPS_TRACE_CONTENT", "1")
    settings_mod._settings = None

    exporter = RedactingSpanExporter(JsonlFileSpanExporter(tmp_path))
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    server_mod._TRACER_PROVIDER = provider

    secret_query = "my key is sk-cp-J5TPJ0MsBam0bI3oMiDhAWf0PyAX7RTWSrw4trQ8rwz0aORn9, what is PostgresSaver"
    try:
        r = client.post(
            "/v1/wiki/qa",
            json={"corpus_id": corpus_id, "query": secret_query},
            headers=bearer,
        )
        assert r.status_code == 200, r.text
    finally:
        settings_mod._settings = None

    jsonl_files = list(tmp_path.glob("*.jsonl"))
    assert jsonl_files, "expected at least one trace file"
    for path in jsonl_files:
        text = path.read_text(encoding="utf-8")
        assert "sk-cp-J5TPJ0MsBam0bI3oMiDhAWf0PyAX7RTWSrw4trQ8rwz0aORn9" not in text
        assert "[REDACTED]" in text


async def test_otlp_exporter_without_the_otlp_extra_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_lifespan` refuses to start rather than silently falling back --
    mirrors the insecure-JWT refusal it already performs."""
    import agentops_workbench.settings as settings_mod

    monkeypatch.setenv("AGENTOPS_TRACE_EXPORTER", "otlp")
    settings_mod._settings = None
    try:
        with pytest.raises(RuntimeError, match="uv sync --extra otel --extra otlp"):
            async with server_mod._lifespan(server_mod.app):
                pass
    finally:
        settings_mod._settings = None
        server_mod._TRACER_PROVIDER = None
