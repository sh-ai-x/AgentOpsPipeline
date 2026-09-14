"""TDD regression -- agentops-oss-helper flow + web route.

Scope:
  - parse_repo_url: accepts the documented URL shapes; rejects garbage.
  - run_oss_helper: against a tiny fixture repo + mocked LLM, produces a
    TriageResult with real evidence refs from both adapters, real
    answer (the LLM was given both evidence blocks).
  - the FastAPI web form: GET returns the HTML, POST returns a render of
    the TriageResult. No live network calls anywhere in this test file.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentops_workbench.api.server import app
from agentops_workbench.llm.adapter import ChatResult, LLMAdapter, Usage
from agentops_workbench.oss_helper import (
    TriageResult,
    parse_repo_url,
    run_oss_helper,
)

# ---- parse_repo_url ----


def test_parse_repo_url_accepts_canonical_form() -> None:
    owner, repo, issue = parse_repo_url("https://github.com/owner/repo")
    assert owner == "owner"
    assert repo == "repo"
    assert issue is None


def test_parse_repo_url_accepts_trailing_slash() -> None:
    o, r, i = parse_repo_url("https://github.com/owner/repo/")
    assert (o, r, i) == ("owner", "repo", None)


def test_parse_repo_url_accepts_dot_git() -> None:
    o, r, i = parse_repo_url("https://github.com/owner/repo.git")
    assert (o, r, i) == ("owner", "repo", None)


def test_parse_repo_url_accepts_embedded_issue() -> None:
    o, r, i = parse_repo_url("https://github.com/owner/repo/issues/42")
    assert (o, r, i) == ("owner", "repo", 42)


def test_parse_repo_url_accepts_hyphens_and_dots() -> None:
    o, r, i = parse_repo_url("https://github.com/my-org/some.repo.js")
    assert (o, r, i) == ("my-org", "some.repo.js", None)


def test_parse_repo_url_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_repo_url("not a url")
    with pytest.raises(ValueError):
        parse_repo_url("https://gitlab.com/foo/bar")  # non-github
    with pytest.raises(ValueError):
        parse_repo_url("https://github.com/foo")        # no repo


# ---- run_oss_helper -- mocked LLM + real wiki, mocked GitHub API ----


class _ScriptedAdapter(LLMAdapter):
    """Returns the queued prompt verbatim as the 'answer' so we can assert
    on what evidence the runner actually composed and sent to the LLM."""

    provider = "scripted-test"
    model = "scripted-v1"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self._last_usage: Usage | None = None

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kw,
    ) -> ChatResult:
        self.calls.append(messages)
        # Echo the user prompt back so the answer literally carries
        # the composed evidence -- lets the test prove the wiring.
        prompt = messages[0]["content"]
        usage = Usage(
            provider=self.provider, model=self.model,
            prompt_tokens=len(prompt), completion_tokens=len(prompt),
            total_tokens=2 * len(prompt), cost_usd=0.0,
        )
        self._last_usage = usage
        return ChatResult(content=prompt, usage=usage)


def _make_repo_tree(tmp_path: Path) -> Path:
    """Create a tiny GitHub-like repo on disk for WikiRagAdapter to read."""
    repo = tmp_path / "owner" / "hello-world"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text(
        "# hello-world\n\nA demo repository for the oss-helper test.\n\n"
        "## installation\n\n`pip install hello-world`\n"
    )
    nested = repo / "docs" / "guide"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "install.md").write_text(
        "# installation guide\n\nDetailed steps for installing hello-world.\n"
    )
    # Also throw in a non-doc file to verify the filter works
    (repo / "main.py").write_text("print('hi')")
    return repo


def test_run_oss_helper_assembles_evidence_and_calls_llm(tmp_path, monkeypatch) -> None:
    """Full flow with a fake-but-real wiki adapter and a fake LLM.

    Mocks:
      - `WikiRagAdapter.__init__` to point at the tmp_path fixture repo
        (avoids network/git entirely)
      - the LLM via a scripted adapter that echoes the prompt back
      - `GitHubIssueAdapter` via a subclass that records calls and returns
        canned results (no httpx mock plumbing needed -- we're testing
        wiring, not the adapter)
    """
    # 1. Build the fake wiki corpus from the tmp repo
    repo = _make_repo_tree(tmp_path)

    # 2. Patch WikiRagAdapter's __init__ to use our local dir
    from agentops_workbench.adapters import wiki_rag
    orig_init = wiki_rag.WikiRagAdapter.__init__

    def patched_init(self, wiki_dir: str) -> None:
        # Replace the fixture-default with our tmp path. Strip the
        # "fixtures/docs" default behaviour entirely.
        orig_init(self, wiki_dir=str(repo))

    monkeypatch.setattr(wiki_rag.WikiRagAdapter, "__init__", patched_init)

    # 3. Patch GitHubIssueAdapter to return canned evidence (no network)
    from agentops_workbench.adapters import github_issue

    class _FakeIssue(github_issue.GitHubIssueAdapter):
        def search_evidence(self, query, top_k=5, window=None, filters=None):
            from datetime import datetime, timezone

            from agentops_workbench.adapters.base import EvidenceRef
            return [
                EvidenceRef(
                    ref_id="42", title="issue: install docs wrong",
                    score=1.0, source_kind="github-issue",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                ),
            ]

        def read_evidence(self, ref_id, offset=0, limit=2000):
            return "User reports the install steps in the README don't match the docs/guide/install.md page."

    monkeypatch.setattr(github_issue, "GitHubIssueAdapter", _FakeIssue)
    # oss_helper imports GitHubIssueAdapter directly via `from .adapters.github_issue import`,
    # so patch BOTH names for the same fake class to take effect.
    import agentops_workbench.oss_helper as _oh
    monkeypatch.setattr(_oh, "GitHubIssueAdapter", _FakeIssue)

    # 4. Stub out the URL parser to return our fake owner/repo
    monkeypatch.setattr(
        "agentops_workbench.oss_helper.parse_repo_url",
        lambda url: ("owner", "hello-world", None),
    )

    # 5. Stub out the bulk-acquisition (no network, no git)
    monkeypatch.setattr(
        "agentops_workbench.oss_helper.bulk_acquire_repo_docs",
        lambda owner, repo, **kw: (repo, []),
    )

    # 6. Run the flow with the scripted LLM
    adapter = _ScriptedAdapter()
    result = run_oss_helper(
        "https://github.com/owner/hello-world",
        question="how do I install?",
        adapter=adapter,
        github_token=None,
    )

    assert isinstance(result, TriageResult)
    assert result.owner == "owner"
    assert result.repo == "hello-world"
    assert result.issue_number is None
    assert result.question == "how do I install?"

    # Both adapters produced real evidence
    assert len(result.wiki_refs) >= 1, result.wiki_refs
    assert len(result.issue_refs) == 1
    assert result.issue_refs[0]["ref_id"] == "42"

    # The LLM was actually called with a prompt that contained both
    # evidence blocks. We prove the wiring by reading what was sent.
    assert len(adapter.calls) == 1
    sent_prompt = adapter.calls[0][0]["content"]
    assert "Docs evidence" in sent_prompt
    assert "Issue/PR evidence" in sent_prompt
    assert "installation" in sent_prompt.lower()  # wiki content present
    assert "install steps in the README" in sent_prompt  # issue content present
    assert "hello-world" in sent_prompt  # repo name in header

    # The LLM echo'd the prompt back as the answer -- proves the answer
    # path actually carries the composed evidence.
    assert "installation" in result.answer.lower()

    # Timing reported (sanity)
    assert result.duration_ms >= 0


def test_run_oss_helper_handles_bad_url() -> None:
    from agentops_workbench.oss_helper import run_oss_helper
    adapter = _ScriptedAdapter()
    with pytest.raises(ValueError):
        run_oss_helper("not a real url", adapter=adapter)


# ---- web route ----


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """A TestClient whose env forces provider=local-fake so /_debug/* and
    the oss-helper flow both work without live keys."""
    monkeypatch.setenv("AGENTOPS_PROVIDER", "local-fake")
    import tempfile

    from agentops_workbench.db.session import reset_for_tests
    db = Path(tempfile.gettempdir()) / "oss-helper-test.db"
    if db.exists():
        db.unlink()
    monkeypatch.setenv("AGENTOPS_DATABASE_URL", f"sqlite:///{db}")
    reset_for_tests()
    yield TestClient(app)
    reset_for_tests()


def test_web_get_renders_html_form(client) -> None:
    r = client.get("/oss-helper")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "<form" in body
    assert "oss-helper" in body.lower()
    # No JS framework dependency asserted -- the page must work without
    # any client-side JS executing.
    assert "<script src=" not in body


def test_web_post_runs_flow_and_renders_answer(client, monkeypatch) -> None:
    """The web form POST runs the flow and renders the structured answer.

    Patches the oss_helper entry point to return a deterministic
    TriageResult so the test doesn't depend on a live GitHub clone.
    """
    from agentops_workbench import oss_helper as oh

    fake = oh.TriageResult(
        owner="octocat",
        repo="hello-world",
        issue_number=42,
        question="how do I install?",
        answer="Per docs/install.md and issue #42, run `pip install hello-world`.",
        wiki_refs=[
            {"ref_id": "docs__install.md", "title": "installation guide",
             "score": 0.91, "source_kind": "wiki",
             "retrieved_at": "2026-09-14T00:00:00+00:00"},
        ],
        issue_refs=[
            {"ref_id": "42", "title": "install docs wrong",
             "score": 1.0, "source_kind": "github-issue",
             "retrieved_at": "2026-09-14T00:00:00+00:00"},
        ],
        warnings=[],
        duration_ms=123,
    )
    monkeypatch.setattr(oh, "run_oss_helper", lambda *a, **kw: fake)

    r = client.post(
        "/oss-helper",
        data={"repo_url": "https://github.com/octocat/hello-world",
              "question": "how do I install?",
              "issue_number": "42"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    body = r.text
    assert "octocat/hello-world" in body
    assert "42" in body  # issue number
    assert "1 doc refs, 1 issue/PR refs" in body
    assert "123ms" in body
    assert "pip install hello-world" in body  # answer text
    assert "installation guide" in body  # wiki ref title


def test_web_post_renders_form_error_on_bad_url(client, monkeypatch) -> None:
    """Bad URL surfaces a friendly message, not a 500."""
    r = client.post(
        "/oss-helper",
        data={"repo_url": "not a url", "question": "", "issue_number": ""},
        follow_redirects=False,
    )
    # 200 (re-renders the form) or 422; either is acceptable per ADR
    assert r.status_code in (200, 422)
    body = r.text
    assert "<form" in body
    assert "github URL" in body.lower() or "not a github url" in body.lower()
