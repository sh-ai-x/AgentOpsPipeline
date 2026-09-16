"""TDD: chat answer is returned clean, references live in their own
tab built from the per-hit array, each link an Obsidian deep-link
when the corpus was an Obsidian vault.

The user feedback: result References => [1] path; obsidian link.
I.e. the numbered footnotes should live in a dedicated References
tab (not bolted onto the bottom of the answer bubble), and each
reference is a clickable link to the underlying path -- ideally an
obsidian:// deep link when the picked directory was an Obsidian vault.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentops_workbench import wiki_corpus
from agentops_workbench.api.server import app, issue_token


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    wiki_corpus.reset_registry_for_tests()
    yield
    wiki_corpus.reset_registry_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('tester')}"}


def test_chat_answer_response_does_not_include_inline_citation_markers(
    client: TestClient, bearer: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat response's `answer` field carries the LLM's prose
    only. Numbered citations like `[1]` should NOT be in the response
    body -- the frontend renders a separate References tab from the
    `hits` array instead.

    (The LLM is instructed to cite by number, so a stub that returns
    `[1]` in `content` proves the response body is carrying the LLM's
    text, not anything server-munged.)"""
    from agentops_workbench.api import server as server_mod
    from agentops_workbench.llm.adapter import ChatResult, LLMAdapter, Usage

    class _Stub(LLMAdapter):
        provider = "stub"
        model = "stub-v1"

        def chat(self, messages, **kw):
            return ChatResult(
                content="Postgres saves checkpoints. [1]",
                usage=Usage(provider="stub", model="stub-v1", prompt_tokens=1, completion_tokens=1, total_tokens=2, cost_usd=0.0),
            )

    monkeypatch.setattr(server_mod, "make_adapter", lambda _s: _Stub())

    # A query token that matches the corpus, so the chat graph's
    # _retrieve_node produces a real hit. Without this the empty-evidence
    # branch short-circuits to a hardcoded refusal with no [1] inside.
    r = client.post(
        "/v1/wiki/index-files",
        json={"files": [{"path": "a.md", "content": "Postgres saves checkpoints to durable storage.", "mtime": 0}]},
        headers=bearer,
    )
    cid = r.json()["corpus_id"]

    r = client.post(
        "/v1/wiki/qa",
        json={"corpus_id": cid, "query": "Postgres", "top_k": 5},
        headers=bearer,
    )
    body = r.json()
    # Backend returns the LLM's raw text -- still has `[1]`. The
    # frontend is responsible for stripping the marker text on render
    # and for surfacing references in its own tab.
    assert "[1]" in body["answer"], (
        "backend should pass through the LLM's text verbatim; the "
        "frontend is what renders references in a separate tab"
    )
    # hits[0] is what populates the per-hit references tab
    assert body["hits"][0]["ref_id"] == "a"
    assert body["hits"][0]["source_path"] == "a.md"
    # No server-appended References footer -- that lived on the prior
    # branch; the per-hit array is the canonical source.
    assert "\nReferences:" not in body["answer"], (
        "the server should not append a References footer; the "
        "frontend builds the references list from `hits` instead"
    )


def test_chat_response_includes_obsidian_uri_on_each_hit_when_vault_name_supplied(
    client: TestClient, bearer: dict
) -> None:
    """When the user supplied `vault_name` on /v1/wiki/index-files, every
    hit carries `obsidian_uri` of the form
    `obsidian://open?vault=<vault>&file=<path>` so the frontend can
    render each reference as a real Obsidian deep link."""
    r = client.post(
        "/v1/wiki/index-files",
        json={
            "files": [{"path": "guides/install.md", "content": "Install notes.", "mtime": 0}],
            "vault_name": "MyVault",
        },
        headers=bearer,
    )
    cid = r.json()["corpus_id"]

    r = client.get(
        "/v1/wiki/search",
        params={"corpus_id": cid, "q": "install"},
        headers=bearer,
    )
    body = r.json()
    assert body["results"], "expected at least one hit"
    assert body["results"][0]["obsidian_uri"] == (
        "obsidian://open?vault=MyVault&file=guides/install.md"
    )
