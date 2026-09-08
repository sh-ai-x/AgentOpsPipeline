#!/usr/bin/env bash
# stage-gate.sh — consult the active hook matrix before stage-managed hooks run.
#
# The matrix is optional for unbootstrapped consumer repos. Once present, the
# current stage and per-stage hook state become the runtime contract.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  printf 'stage-gate.sh must be sourced, not executed.\n' >&2
  exit 1
fi

hook_stage_active() {
  local hook_name="${1:?hook name required}"
  local root stage plugin_root
  root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  local matrix="$root/.dev-kit/.active-hooks.json"
  [ -f "$matrix" ] || return 0

  stage="${DEV_KIT_STAGE:-}"
  if [ -z "$stage" ]; then
    stage="$(jq -r '.current_stage // ""' "$root/.dev-kit/state.json" 2>/dev/null || true)"
  fi
  [ -n "$stage" ] || stage="bootstrap"

  plugin_root="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-$(cd "${BASH_SOURCE[0]%/*}/../.." && pwd)}}"
  python3 - "$plugin_root" "$root" "$stage" "$hook_name" <<'PY'
import sys
from pathlib import Path

plugin_root, project_root, stage, hook_name = sys.argv[1:]
sys.path.insert(0, str(Path(plugin_root) / "lib"))
from active_hooks_codec import is_hook_active  # noqa: E402

raise SystemExit(0 if is_hook_active(Path(project_root), stage, hook_name) else 1)
PY
}

pre_completion_checklist_active() {
  # The checklist follows stop-verify's stage activation and override rules.
  hook_stage_active stop-verify
}
