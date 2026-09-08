#!/usr/bin/env bash
# scripts/test.sh — Run pytest against tests/. Exits 0 if no tests/.
set -euo pipefail

# Resolve REPO_ROOT (this script lives at <repo>/scripts/test.sh).
# Same fix as ci-local.sh: scope the fallback in a subshell so the
# inner `pwd` cannot leak into REPO_ROOT. See that file for the full
# explanation of the `A || B && C` operator-precedence trap.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "$0")/.." && pwd))"
cd "$REPO_ROOT"

if [ ! -d "tests" ]; then
  echo "test.sh: no tests/ directory in $REPO_ROOT — skip"
  exit 0
fi

# Add lib/ to PYTHONPATH if it exists (mirrors dev-kit convention).
if [ -d "lib" ]; then
  export PYTHONPATH="${REPO_ROOT}/lib${PYTHONPATH:+:$PYTHONPATH}"
fi

# Make sure pytest is available — install if missing (pinned for reproducibility).
if ! python3 -c "import pytest" 2>/dev/null; then
  echo "test.sh: installing pytest (pinned)..."
  python3 -m pip install --quiet "pytest>=8.0,<9.0"
fi

python3 -m pytest tests/ -v --tb=short
