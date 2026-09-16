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
    """Patch the LLM adapter so we don't need a real provider.

    Verifies the API surfaces the three published metrics:
      - per-sentence ROUGE-L F1 (Lin, 2004)
      - answer-level overall_rouge_l_f1
      - answer-level citation_recall + citation_precision (Honovich, 2022)
    """
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
    # Sentence 1 fully matches the evidence; sentence 2 is disjoint and
    # cites a fabricated ref so we can verify citation_precision < 1.
    class _StubAdapter:
        def chat(self, messages, **kwargs):
            class _Result:
                content = (
                    "PostgresSaver writes durable checkpoints. [ref] "
                    "MongoDB clusters horizontally. [ref-bogus]"
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
    # Per-sentence: all three published metrics surface in the response.
    for s in body["sentences"]:
        for field_name in (
            "rouge_l_f1",
            "rouge_l_precision",
            "rouge_l_recall",
            "cited_refs",
            "unresolved_refs",
        ):
            assert field_name in s, f"missing metric: {field_name}"
    # Sentence 1: sentence tokens are a strict subsequence of evidence,
    # so LCS == len(sentence) == 4. P = 4/4 = 1.0; R = 4/12 = 0.333;
    # F1 = 2*P*R/(P+R) = 0.5. This is the standard ROUGE-L behaviour for a
    # short sentence vs longer evidence — the harmonic mean penalises
    # the unbalanced coverage even when every sentence token is present.
    assert body["sentences"][0]["rouge_l_f1"] == pytest.approx(0.5, abs=0.01)
    assert body["sentences"][0]["rouge_l_precision"] == pytest.approx(1.0, abs=0.01)
    assert body["sentences"][0]["rouge_l_recall"] == pytest.approx(4 / 12, abs=0.01)
    # Sentence 2: disjoint from evidence -> ROUGE-L F1 = 0.0.
    assert body["sentences"][1]["rouge_l_f1"] == pytest.approx(0.0, abs=0.01)
    # Sentence 2 also has an unresolved citation -> reflected in field.
    assert "ref-bogus" in body["sentences"][1]["unresolved_refs"]
    # Answer-level: three published metrics all surface.
    for field_name in ("overall_rouge_l_f1", "citation_recall", "citation_precision"):
        assert field_name in body, f"missing answer-level metric: {field_name}"
    # Macro-average ROUGE-L F1 across the two sentences = (0.5 + 0.0) / 2.
    assert body["overall_rouge_l_f1"] == pytest.approx(0.25, abs=0.01)
    # Citation Recall: 1 of 2 sentences has a resolved citation -> 0.5.
    assert body["citation_recall"] == pytest.approx(0.5, abs=0.01)
    # Citation Precision: 1 valid (ref) + 1 invalid (ref-bogus) out of 2 -> 0.5.
    assert body["citation_precision"] == pytest.approx(0.5, abs=0.01)


def test_qa_returns_404_for_unknown_corpus(client: TestClient, bearer: dict) -> None:
    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": "nonexistent", "query": "anything"},
        headers=bearer,
    )
    assert r.status_code == 404


# ---- Dev-mode auto-mint (Phase 9 UX) ----


@pytest.fixture
def dev_mode_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable AGENTOPS_ALLOW_DEV_TOKEN=1 and reset the settings cache."""
    monkeypatch.setenv("AGENTOPS_ALLOW_DEV_TOKEN", "1")
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    import agentops_workbench.settings as _settings
    _settings._settings = None
    yield
    _settings._settings = None


@pytest.fixture
def dev_mode_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure AGENTOPS_ALLOW_DEV_TOKEN=0 and reset the settings cache."""
    monkeypatch.setenv("AGENTOPS_ALLOW_DEV_TOKEN", "0")
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    import agentops_workbench.settings as _settings
    _settings._settings = None
    yield
    _settings._settings = None


def test_dev_mode_status_reports_enabled(
    client: TestClient, dev_mode_on: None
) -> None:
    r = client.get("/v1/auth/dev-mode")
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert r.json()["provider"] == "local-fake"


def test_dev_mode_status_reports_disabled_by_default(
    client: TestClient,
) -> None:
    """With AGENTOPS_ALLOW_DEV_TOKEN unset, dev-mode is off and the
    endpoint reports it."""
    import agentops_workbench.settings as _settings
    _settings._settings = None  # ensure fresh read
    r = client.get("/v1/auth/dev-mode")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_dev_token_endpoint_returns_jwt_when_enabled(
    client: TestClient, dev_mode_on: None
) -> None:
    r = client.get("/v1/auth/dev-token", params={"principal_id": "reviewer"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["token"], str) and len(body["token"]) > 50
    assert body["principal_id"] == "reviewer"
    assert body["expires_in"] > 0
    # Token must actually authenticate. Use /v1/wiki/index-files with
    # an empty body — auth is the gate we want to verify, the 200 is
    # the success path (corpus_id for an empty corpus).
    r2 = client.post(
        "/v1/wiki/index-files",
        json={"files": []},
        headers={"Authorization": f"Bearer {body['token']}"},
    )
    assert r2.status_code == 200, r2.text


def test_dev_token_endpoint_refuses_when_disabled(
    client: TestClient, dev_mode_off: None
) -> None:
    r = client.get("/v1/auth/dev-token", params={"principal_id": "reviewer"})
    assert r.status_code == 403


def test_dev_token_uses_default_principal_when_blank(
    client: TestClient, dev_mode_on: None
) -> None:
    r = client.get("/v1/auth/dev-token", params={"principal_id": "  "})
    assert r.status_code == 200
    assert r.json()["principal_id"] == "dev-user"
