#!/usr/bin/env python3
"""Small, restartable feature loop with an auditable atomic checkpoint."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.atomic import atomic_write_json, now_iso  # noqa: E402


def _features(root: Path, name: str) -> list[dict[str, Any]]:
    data = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("feature list must be a JSON array of objects")
    return data


def _next(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_id = {item.get("id"): item for item in features}
    candidates = []
    for item in features:
        if item.get("status") != "failing":
            continue
        if all(by_id.get(dep, {}).get("status") == "passing" for dep in item.get("depends_on", [])):
            candidates.append(item)
    return sorted(candidates, key=lambda item: str(item.get("id")))[0] if candidates else None


def _checkpoint_path(root: Path) -> Path:
    return root / ".dev-kit" / "loop-checkpoint.json"


def _verify(root: Path, features: list[dict[str, Any]]) -> list[str]:
    path = _checkpoint_path(root)
    if not path.is_file():
        return []
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid checkpoint: {exc}"]
    errors: list[str] = []
    ids = {item.get("id") for item in features}
    if checkpoint.get("schema_version") != "1":
        errors.append("unsupported checkpoint schema")
    if not isinstance(checkpoint.get("iteration"), int) or checkpoint["iteration"] < 1:
        errors.append("checkpoint iteration must be a positive integer")
    last = checkpoint.get("last")
    if not isinstance(last, dict) or last.get("feature_id") not in ids:
        errors.append("checkpoint references unknown feature")
    if isinstance(last, dict) and not isinstance(last.get("exit_code"), int):
        errors.append("checkpoint exit_code must be an integer")
    return errors


def iterate(root: Path, feature_list: str, test_cmd: str | None, timeout: int) -> int:
    features = _features(root, feature_list)
    errors = _verify(root, features)
    if errors:
        print("; ".join(errors), file=sys.stderr)
        return 1
    feature = _next(features)
    if feature is None:
        print("no eligible failing feature", file=sys.stderr)
        return 2
    path = root / str(feature["test_path"])
    if test_cmd:
        command = test_cmd.split() + [str(path)]
    elif path.suffix == ".py":
        command = [sys.executable, str(path)]
    else:
        command = ["sh", str(path)]
    try:
        proc = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout)
        exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\ntest timed out after {timeout}s"
    checkpoint = _checkpoint_path(root)
    previous = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {"iteration": 0}
    payload = {
        "schema_version": "1",
        "iteration": previous["iteration"] + 1,
        "recorded_at": now_iso(),
        "last": {
            "feature_id": feature["id"], "test_path": feature["test_path"],
            "command": command, "exit_code": exit_code,
            "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:],
        },
    }
    atomic_write_json(checkpoint, payload)
    print(json.dumps(payload["last"], ensure_ascii=False))
    return 0 if exit_code == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("iterate", "verify"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--feature-list", default="feature_list.json")
    parser.add_argument("--test-cmd", default=os.environ.get("TEST_CMD"))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    root = args.project_root.resolve()
    try:
        features = _features(root, args.feature_list)
        errors = _verify(root, features)
        if args.action == "verify":
            if errors:
                print("; ".join(errors), file=sys.stderr)
                return 1
            print("loop checkpoint valid")
            return 0
        return iterate(root, args.feature_list, args.test_cmd, args.timeout)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"loop error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
