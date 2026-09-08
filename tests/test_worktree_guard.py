#!/usr/bin/env python3
"""test_worktree_guard.py — regression tests for the 2 worktree-rule hooks.

Verifies the bash-level behavior of:
  - hooks/worktree-guard.sh       (PreToolUse Edit|Write|MultiEdit — hard block)

  - hooks/session-start-check.sh  (SessionStart — advisory additionalContext)

The hard rule under test (.claude/rules/git-workflow.md):
  "Every task = new worktree + subagent handoff + new branch."

We test the scripts as black boxes by feeding them JSON via stdin and
asserting on exit code + stdout/stderr. No mocks. We synthesize real
git repos (main + linked worktree) via `git worktree add` to exercise
the --git-dir / --git-common-dir discriminator.
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


def _prompt_payload(prompt: str, cwd: str = "") -> dict:
    p = {"tool_name": "UserPromptSubmit", "prompt": prompt}
    if cwd:
        p["cwd"] = cwd
    return p


def _session_payload(cwd: str = "") -> dict:
    p = {"hook_event_name": "SessionStart", "session_id": "test"}
    if cwd:
        p["cwd"] = cwd
    return p


def _init_main_with_worktree() -> tuple:
    """Build a throwaway repo with a linked worktree. Returns (main_tmp, wt_tmp).

    main_tmp: tempdir that IS the main checkout (git_dir == git_common_dir).
    wt_tmp:   tempdir that IS a worktree (git_dir != git_common_dir).
    """
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


class TestWorktreeGuardBlocks(unittest.TestCase):
    """worktree-guard.sh must DENY (exit 2) Edit/Write/MultiEdit in the main checkout."""

    def setUp(self):
        if not (HOOKS / "worktree-guard.sh").exists():
            self.skipTest("worktree-guard.sh not found")

    def test_blocks_edit_in_main_checkout(self):
        main_tmp, _, _ = _init_main_with_worktree()
        try:
            r = _run_hook("worktree-guard.sh", _edit_payload("/some/file.py"), cwd=Path(main_tmp.name))
            self.assertEqual(r.returncode, 2, f"expected deny, got rc={r.returncode}, stderr={r.stderr}")
            combined = r.stdout + r.stderr
            self.assertIn("WORKTREE GUARD", combined)
            self.assertIn("permissionDecision", combined)
            self.assertIn('"deny"', combined)
            self.assertIn("main checkout", combined)
        finally:
            main_tmp.cleanup()

    def test_deny_output_is_valid_pretooluse_json(self):
        """Minor 4: deny output must match the PreToolUse JSON schema
        that Claude Code parses (hookSpecificOutput.permissionDecision)."""
        main_tmp, _, _ = _init_main_with_worktree()
        try:
            r = _run_hook("worktree-guard.sh", _edit_payload("/some/file.py"), cwd=Path(main_tmp.name))
            self.assertEqual(r.returncode, 2)
            # The deny JSON is printed to stderr; find it.
            deny_lines = [ln for ln in (r.stdout + r.stderr).splitlines()
                          if ln.strip().startswith("{")]
            self.assertTrue(deny_lines, f"no JSON line in output: stdout={r.stdout!r} stderr={r.stderr!r}")
            for line in deny_lines:
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError as e:
                    self.fail(f"deny output is not valid JSON: {line!r} ({e})")
                self.assertIn("hookSpecificOutput", doc)
                hso = doc["hookSpecificOutput"]
                self.assertEqual(hso.get("hookEventName"), "PreToolUse")
                self.assertEqual(hso.get("permissionDecision"), "deny")
                self.assertIn("permissionDecisionReason", hso)
                self.assertTrue(len(hso["permissionDecisionReason"]) > 0)
        finally:
            main_tmp.cleanup()

    def test_blocks_write_in_subdir_of_main_checkout(self):
        """Subdirectory of the main checkout is still main checkout."""
        main_tmp, _, _ = _init_main_with_worktree()
        try:
            sub = Path(main_tmp.name) / "src" / "deep"
            sub.mkdir(parents=True, exist_ok=True)
            r = _run_hook("worktree-guard.sh", _edit_payload(str(sub / "foo.py")), cwd=sub)
            self.assertEqual(r.returncode, 2, f"expected deny, got rc={r.returncode}, stderr={r.stderr}")
            self.assertIn("WORKTREE GUARD", r.stdout + r.stderr)
        finally:
            main_tmp.cleanup()


class TestWorktreeGuardAllows(unittest.TestCase):
    """worktree-guard.sh must ALLOW (exit 0) edits inside a worktree."""

    def setUp(self):
        if not (HOOKS / "worktree-guard.sh").exists():
            self.skipTest("worktree-guard.sh not found")

    def test_allows_edit_in_worktree(self):
        _, wt_parent, wt_path = _init_main_with_worktree()
        try:
            r = _run_hook("worktree-guard.sh", _edit_payload(str(wt_path / "foo.py")), cwd=wt_path)
            self.assertEqual(r.returncode, 0, f"expected allow, got rc={r.returncode}, stderr={r.stderr}")
        finally:
            wt_parent.cleanup()

    def test_allows_edit_in_worktree_subdir(self):
        _, wt_parent, wt_path = _init_main_with_worktree()
        try:
            sub = wt_path / "src" / "deep"
            sub.mkdir(parents=True, exist_ok=True)
            r = _run_hook("worktree-guard.sh", _edit_payload(str(sub / "foo.py")), cwd=sub)
            self.assertEqual(r.returncode, 0, f"expected allow, got rc={r.returncode}, stderr={r.stderr}")
        finally:
            wt_parent.cleanup()

    def test_allows_edit_outside_any_git_repo(self):
        """Non-git directory → hook does not apply → exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            r = _run_hook("worktree-guard.sh", _edit_payload(str(Path(tmp) / "foo.py")), cwd=Path(tmp))
            self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")

    def test_no_op_on_missing_payload(self):
        """Empty stdin → hook should not crash, exit 0."""
        r = subprocess.run(
            ["bash", str(HOOKS / "worktree-guard.sh")],
            input="", capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")


class TestWorktreeGuardJqMissing(unittest.TestCase):
    """worktree-guard.sh must FAIL CLOSED when jq is missing."""

    def setUp(self):
        if not (HOOKS / "worktree-guard.sh").exists():
            self.skipTest("worktree-guard.sh not found")
        import shutil as _sh
        self._bash = _sh.which("bash")
        self._jq = _sh.which("jq")
        if not self._bash:
            self.skipTest("bash not on PATH")
        if not self._jq:
            self.skipTest("jq not on host — cannot simulate missing-jq")

    def test_denies_when_jq_missing(self):
        util_dirs = set()
        for util in ("bash", "cat", "echo", "printf", "command"):
            p = shutil.which(util)
            if p:
                util_dirs.add(os.path.dirname(p))
        util_dirs.discard(os.path.dirname(self._jq))
        minimal_path = os.pathsep.join(sorted(util_dirs)) or "/nonexistent"
        payload = json.dumps(_edit_payload("/tmp/foo.py"))
        r = subprocess.run(
            [self._bash, str(HOOKS / "worktree-guard.sh")],
            input=payload, capture_output=True, text=True, timeout=5,
            env={**os.environ, "PATH": minimal_path},
        )
        self.assertEqual(r.returncode, 2, f"expected deny, got rc={r.returncode}, stderr={r.stderr}")
        self.assertIn("jq is required", r.stderr)
        self.assertIn("permissionDecision", r.stderr)



class TestSessionStartCheck(unittest.TestCase):
    """session-start-check.sh: SessionStart — nudge only in main checkout."""

    def setUp(self):
        if not (HOOKS / "session-start-check.sh").exists():
            self.skipTest("session-start-check.sh not found")

    def test_nudges_when_started_in_main_checkout(self):
        main_tmp, _, _ = _init_main_with_worktree()
        try:
            r = _run_hook("session-start-check.sh", _session_payload(cwd=main_tmp.name), cwd=Path(main_tmp.name))
            self.assertEqual(r.returncode, 0, f"got rc={r.returncode}, stderr={r.stderr}")
            self.assertIn("additionalContext", r.stdout)
            self.assertIn("GIT-WORKFLOW REMINDER", r.stdout)
        finally:
            main_tmp.cleanup()

    def test_silent_when_started_in_worktree(self):
        _, wt_parent, wt_path = _init_main_with_worktree()
        try:
            r = _run_hook("session-start-check.sh", _session_payload(cwd=str(wt_path)), cwd=wt_path)
            self.assertEqual(r.returncode, 0)
            self.assertNotIn("GIT-WORKFLOW REMINDER", r.stdout)
        finally:
            wt_parent.cleanup()

    def test_silent_outside_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = _run_hook("session-start-check.sh", _session_payload(cwd=tmp), cwd=Path(tmp))
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "")

    def test_silent_when_no_cwd_field(self):
        """If the SessionStart payload has no cwd, the hook should not crash."""
        r = _run_hook("session-start-check.sh", _session_payload())
        self.assertEqual(r.returncode, 0)


