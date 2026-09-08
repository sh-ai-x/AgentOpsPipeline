#!/usr/bin/env bash
# worktree-detect.sh — shared "am I in a worktree?" check for the
# every-task-new-worktree rule.
#
# Sourced (not executed) by hooks/worktree-guard.sh,
# hooks/session-start-check.sh.
# Duplication has been a maintenance trap — keep this file as the
# single source of truth for the discriminator.
#
# Public API:
#   worktree_detect                — sets $WORKTREE_DETECT to one of:
#                                    "worktree", "main", "outside", or
#                                    leaves it empty on jq-less no-op.
#   worktree_detect_jq_missing_warn — emit a stderr warning to stdout
#                                    then echo 0 (advisory). Used by
#                                    advisory hooks (session-start-check,
#                                    session-start-check) which can't
#                                    hard-block on missing jq.

# worktree_detect — set $WORKTREE_DETECT to "worktree" or "main"
# based on the discriminator. Caller must `cd` into the right
# working dir before sourcing (each hook has its own cwd policy).
#
# The discriminator is `git rev-parse --git-dir == --git-common-dir`:
#   - In the MAIN checkout both return the same path
#     (`.git` or its absolute form).
#   - In any WORKTREE, --git-dir returns `<common>/worktrees/<name>`
#     while --git-common-dir returns `<common>` — the two differ.
#   - Outside any git working tree, git rev-parse fails and we return
#     "outside" so the caller knows the rule does not apply.
#
# To avoid absolute-vs-relative path mismatches in subdirectories and
# on hosts where /tmp is a symlink (macOS: /tmp → /private/tmp), the
# rev-parse is run from `--show-toplevel` and both paths are
# canonicalized via `realpath`.
worktree_detect() {
  WORKTREE_DETECT=""

  if ! command -v jq >/dev/null 2>&1; then
    # jq missing — caller decides whether to fail closed or warn.
    # Both worktree-guard and the advisory hooks handle this.
    return 1
  fi

  local git_dir_raw git_common_raw toplevel
  toplevel="$(git rev-parse --show-toplevel 2>/dev/null)" || { WORKTREE_DETECT="outside"; return 0; }
  git_dir_raw="$(cd "$toplevel" && git rev-parse --git-dir 2>/dev/null)" || { WORKTREE_DETECT="outside"; return 0; }
  git_common_raw="$(cd "$toplevel" && git rev-parse --git-common-dir 2>/dev/null)" || { WORKTREE_DETECT="outside"; return 0; }

  local git_dir git_common
  git_dir="$(abspath "$git_dir_raw")"
  git_common="$(abspath "$git_common_raw")"
  git_dir="${git_dir%/}"
  git_common="${git_common%/}"

  if [ "$git_dir" = "$git_common" ]; then
    WORKTREE_DETECT="main"
  else
    WORKTREE_DETECT="worktree"
  fi
  return 0
}

# abspath — canonicalize a path to absolute. Uses realpath when
# available (macOS ships it by default since 10.12), falls back to
# identity / manual resolution.
abspath() {
  local p="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$p" 2>/dev/null || printf '%s' "$p"
  else
    case "$p" in
      /*) printf '%s' "$p" ;;
      *) printf '%s/%s' "$PWD" "$p" ;;
    esac
  fi
}

# worktree_detect_jq_missing_warn — emit a stderr warning when jq is
# missing. Used by the advisory hooks (session-start-check,
# session-start-check) which can't hard-block on missing jq. The
# hard-block hook (worktree-guard) fails closed (exit 2) instead.
worktree_detect_jq_missing_warn() {
  local hook_name="$1"
  printf '[%s] jq is required to enforce the worktree rule but is not installed. Install jq (apt/brew/apk) — without it, this hook is a no-op.\n' "$hook_name" >&2
  return 0
}
