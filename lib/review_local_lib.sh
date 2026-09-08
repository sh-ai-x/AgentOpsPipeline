#!/usr/bin/env bash
# review_local_lib.sh — Pure-bash helpers sourced by bin/review-local.sh.
#
# Extracted from bin/review-local.sh so the worst-of rank, the L3
# pytest-tail regex, and the bump-PR title skip can be unit-tested
# hermetically (no `gh` / `claude` / network). Tests source this file
# directly via `bash -c 'source lib/review_local_lib.sh; ...'`.
#
# Functions (all pure; no I/O, no global state mutation beyond the
# declared variables each function reads):
#
#   rank <verdict>
#       Print 0 for Approve, 1 for Changes*, 2 for Blocked, 99 for
#       anything else (unparseable). Mirrors the workflow's combined
#       gate at review.yml:539-561.
#
#   is_bump_pr <pr_title>
#       Print "yes" if the title matches `chore(release): bump dev-kit
#       to v*`, else "no". Mirrors review.yml:75.
#
#   extract_pytest_tail < body
#       Print "yes" if the body contains a pytest tail line
#       (`<N> passed|failed ... in <Ns>s`), else "no". Used by the
#       L3-evidence gate.
#
#   provider_env_for <provider>
#       Print `KEY=VAL` lines (one per line, no `export`) for the
#       provider's ANTHROPIC_* mapping. Empty for anthropic (default).
#       Reads the base-URL / model block from `provider_config` so
#       adding a new provider is a one-line edit in `provider_config`.
#
#   verdict_default_for <verdict_var>
#       Print "yes" if the variable is empty/unset (i.e. the lenient
#       default-to-Approve policy should apply), else "no". Mirrors
#       review.yml:521-522.
#
#   provider_config <provider>
#       Single source of truth for per-provider config. The output is a
#       pipe-separated tuple: `<api_key_env_name>|<base_url>|<sonnet_model>`.
#       The first field is always set (every provider has a key env
#       name); the second is empty for anthropic (uses default base
#       URL); the third is the model id (empty for anthropic -- lets
#       the Claude CLI pick the default model). `provider_env_for`
#       reads from this helper so the two paths cannot drift.

# Guard against double-sourcing in test runners.
if [ -n "${REVIEW_LOCAL_LIB_SOURCED:-}" ]; then
  return 0
fi
REVIEW_LOCAL_LIB_SOURCED=1

rank() {
  case "$1" in
    Blocked) echo 2 ;;
    "Changes"*) echo 1 ;;
    Approve) echo 0 ;;
    *) echo 99 ;;
  esac
}

is_bump_pr() {
  case "$1" in
    "chore(release): bump dev-kit to v"*) echo yes ;;
    *) echo no ;;
  esac
}

extract_pytest_tail() {
  # POSIX-portable: no `[[ ... =~ ... ]]`. Use grep -E for portability.
  if printf '%s' "$1" | grep -qE '[0-9]+ (passed|failed)(, [0-9]+ (skipped|xfailed|xpassed))? in [0-9.]+s'; then
    echo yes
  else
    echo no
  fi
}

provider_env_for() {
  # Reads from `provider_config` so adding a new provider is a
  # one-line edit in one place. anthropic returns empty (no overrides
  # needed); other providers emit 5 ANTHROPIC_* lines.
  local cfg base model
  cfg="$(provider_config "$1")" || return 1
  base="${cfg#*|}"; base="${base%%|*}"
  model="${cfg##*|}"
  if [ -z "$base" ] && [ -z "$model" ]; then
    return 0
  fi
  printf '%s\n' \
    "ANTHROPIC_BASE_URL=$base" \
    "ANTHROPIC_MODEL=$model" \
    "ANTHROPIC_DEFAULT_SONNET_MODEL=$model" \
    "ANTHROPIC_DEFAULT_OPUS_MODEL=$model" \
    "ANTHROPIC_DEFAULT_HAIKU_MODEL=$model"
}

verdict_default_for() {
  if [ -z "${1:-}" ]; then
    echo yes
  else
    echo no
  fi
}

# Single source of truth for per-provider config. The output is a pipe-
# separated triple: `<api_key_env_name>|<base_url>|<sonnet_model>`. The
# first field is always set (every provider has a key env name); the
# second is empty for anthropic (uses default base URL); the third is
# the model id (empty for anthropic -- lets the Claude CLI pick the
# default model). `provider_env_for` reads from this helper so the two
# paths cannot drift.
#
# Callers that want the API-key env name should capture field 1 of this
# helper's output. Callers that want the base-URL / model block should
# source `provider_env_for`.
provider_config() {
  case "$1" in
    minimax)   printf '%s|%s|%s\n' "MINIMAX_API_KEY" "https://api.minimax.io/anthropic" "MiniMax-M3[1m]" ;;
    anthropic) printf '%s|%s|%s\n' "ANTHROPIC_API_KEY" "" "" ;;
    deepseek)  printf '%s|%s|%s\n' "DEEPSEEK_API_KEY" "https://api.deepseek.com/anthropic" "deepseek-v4-pro" ;;
    *) return 1 ;;
  esac
}