class TestHooksJsonWiring(unittest.TestCase):
    """hooks.json must register all three new hooks so Claude Code invokes them."""

    def setUp(self):
        path = HOOKS / "hooks.json"
        if not path.exists():
            self.skipTest(f"hooks.json not found at {path}")
        self._cfg = json.loads(path.read_text(encoding="utf-8"))

    def _hooks_under(self, event: str) -> list:
        """Flatten the matcher-list-of-hook-list shape into a flat hook list."""
        flat = []
        for entry in self._cfg["hooks"].get(event, []):
            for h in entry.get("hooks", []):
                flat.append(h.get("command", ""))
        return flat

    def test_worktree_guard_in_pretooluse_edit_matcher(self):
        cmds = self._hooks_under("PreToolUse")
        self.assertTrue(
            any("worktree-guard.sh" in c for c in cmds),
            f"worktree-guard.sh not wired into PreToolUse. Got commands: {cmds}",
        )

    def test_session_start_check_in_sessionstart(self):
        cmds = self._hooks_under("SessionStart")
        self.assertTrue(
            any("session-start-check.sh" in c for c in cmds),
            f"session-start-check.sh not wired into SessionStart. Got: {cmds}",
        )


class TestWorktreeDetectLib(unittest.TestCase):
    """hooks/lib/worktree-detect.sh — shared discriminator (Major 3)."""

    LIB = HOOKS / "lib" / "worktree-detect.sh"

    def setUp(self):
        if not self.LIB.exists():
            self.skipTest(f"worktree-detect.sh not found at {self.LIB}")

    def _source_in(self, cwd: Path) -> dict:
        """Source the lib in a subshell with the given cwd, return the
        env vars it set (WORKTREE_DETECT)."""
        cmd = (
            f'source "{self.LIB}" && '
            f'worktree_detect && '
            f'echo "WORKTREE_DETECT=$WORKTREE_DETECT"'
        )
        r = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=5, cwd=str(cwd),
        )
        self.assertEqual(r.returncode, 0, f"sourcing failed: stderr={r.stderr}")
        out = {}
        for ln in r.stdout.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                out[k] = v
        return out

    def test_returns_worktree_in_a_worktree(self):
        _, wt_parent, wt_path = _init_main_with_worktree()
        try:
            env = self._source_in(wt_path)
            self.assertEqual(env.get("WORKTREE_DETECT"), "worktree")
        finally:
            wt_parent.cleanup()

    def test_returns_main_in_main_checkout(self):
        main_tmp, _, _ = _init_main_with_worktree()
        try:
            env = self._source_in(Path(main_tmp.name))
            self.assertEqual(env.get("WORKTREE_DETECT"), "main")
        finally:
            main_tmp.cleanup()

    def test_returns_outside_when_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._source_in(Path(tmp))
            self.assertEqual(env.get("WORKTREE_DETECT"), "outside")

    def test_jq_missing_warn_helper_emits_to_stderr(self):
        """The advisory helper must print to stderr (loud) and return 0."""
        if not shutil.which("jq"):
            self.skipTest("jq not on host")
        # We cannot easily strip jq from PATH just for this test, so
        # verify the helper's contract: a hook-name argument, prints
        # to stderr, returns 0. We simulate "jq missing" by directly
        # calling the helper when we know jq IS available — the helper
        # does not check jq itself, the caller does. So calling it
        # always works; we just assert the print contract.
        r = subprocess.run(
            ["bash", "-c", f'source "{self.LIB}" && worktree_detect_jq_missing_warn "fake-hook.sh"'],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(r.returncode, 0, f"helper returned non-zero: stderr={r.stderr}")
        self.assertIn("fake-hook.sh", r.stderr, f"expected hook name in stderr: {r.stderr!r}")
        self.assertIn("jq", r.stderr, f"expected jq mention in stderr: {r.stderr!r}")
        self.assertEqual(r.stdout, "", f"helper should print to stderr only: stdout={r.stdout!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
