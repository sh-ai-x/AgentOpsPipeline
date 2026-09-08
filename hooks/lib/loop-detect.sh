# loop-detect.sh — doom-loop detector (sourced helper).
#
# Read by the PostToolUse Bash hook after every Bash call. Compares the
# last N log entries against the current call by tool name + first 80
# chars of input; returns 1 if the last <threshold> entries (including
# the current one) are identical, 0 otherwise.
#
# Why this exists:
#   Doom loops (3+ identical Bash retries, no progress, no let-up) burn
#   ~5-10k tokens per occurrence and are silent. The agent retries with
#   the same input expecting a different result. This helper fails
#   loudly on the third identical call so the agent can switch tools or
#   ask the user before the fourth attempt.
#
# Entry format (one per line, append-only):
#   <tool_name>\t<input_first_<LOOP_DETECT_PREFIX_LEN>_chars>
#
# Env knobs (all override-able per call; defaults shown):
#   LOOP_DETECT_LOG_DIR    = .dev-kit/hand-off
#   LOOP_DETECT_SESSION_ID = ${SESSION_ID:-}      (required; empty = no-op)
#   LOOP_DETECT_WINDOW     = 10 (minimum history scan; threshold may expand it)
#   LOOP_DETECT_THRESHOLD  = 3
#   LOOP_DETECT_PREFIX_LEN = 80
#
# Style: mirror hooks/lib/slot-check.sh — sourced, not executed.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'loop-detect.sh must be sourced, not executed.\n' >&2
  exit 1
fi

# loop_detected <tool_name> <input>
#   Returns 0 = no loop detected (caller continues normally).
#   Returns 1 = doom loop detected (caller should emit a recovery hint).
#   Side effect: appends "<tool_name>\t<input_prefix>" to the per-session
#   log so the NEXT call can compare against this one.
loop_detected() {
  local tool_name="${1:?tool_name required}"
  local input="${2-}"
  local prefix_len="${LOOP_DETECT_PREFIX_LEN:-80}"
  local threshold="${LOOP_DETECT_THRESHOLD:-3}"
  local window="${LOOP_DETECT_WINDOW:-10}"
  local log_dir="${LOOP_DETECT_LOG_DIR:-.dev-kit/hand-off}"
  local session_id="${LOOP_DETECT_SESSION_ID:-${SESSION_ID:-}}"
  local log_file

  # Truncate input deterministically: collapse newlines to spaces, then
  # keep the first <prefix_len> chars. `cut -c` is char-based on ASCII
  # and on UTF-8-safe locales; identical input always produces identical
  # prefixes, which is what the equality comparison needs.
  local prefix
  prefix="$(printf '%s' "$input" | tr '\n' ' ' | cut -c1-"${prefix_len}")"

  # No session id → no log path → cannot detect. Fail open (no loop).
  [ -n "$session_id" ] || return 0

  log_file="${log_dir}/${session_id}.log"
  mkdir -p "$log_dir" 2>/dev/null || true

  # Count how many PRIOR consecutive log entries match the current
  # call's fingerprint; add this current call → (count + 1) consecutive
  # matches. If that meets or exceeds the threshold, the loop fires.
  # A threshold can exceed the configured window, so scan enough prior
  # entries to make every documented threshold reachable.
  local history_limit="$window"
  local required_prior_count=$((threshold > 1 ? threshold - 1 : 0))
  if [ "$required_prior_count" -gt "$history_limit" ]; then
    history_limit="$required_prior_count"
  fi

  local prior_matches=0
  if [ -f "$log_file" ]; then
    local pattern="${tool_name}	${prefix}"
    # tail keeps read cost bounded regardless of how long the log has
    # grown; awk walks the slice bottom-up and stops on the first mismatch
    # (consecutive from-the-bottom only).
    prior_matches="$(
      tail -n "$history_limit" "$log_file" 2>/dev/null | awk -F '\t' -v want="$pattern" '
        { lines[NR] = $0 }
        END {
          c = 0
          for (i = NR; i >= 1; i--) {
            if (lines[i] == want) c++
            else break
          }
          print c
        }'
    )"
    prior_matches="${prior_matches:-0}"
  fi

  # Append this call's fingerprint (always — even on detection, so the
  # caller can see consecutive matches if it inspects the log).
  printf '%s\t%s\n' "$tool_name" "$prefix" >> "$log_file" 2>/dev/null || true

  if [ "$((prior_matches + 1))" -ge "$threshold" ]; then
    return 1
  fi
  return 0
}
