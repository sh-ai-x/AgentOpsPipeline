"""agentops-oss-helper flow -- flagship demo of the OSS-maintainer pivot.

Given a public GitHub repo URL (and optionally an issue number or a free-
text question), produce a grounded triage / answer draft that cites the
repo's own docs/README AND its own Issues/PRs as evidence. This is the
concretization of phases/08-deployable-mvp/index.md and ADR-0008.

Acquisition is split, forced by two algorithm/contract facts:

1. **Docs acquired in bulk** via `git clone --depth 1 --filter=blob:none
   --sparse` (when `git` is available on the host) or a `codeload.github.com`
   tarball (when it isn't, e.g. a container image without `git`). Bulk is
   forced by WikiRagAdapter's TF-IDF: its `__init__` builds a corpus-wide
   IDF table before any query runs, and per-query Contents-API fetches
   can't produce that.
2. **Issues/PRs acquired via the GitHub REST API** via the existing
   GitHubIssueAdapter (real `httpx` calls, `pytest-httpx`-mocked in
   tests). Issues aren't in the git tree.

The result is a structured triage result (not a streaming LLM
response): answer text, top evidence refs from each source with
citations, raw per-source counts, and any acquisition warnings.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.github_issue import GitHubIssueAdapter
from .adapters.wiki_rag import WikiRagAdapter
from .llm.adapter import LLMAdapter

log = logging.getLogger(__name__)


# Default doc roots we attempt to bulk-acquire from any GitHub repo.
# Override per-call if needed. `hooks/` covers OSS tooling repos
# (worktree-guard, CI templates, etc.) where the actual project docs
# live in the hooks/ subdirectory rather than the top-level README.
DEFAULT_DOC_ROOTS: tuple[str, ...] = (
    "README.md",
    "README.rst",
    "README",
    "docs",
    "doc",
    "documentation",
    "hooks",
    "CONTRIBUTING.md",
)


@dataclass(frozen=True)
class TriageResult:
    owner: str
    repo: str
    issue_number: int | None
    question: str | None
    answer: str
    wiki_refs: list[dict]      # [{ref_id, title, score, source_kind, retrieved_at}]
    issue_refs: list[dict]    # same shape
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0


def parse_repo_url(url: str) -> tuple[str, str, int | None]:
    """Accept `https://github.com/<owner>/<repo>` with or without `.git`,
    a trailing slash, or a trailing `/issues/<N>` (in which case <N> is
    taken as the issue number, returned in the third tuple slot).

    Returns (owner, repo, issue_number_or_None). Raises ValueError on
    anything else.
    """
    m = re.match(
        r"^https?://github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?(?:/issues/(\d+))?/?$",
        url.strip(),
    )
    if not m:
        raise ValueError(
            f"not a github URL of the form https://github.com/<owner>/<repo>: {url!r}"
        )
    owner, repo = m.group(1), m.group(2)
    issue = int(m.group(3)) if m.group(3) else None
    return owner, repo, issue


def bulk_acquire_repo_docs(
    owner: str,
    repo: str,
    *,
    ref: str = "HEAD",
    doc_roots: tuple[str, ...] = DEFAULT_DOC_ROOTS,
    prefer: str = "auto",     # "git" | "codeload" | "auto"
    timeout_s: float = 30.0,
) -> tuple[Path, list[str]]:
    """Acquire a repo's docs into a temporary directory.

    Returns (work_dir, warnings). work_dir contains flattened *.md/*.mdx
    files (path separators encoded into the stem: docs__guide__install.md)
    suitable for direct construction of a WikiRagAdapter.

    Strategy:
      - if `prefer=git` or (prefer=auto and `git` binary is on PATH):
        git clone --depth 1 --filter=blob:none --sparse, then
        git sparse-checkout set <roots>
      - else (no `git` binary, e.g. container image):
        GET https://codeload.github.com/<owner>/<repo>/tar.gz/<ref>, extract
        into the temp dir, then walk the extracted tree to find the doc
        roots.

    Warnings (not errors): anything non-fatal -- "git timed out", "tarball
    didn't contain any of the requested roots", etc. The caller decides
    whether to surface them.
    """
    warnings: list[str] = []
    if prefer == "auto":
        prefer = "git" if shutil.which("git") else "codeload"

    work = Path(tempfile.mkdtemp(prefix=f"oss-helper-{owner}-{repo}-"))

    if prefer == "git":
        rc = _acquire_via_git(owner, repo, ref, doc_roots, work, timeout_s)
        if rc != 0:
            warnings.append(
                f"git acquisition failed (rc={rc}); falling back to codeload tarball"
            )
            return bulk_acquire_repo_docs(
                owner, repo, ref=ref, doc_roots=doc_roots,
                prefer="codeload", timeout_s=timeout_s,
            )
    else:
        try:
            _acquire_via_codeload(owner, repo, ref, doc_roots, work, timeout_s)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"codeload acquisition failed: {exc!r}")
            return work, warnings  # empty work dir, caller handles

    return work, warnings


def _acquire_via_git(
    owner: str,
    repo: str,
    ref: str,
    doc_roots: tuple[str, ...],
    work: Path,
    timeout_s: float,
) -> int:
    # shallow + filter=blob:none keeps the clone cheap; sparse-checkout
    # pulls only the requested doc roots (no other blobs are fetched).
    cmds: list[list[str]] = [
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", f"https://github.com/{owner}/{repo}.git"],
        ["git", "config", "user.email", "oss-helper@localhost"],
        ["git", "config", "user.name", "oss-helper"],
        ["git", "fetch", "--depth=1", "--filter=blob:none", "origin", ref],
        ["git", "sparse-checkout", "init", "--cone"],
        ["git", "sparse-checkout", "set", *doc_roots],
        ["checkout", ref],  # fall through; use the local git checkout cmd
    ]
    # The last step needs `git checkout <ref>` not just `checkout <ref>`
    cmds[-1] = ["git", "checkout", "FETCH_HEAD"]
    for cmd in cmds:
        try:
            r = subprocess.run(
                cmd, cwd=str(work), capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            log.warning("git command timed out: %s", cmd)
            return 124
        if r.returncode != 0:
            log.warning("git %s failed: %s", cmd, r.stderr.strip())
            return r.returncode
    # Flatten into a single docs/ subdir (WikiRagAdapter globs *.md non-
    # recursively, per ADR-0008's forced-fix rationale).
    flat = work / "_flat"
    flat.mkdir(exist_ok=True)
    for root in doc_roots:
        src = work / root
        if not src.exists():
            continue
        if src.is_file():
            _flatten_one(src, flat, work)
            continue
        for path in src.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".md", ".mdx"}:
                _flatten_one(path, flat, work)
    return 0


def _acquire_via_codeload(
    owner: str,
    repo: str,
    ref: str,
    doc_roots: tuple[str, ...],
    work: Path,
    timeout_s: float,
) -> None:
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    log.info("codeload fetch: %s", url)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        tmp_tar = work / "repo.tgz"
        tmp_tar.write_bytes(resp.read())
    with tarfile.open(tmp_tar, "r:gz") as tf:
        prefix_root = next((m.name.split("/")[0] for m in tf.getmembers() if m.isdir()), None)
        tf.extractall(work)
    extracted = work / (prefix_root or "")
    flat = work / "_flat"
    flat.mkdir(exist_ok=True)
    if not extracted.exists():
        return
    for root in doc_roots:
        src = extracted / root
        if not src.exists():
            continue
        if src.is_file():
            _flatten_one(src, flat, extracted)
            continue
        for path in src.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".md", ".mdx"}:
                _flatten_one(path, flat, extracted)


def _flatten_one(path: Path, dest_dir: Path, source_root: Path) -> None:
    """Copy `path` into `dest_dir` with a flattened stem.

    Path separators below `source_root` are encoded with `__`. Example:
    <source>/docs/guide/install.md -> <dest>/docs__guide__install.md
    """
    try:
        rel = path.relative_to(source_root)
    except ValueError:
        rel = Path(path.name)
    flat_stem = str(rel).replace("/", "__").replace("\\", "__")
    (dest_dir / flat_stem).write_text(path.read_text(encoding="utf-8", errors="replace"))


def run_oss_helper(
    repo_url: str,
    *,
    question: str | None = None,
    issue_number: int | None = None,
    github_token: str | None = None,
    wiki_dir_cap: int = 4096,        # max flattened doc files; default = sane bound
    timeout_s: float = 30.0,
    adapter: LLMAdapter | None = None,   # injected for tests; real calls pass the default
) -> TriageResult:
    """Run the flagship flow end-to-end and return a structured TriageResult.

    Sequence:
      1. Parse repo URL, derive owner/repo/[issue]
      2. Bulk-acquire docs into a temp dir, construct WikiRagAdapter
      3. Construct GitHubIssueAdapter (read-only, no mutations)
      4. Optionally fetch the named issue
      5. Compose an answer prompt from the assembled evidence
      6. Call the LLM via `adapter.chat`
      7. Return TriageResult with answer + per-source evidence refs

    The LLM is asked to ground every claim in the assembled evidence;
    if no relevant evidence is found for any part of the question, it
    should refuse (per ADR-0008's "explicit refusal when evidence does
    not support one").
    """
    started = time.monotonic()
    owner, repo, parsed_issue = parse_repo_url(repo_url)
    issue = issue_number if issue_number is not None else parsed_issue
    warnings: list[str] = []

    work, acq_warnings = bulk_acquire_repo_docs(
        owner, repo, timeout_s=timeout_s,
    )
    warnings.extend(acq_warnings)

    # Construct the two adapters.
    wiki = WikiRagAdapter(wiki_dir=str(work))
    # Caller-passed token beats env fallback. Env fallback beats no token.
    # Without it, GitHub returns 422 for private repos (not even a 403 --
    # the search endpoint refuses to confirm the repo exists) and the user
    # sees a "no match" page that was actually a permission error.
    # For public-but-large repos (facebook/react, microsoft/typescript,
    # etc.) unauthenticated requests also hit this exact "Validation
    # Failed" error -- the search endpoint has a stricter rate limit and
    # rejects anonymous queries against high-spam-risk repos. Surfacing
    # the missing-token state as a warning lets the user fix the actual
    # cause rather than chase a non-existent issue list.
    effective_token = (
        github_token
        if github_token is not None
        else os.environ.get("AGENTOPS_GITHUB_TOKEN")
    )
    if effective_token is None:
        warnings.append(
            "AGENTOPS_GITHUB_TOKEN is not set -- unauthenticated GitHub API "
            "search may fail with 'Validation Failed' for popular or "
            "private repos. Set the env var (or pass github_token=...) "
            "to enable issue/PR search."
        )
    issue_adapter = GitHubIssueAdapter(
        owner=owner, repo=repo, token=effective_token,
    )

    # Search both sources. Per-source top-k; never merge-ranked across
    # adapters (different scoring distributions).
    #
    # Query construction -- multiple real bugs were hiding in here:
    #   - GitHub's issues search API enforces a 256-character limit on the
    #     `q` parameter. Concatenating question + full issue body blows
    #     past it with a 422, which then surfaced as a silent 0-results
    #     page (the exception propagated, but the LLM answered "I found
    #     no match" anyway because the body still ran through it).
    #   - Empty `q` is also rejected by GitHub (422 or just no hits),
    #     which is why a blank form returns 0 issue/PR refs with no
    #     visible error.
    # Fix: query stays SHORT (issue # + optional short question, truncated
    # to 200 chars). When no question is given, search the repo's open
    # issues broadly via the qualifier `repo:owner/name is:issue is:open`
    # so we always have something to anchor the LLM's answer.
    #
    # Subtle: GitHubIssueAdapter.search_evidence prepends its own
    # `repo:owner/name ` prefix internally. We must NOT include it
    # here or the actual HTTP request gets sent with `repo:X repo:X ...`
    # which GitHub silently treats as a malformed query and returns 0
    # results -- not an error, just no hits. Pass only the qualifiers
    # plus a short keyword fragment of the question.
    #
    # Second subtle: GitHub's lexical search treats natural-language
    # sentences as AND-of-all-tokens -- adding more tokens monotonically
    # narrows the result set. A 10-word question often narrows to 0
    # results even though a 2-word substring gives 5. So we pass only
    # the 3 most discriminating keywords (after stopword filtering) to
    # the gh side, while the full question goes to the wiki side where
    # TF-IDF scoring handles long text correctly.
    base = "is:issue is:open"
    if issue is not None:
        base = f"is:issue {issue}"
    _STOPWORDS = frozenset(
        "the a an is in on at to for of and or how do does i me my you we they it "
        "this that these those is are was were be been being have has had do does did "
        "a an the".split()
    )
    # Split on whitespace, then strip non-alnum (keeping hyphens, which
    # are common in code identifiers like 'worktree-guard'). Re-join so
    # 'worktree-guard' stays one keyword token, but punctuation noise
    # like 'edits?' becomes 'edits'.
    keywords: list[str] = []
    for raw in (question or "").lower().split():
        if not raw:
            continue
        # Keep the token but strip trailing/leading punctuation
        cleaned = raw.strip(".,;:?!'\"`()[]{}*")
        if not cleaned or cleaned in _STOPWORDS:
            continue
        if len(cleaned) <= 2:
            continue
        keywords.append(cleaned)
    keywords_str = " ".join(keywords[:3])
    gh_query = (base + (" " + keywords_str if keywords_str else "")).strip()
    # GitHub enforces 256 chars on /search/issues; truncate defensively.
    if len(gh_query) > 256:
        gh_query = gh_query[:256]

    wiki_query = question or ""
    if not wiki_query and issue is not None:
        # The wiki side also benefits from a hint when there's no free-text
        # question -- just the issue number, no body.
        wiki_query = f"issue {issue}"
    if not wiki_query:
        # No question, no issue number -- the user just dropped a URL.
        # Search the corpus with the repo name itself as a generic
        # anchor so we still surface SOMETHING (README/CHANGELOG/AGENTS
        # etc. usually mention the project name). TF-IDF scoring will
        # naturally bring top-level project docs to the top.
        wiki_query = f"{repo}"

    wiki_evs = wiki.search_evidence(wiki_query, top_k=5) if wiki_query else []
    try:
        issue_evs = issue_adapter.search_evidence(gh_query, top_k=5)
    except Exception as exc:  # noqa: BLE001 -- surfaced as warning
        warnings.append(f"github issues search failed: {exc!r}")
        issue_evs = []

    # Cap the flattened docs folder -- WikiRagAdapter's TF-IDF is a linear
    # scan over every document per query, inappropriate at scale. A
    # monorepo with thousands of md files must fail loudly with a named
    # cap, not wedge. Default is intentionally small for the demo; the
    # CLI will expose --max-docs (a follow-up).
    try:
        md_count = sum(1 for _ in (work / "_flat").glob("*.md"))
        if md_count > wiki_dir_cap:
            warnings.append(
                f"repo has {md_count} markdown files, exceeds --max-docs={wiki_dir_cap}; "
                f"scoring may be slow or inaccurate"
            )
    except Exception:  # noqa: BLE001
        pass

    # Compose the answer prompt and call the LLM.
    wiki_blob = "\n\n--\n\n".join(
        f"[{r.ref_id}] {r.title}\n{r.source_kind} score={r.score:.2f}\n" +
        # show the first ~600 chars of the body when we can fetch it
        f"{wiki.read_evidence(r.ref_id, limit=1200)}"
        for r in wiki_evs[:5]
    ) or "(no wiki/docs evidence)"
    issue_blob = "\n\n--\n\n".join(
        f"[{r.ref_id}] {r.title}\n{r.source_kind} score={r.score:.2f}\n" +
        f"{issue_adapter.read_evidence(r.ref_id, limit=1200)}"
        for r in issue_evs[:5]
    ) or "(no issue/PR evidence)"

    prompt = (
        "You are the OSS Maintainer Helper Agent. Use the evidence below "
        "(from the target repo's own docs/README and Issues/PRs) to ground "
        "your answer. Cite sources inline as `[ref_id]`. If the evidence "
        "does not support a claim, say so explicitly rather than guessing.\n\n"
        f"Repo: {owner}/{repo}\n"
        + (f"Question: {question}\n" if question else "")
        + (f"Issue #{issue} context is included in the search query.\n" if issue is not None else "")
        + "\n## Docs evidence\n\n"
        + wiki_blob
        + "\n\n## Issue/PR evidence\n\n"
        + issue_blob
        + "\n\n## Answer\n"
    )

    if adapter is None:
        from .llm.factory import make_adapter
        from .settings import get_settings
        adapter = make_adapter(get_settings())

    chat_result = adapter.chat([{"role": "user", "content": prompt}])
    answer = (chat_result.content or "").strip()

    return TriageResult(
        owner=owner,
        repo=repo,
        issue_number=issue,
        question=question,
        answer=answer,
        wiki_refs=[r.__dict__ for r in wiki_evs],
        issue_refs=[r.__dict__ for r in issue_evs],
        warnings=warnings,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
