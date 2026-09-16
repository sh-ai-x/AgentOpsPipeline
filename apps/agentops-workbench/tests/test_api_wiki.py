"""TDD: /v1/wiki/{index-files,search,qa} endpoints.

AC1 — the browser POSTs uploaded files; the server returns corpus_id.
AC2 — search routes through the existing WikiRagAdapter (TF-IDF +
cosine), the same path used by planner_executor/single_agent.
AC3 — every search hit carries source_path, evidence_span, score,
coverage, contributing_terms, mtime. /qa additionally returns
per-sentence groundedness.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentops_workbench import wiki_corpus
from agentops_workbench.api.server import app, issue_token


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Drop any state from a previous test before this one runs."""
    wiki_corpus.reset_registry_for_tests()
    yield
    wiki_corpus.reset_registry_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('tester')}"}


# ---- AC1: directory picker → server → corpus_id ----


def test_index_files_requires_auth(client: TestClient) -> None:
    """Unauthenticated POSTs are refused at the JWT gate (401)."""
    r = client.post("/v1/wiki/index-files", json={"files": []})
    assert r.status_code == 401


def test_index_files_accepts_empty_list(client: TestClient, bearer: dict) -> None:
    r = client.post("/v1/wiki/index-files", json={"files": []}, headers=bearer)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "corpus_id" in body
    assert body["doc_count"] == 0


def test_index_files_creates_corpus_with_provided_files(
    client: TestClient, bearer: dict
) -> None:
    payload = {
        "files": [
            {
                "path": "notes/install.md",
                "content": (
                    "# Install\n"
                    "Install LangGraph with PostgreSQL checkpointing.\n"
                ),
                "mtime": 1_700_000_000_000,
            },
            {
                "path": "notes/auth.md",
                "content": (
                    "# Auth\n"
                    "JWT with HS256, generate a 48-byte secret.\n"
                ),
                "mtime": 1_700_000_001_000,
            },
        ]
    }
    r = client.post("/v1/wiki/index-files", json=payload, headers=bearer)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["doc_count"] == 2
    assert isinstance(body["corpus_id"], str) and len(body["corpus_id"]) >= 16


def test_index_files_rejects_unsafe_paths(client: TestClient, bearer: dict) -> None:
    payload = {
        "files": [
            {"path": "../escape.md", "content": "x", "mtime": 0},
        ]
    }
    r = client.post("/v1/wiki/index-files", json=payload, headers=bearer)
    assert r.status_code == 400


def test_index_files_rejects_absolute_paths(client: TestClient, bearer: dict) -> None:
    payload = {
        "files": [
            {"path": "/etc/passwd", "content": "x", "mtime": 0},
        ]
    }
    r = client.post("/v1/wiki/index-files", json=payload, headers=bearer)
    assert r.status_code == 400


# ---- AC2: search routes through WikiRagAdapter ----


def test_search_requires_auth(client: TestClient) -> None:
    r = client.get("/v1/wiki/search", params={"corpus_id": "x", "q": "anything"})
    assert r.status_code == 401


def test_search_returns_404_for_unknown_corpus(
    client: TestClient, bearer: dict
) -> None:
    r = client.get(
        "/v1/wiki/search",
        params={"corpus_id": "nonexistent", "q": "anything"},
        headers=bearer,
    )
    assert r.status_code == 404


