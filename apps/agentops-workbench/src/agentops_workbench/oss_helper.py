"""agentops-oss-helper flow -- OSS maintainer helper, docs-only.

Given a public GitHub repo URL (and optionally a free-text question),
fetch the repo's own docs/README via `git sparse-checkout` (or
`codeload.github.com` tarball), build a TF-IDF corpus, and answer the
question grounded in those docs with explicit citations.

This is the concretization of phases/08-deployable-mvp/index.md and
ADR-0008 -- with the GitHub issues/PRs source removed per operator
direction 2026-09-14. The flow remains a useful demo of the
EvidenceSourceAdapter pattern: same Protocol shape as
GitHubIssueAdapter (now removed), different corpus, no network
permission dependency.

Acquisition forced by WikiRagAdapter's TF-IDF: its `__init__` builds
a corpus-wide IDF table before any query runs. Per-query Contents-API
fetches can't produce that, so docs must be bulk-fetched.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.wiki_rag import WikiRagAdapter
from .llm.adapter import LLMAdapter

log = logging.getLogger(__name__)


# Default doc roots we attempt to bulk-acquire from any GitHub repo.
# Override per-call if needed.
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
    question: str | None
    answer: str
    wiki_refs: list[dict]      # [{ref_id, title, score, source_kind, retrieved_at}]
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0


def parse_repo_url(url: str) -> tuple[str, str]:
    """Accept `https://github.com/<owner>/<repo>` with or without `.git`
    or a trailing slash.

    Returns (owner, repo). Raises ValueError on anything else (including
    GitLab / Bitbucket URLs -- this flow is GitHub-specific because it
    uses `codeload.github.com` and the git+sparse-checkout shape).
    """
    m = re.match(
        r"^https?://github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$",
        url.strip(),
    )
    if not m:
        raise ValueError(
            f"not a github URL of the form https://github.com/<owner>/<repo>: {url!r}"
        )
    return m.group(1), m.group(2)


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
        members = tf.getmembers()
        prefix_root = next(
            (m.name.split("/")[0] for m in members if m.isdir()), None
        )
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
    (dest_dir / flat_stem).write_text(
        path.read_text(encoding="utf-8", errors="replace")
    )


def run_oss_helper(
    repo_url: str,
    *,
    question: str | None = None,
    wiki_dir_cap: int = 4096,        # max flattened doc files; default = sane bound
    timeout_s: float = 30.0,
    adapter: LLMAdapter | None = None,   # injected for tests; real calls pass the default
) -> TriageResult:
    """Run the flagship flow end-to-end and return a structured TriageResult.

    Sequence:
      1. Parse repo URL, derive owner/repo
      2. Bulk-acquire docs into a temp dir, construct WikiRagAdapter
      3. Compose the answer prompt from the assembled evidence
      4. Call the LLM via `adapter.chat`
      5. Return TriageResult with answer + wiki evidence refs

    The LLM is asked to ground every claim in the assembled evidence;
    if no relevant evidence is found for any part of the question, it
    should refuse (per ADR-0008 / phase 8 exit criterion 2: visible
    failure modes for a triage tool).
    """
    started = time.monotonic()
    owner, repo = parse_repo_url(repo_url)
    warnings: list[str] = []

    work, acq_warnings = bulk_acquire_repo_docs(
        owner, repo, timeout_s=timeout_s,
    )
    warnings.extend(acq_warnings)

    # Construct the docs adapter.
    wiki = WikiRagAdapter(wiki_dir=str(work))
    query = question or ""

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
        for r in wiki.search_evidence(query, top_k=5)[:5]
    ) or "(no docs evidence)"

    prompt = (
        "You are the OSS Maintainer Helper Agent. Use the docs evidence "
        "below (from the target repo's own README/docs) to ground your "
        "answer. Cite sources inline as `[ref_id]`. If the evidence does "
        "not support a claim, say so explicitly rather than guessing.\n\n"
        f"Repo: {owner}/{repo}\n"
        + (f"Question: {question}\n" if question else "")
        + "\n## Docs evidence\n\n"
        + wiki_blob
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
        question=question,
        answer=answer,
        wiki_refs=[
            {
                "ref_id": r.ref_id,
                "title": r.title,
                "score": r.score,
                "source_kind": r.source_kind,
                "retrieved_at": r.retrieved_at,
            }
            for r in wiki.search_evidence(query, top_k=5)
        ],
        warnings=warnings,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
