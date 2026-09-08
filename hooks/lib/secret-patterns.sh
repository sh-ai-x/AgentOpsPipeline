#!/usr/bin/env bash
# secret-patterns.sh — bash ERE SSOT for credential regexes used by
# hooks/secret-scan.sh (and any future hook that scans free text for
# secret-shaped strings).
#
# SSOT DOCUMENTATION:
#   The Python `re` SSOT lives in
#   lib/analysis_core/runner.py::_SECRET_PATTERNS. This file is the
#   bash ERE mirror of that same set, consumed by `grep -E` inside
#   secret-scan.sh's main loop. When a credential family is added or
#   tightened, BOTH files MUST be updated together — adding to only
#   one creates a coverage gap that the secret-dimension audit will
#   flag (see lib/analysis_core/dimensions.py + skills/inspect/SKILL.md (--secrets)).
#
# Public API:
#   SECRET_PATTERNS   bash array of ERE strings, one credential family
#                     per entry. Consumed by:
#                       for p in "${SECRET_PATTERNS[@]}"; do
#                         grep -oE "$p" <<<"$CONTENT"
#                       done
#
# Pattern notes (POSIX ERE adaptations from the Python source):
#   - Python non-capturing `(?:...)` becomes ERE capturing `(...)`.
#   - Python `\s` becomes ERE `[[:space:]]`.
#   - Python `\-` becomes `-` (no need to escape in an ERE char class).
#   - Python multi-line `[\s\S]+?` (non-greedy across newlines) is
#     not portable to POSIX ERE; the PEM-private-key pattern uses a
#     single-line BEGIN marker instead, matching the legacy
#     secret-scan.sh inline set. End-block detection is the caller's
#     responsibility if it matters (the secret-dim engine relies on
#     secret-shape, not on well-formed PEM).

# Bail if executed directly — this file is meant to be sourced.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'secret-patterns.sh must be sourced, not executed.\n' >&2
  exit 1
fi

SECRET_PATTERNS=(
  'AKIA[0-9A-Z]{16}'                                              # AWS access key id (lib/analysis_core/runner.py:1)
  'AIza[0-9A-Za-z_-]{35}'                                         # GCP API key (lib/analysis_core/runner.py:2)
  'ghp_[0-9A-Za-z]{36}'                                           # GitHub personal access token (lib/analysis_core/runner.py:3)
  'gho_[0-9A-Za-z]{36}'                                           # GitHub OAuth token (lib/analysis_core/runner.py:4)
  'sk-[0-9A-Za-z]{32,}'                                           # OpenAI-style secret key (lib/analysis_core/runner.py:5)
  'sk-ant-[0-9A-Za-z-]{32,}'                                      # Anthropic admin key (lib/analysis_core/runner.py:6)
  'xox[baprs]-[0-9A-Za-z-]{10,}'                                  # Slack token (lib/analysis_core/runner.py:7)
  '-----BEGIN [A-Z ]+PRIVATE KEY-----'                            # PEM private key BEGIN marker (lib/analysis_core/runner.py:8; multi-line END matcher dropped for POSIX ERE portability)
  'postgres(ql)?://[^[:space:]:@]+:[^[:space:]@]+@[^[:space:]]+'  # postgres credential URI (lib/analysis_core/runner.py:9)
  'mongodb(\+srv)?://[^[:space:]:@]+:[^[:space:]@]+@[^[:space:]]+' # mongodb credential URI (lib/analysis_core/runner.py:10)
)