def test_search_after_index_returns_results_with_provenance(
    client: TestClient, bearer: dict
) -> None:
    # Index two files via the upload endpoint.
    r = client.post(
        "/v1/wiki/index-files",
        json={
            "files": [
                {
                    "path": "guides/install.md",
                    "content": (
                        "# Install\n"
                        "Install LangGraph with PostgreSQL checkpointing.\n"
                        "Use pip install langgraph[postgres].\n"
                    ),
                    "mtime": 1_700_000_000_000,
                },
                {
                    "path": "guides/auth.md",
                    "content": (
                        "# Auth\n"
                        "JWT with HS256, generate a 48-byte secret.\n"
                    ),
                    "mtime": 1_700_000_001_000,
                },
            ]
        },
        headers=bearer,
    )
    corpus_id = r.json()["corpus_id"]

    # Search and check the AC3 trust fields land in the response.
    r = client.get(
        "/v1/wiki/search",
        params={"corpus_id": corpus_id, "q": "postgres checkpointing"},
        headers=bearer,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "postgres checkpointing"
    assert body["corpus_id"] == corpus_id
    assert body["results"], "expected at least one hit"
    hit = body["results"][0]
    # AC3 trust fields are all present.
    for field_name in (
        "ref_id",
        "score",
        "source_path",
        "evidence_span",
        "match_offsets",
        "coverage",
        "contributing_terms",
        "mtime",
    ):
        assert field_name in hit, f"missing AC3 field: {field_name}"
    assert hit["source_path"] == "guides/install.md"
    assert hit["mtime"] == 1_700_000_000_000
    assert 0.0 < hit["coverage"] <= 1.0


def test_search_filters_top_k(client: TestClient, bearer: dict) -> None:
    r = client.post(
        "/v1/wiki/index-files",
        json={
            "files": [
                {"path": "a.md", "content": "alpha beta gamma", "mtime": 0},
                {"path": "b.md", "content": "alpha delta epsilon", "mtime": 0},
                {"path": "c.md", "content": "alpha zeta eta", "mtime": 0},
            ]
        },
        headers=bearer,
    )
    corpus_id = r.json()["corpus_id"]
    r = client.get(
        "/v1/wiki/search",
        params={"corpus_id": corpus_id, "q": "alpha", "top_k": 2},
        headers=bearer,
    )
    body = r.json()
    assert len(body["results"]) <= 2


# ---- AC3: /qa returns per-sentence groundedness ----


def test_qa_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": "x", "query": "anything"},
    )
    assert r.status_code == 401


def test_qa_returns_per_sentence_groundedness(
    client: TestClient, bearer: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patch the LLM adapter so we don't need a real provider."""
    # Index one doc whose evidence supports a fully-grounded claim.
    r = client.post(
        "/v1/wiki/index-files",
        json={
            "files": [
                {
                    "path": "ref.md",
                    "content": (
                        "PostgresSaver writes durable checkpoints to "
                        "a PostgreSQL table for long-running agents."
                    ),
                    "mtime": 0,
                }
            ]
        },
        headers=bearer,
    )
    corpus_id = r.json()["corpus_id"]

    # Patch the QA adapter factory to a stub that returns a known answer.
    from agentops_workbench.api import server as server_mod

    # The corpus contains one file `ref.md` (flat file -> ref_id "ref").
    class _StubAdapter:
        def chat(self, messages, **kwargs):
            class _Result:
                content = (
                    "PostgresSaver writes durable checkpoints. [ref] "
                    "MongoDB is unrelated. [ref]"
                )
            return _Result()

        last_usage = None

        def close(self) -> None:
            pass

    def _stub_factory(_settings):
        return _StubAdapter()

    monkeypatch.setattr(server_mod, "make_adapter", _stub_factory)

    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": corpus_id, "query": "what is PostgresSaver"},
        headers=bearer,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"]
    assert isinstance(body["sentences"], list)
    assert len(body["sentences"]) == 2
    # The first sentence is fully grounded (every token in evidence).
    assert body["sentences"][0]["score"] == pytest.approx(1.0, abs=0.01)
    # The second sentence has zero overlap (mongodb not in evidence).
    assert body["sentences"][1]["score"] == pytest.approx(0.0, abs=0.01)
    # Overall = mean of the two.
    assert 0.0 <= body["overall_groundedness"] <= 1.0


def test_qa_returns_404_for_unknown_corpus(client: TestClient, bearer: dict) -> None:
    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": "nonexistent", "query": "anything"},
        headers=bearer,
    )
    assert r.status_code == 404
