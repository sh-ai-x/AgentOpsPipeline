# slot-check.sh — plugin.json version-slot freshness predicate.
#
# Extracted from hooks/git-guard.sh:_verify_slot (inspect 2026-08-03
# finding #2) so the truth table is unit-testable in isolation instead
# of being inlined in a PreToolUse hook where the bash precedence of
# mixed `||` and `&&` produced a parse the original author did not
# intend.
#
# Contract: both `.claude-plugin/plugin.json` and
# `.codex-plugin/plugin.json` must be pinned to the version that
# `origin/main` advertises. A Codex-only drift would let a Codex
# sub-agent push a stale slot even after the Claude manifest is
# re-pinned, so the predicate denies if EITHER manifest is stale
# relative to expected. The Claude manifest is checked unconditionally
# (an empty value is itself a drift from `expected`). The Codex
# manifest, by contrast, is checked only when non-empty — an empty
# (missing-file) Codex value is treated as "not yet authored" and does
# not by itself trigger deny, matching the original guard's intent.

# slot_should_deny <actual_claude> <actual_codex> <expected>
#   Returns 0 (deny) when either manifest is stale; 1 (allow) otherwise.
slot_should_deny() {
  local actual_claude="$1" actual_codex="$2" expected="$3"
  if [ "$actual_claude" != "$expected" ]; then
    return 0
  fi
  if [ -n "$actual_codex" ] && [ "$actual_codex" != "$expected" ]; then
    return 0
  fi
  return 1
}
