#!/usr/bin/env python3
"""test_worktree_guard_bypass.py — regression for the bypass that the
original file_path-based classification opened.

Background: issue #842 was that sub-agents inside a linked worktree
inherit the parent orchestrator main-checkout cwd, so they got denied
even when editing inside their own worktree. PR fix/worktree-guard-file-path
fixed that by classifying by the TARGET file_path rather than the session
cwd.

But that fix opened a separate bypass: a TRUE main-checkout session can
now point file_path at ANY linked worktree's file and pass the guard,
because the hook only checks the file's repo, not whether the session
is actually working from that worktree.

The corrected semantic: the target worktree must match the SESSION'S own
worktree, not just exist in the repo. These tests pin that.

These tests are in a separate file so the original test_worktree_guard.py
remains untouched (the original test_allows_target_worktree_when_hook_cwd_is_main_checkout
test encodes the bypass as expected behavior and will be removed/replaced
when the hook fix lands).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOKS = REPO_ROOT / "hooks"


def _run_hook(script: str, payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(cwd) if cwd else None,
    )


def _edit_payload(file_path: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": file_path}}


def _init_main_with_worktree() -> tuple:
    """Build a throwaway repo with a linked worktree. Returns
    (main_tmpdir, wt_parent_tmpdir, wt_path)."""
    main_tmp = tempfile.TemporaryDirectory()
    main_root = Path(main_tmp.name)
    subprocess.run(["git", "init", "-q", "-b", "main", str(main_root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(main_root), "config", "user.name", "Test"], check=True)
    (main_root / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(main_root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main_root), "commit", "-q", "-m", "init"], check=True, capture_output=True)

    wt_parent = tempfile.TemporaryDirectory()
    wt_path = Path(wt_parent.name) / "wt"
    subprocess.run(
        ["git", "-C", str(main_root), "worktree", "add", "-b", "fix/test", str(wt_path)],
        check=True, capture_output=True,
    )
    return main_tmp, wt_parent, wt_path


class TestBypassRejection(unittest.TestCase):
    """The file_path-based classifier must NOT open a bypass for
    main-checkout sessions pointing at other worktrees' files."""

    def setUp(self):
        if not (HOOKS / "worktree-guard.sh").exists():
            self.skipTest("worktree-guard.sh not found")

    def test_blocks_main_session_editing_into_worktree(self):
        """The bypass case: session cwd == main checkout, target path
        is inside a different linked worktree. Must deny -- a main
        session has no business editing into another worktree."""
        main_tmp, wt_parent, wt_path = _init_main_with_worktree()
        try:
            r = _run_hook(
                "worktree-guard.sh",
                _edit_payload(str(wt_path / "new.py")),
                cwd=Path(main_tmp.name),
            )
            self.assertEqual(r.returncode, 2,
                f"expected deny, got rc={r.returncode}, stderr={r.stderr}")
            self.assertIn("main checkout", r.stdout + r.stderr)
        finally:
            wt_parent.cleanup()
            main_tmp.cleanup()

    def test_allows_subagent_in_worktree(self):
        """The corrected happy path: session cwd IS the worktree, target
        path is inside the SAME worktree. Must allow."""
        main_tmp, wt_parent, wt_path = _init_main_with_worktree()
        try:
            r = _run_hook(
                "worktree-guard.sh",
                _edit_payload(str(wt_path / "new.py")),
                cwd=wt_path,
            )
            self.assertEqual(r.returncode, 0,
                f"expected allow, got rc={r.returncode}, stderr={r.stderr}")
        finally:
            wt_parent.cleanup()
            main_tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
