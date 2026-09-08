#!/usr/bin/env bash
# scripts/branch-policy.sh — Callable branch-policy check (mirrors .githooks/pre-push).
#
# Behavior by environment:
#   - GitHub Actions (GITHUB_REF set): warn-only `::warning::` annotation on direct push to main
#   - Manual: print policy text and exit 0
#
# Active enforcement lives in `.githooks/pre-push` (client-side git hook).
# This script provides the warn-only server-side mirror so CI sees the same policy.

set -eo pipefail

if [ -n "${GITHUB_REF:-}" ] && [ -n "${GITHUB_EVENT_NAME:-}" ]; then
  if [ "$GITHUB_EVENT_NAME" = "push" ] && { [ "$GITHUB_REF" = "refs/heads/main" ] || [ "$GITHUB_REF" = "refs/heads/master" ]; }; then
    echo "::warning::Direct push to main detected. Policy: PR review required before merge."
    echo "  Commit:  ${GITHUB_SHA:-unknown}"
    echo "  Author:  ${GITHUB_ACTOR:-unknown}"
    echo "  Event:   push (not pull_request)"
    echo "  Workaround: revert + branch + gh pr create"
  fi
  exit 0
fi

echo "branch-policy.sh: active enforcement lives in .githooks/pre-push."
echo "  Client-side:    git config core.hooksPath .githooks"
echo "  Python lint:    .githooks/pre-commit runs Ruff in the dev-kit source repo."
echo "  Server-side:    this script (warn-only in CI)."
echo "  Bypass (emergency hotfix only): git push --no-verify"
exit 0
