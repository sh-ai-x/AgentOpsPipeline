# Hooks (SSOT)

> Matrix state lives in `.dev-kit/.active-hooks.json` (MUST-13).
> Shells live in `hooks/*.sh` and are wired via `hooks/hooks.json`.

## Hook matrix (per stage)

```
| Hook           | Bootstrap | Plan | Design | Build | Review | Security | Ship |
|----------------|:----:|:----:|:----:|:----:|:----:|:----:|:----:|
| tdd-guard       |  -    |  -    |  -    |  ✅    |  -    |  -    |  -    |
| bash-guard      |  -    |  -    |  -    |  ✅    |  -    |  -    |  -    |
| secret-scan     |  R    |  -    |  -    |  ✅    |  ✅    |  ✅    |  -    |
| slop-detector   |  -    |  -    |  -    |  ✅    |  ✅    |  ✅    |  -    |
| stop-verify     |  -    |  ✅    |  ✅    |  ✅    |  ✅    |  ✅    |  ✅    |
```
(R = read-only)

## Hook shells

| Hook | Stage ON | Purpose |
|------|----------|---------|
| `tdd-guard` | build | active when `lib/methodology/tdd.py` is loaded (MUST-48). |
| `bash-guard` | build | blocks dangerous shell patterns (`rm -rf`, force-push, etc.). |
| `secret-scan` | build / review / security | PostToolUse credential-pattern grep. |
| `slop-detector` | build / review / security | KO+EN banned-phrase scan. |
| `stop-verify` | plan / design / build / review / security / ship | Stop hook: AC claim verification. |
| `worktree-guard` | n/a | PreToolUse Edit/Write block on main checkout (this repo). |
| `git-guard` | n/a | PreToolUse Bash block on `git commit`/`push` to main. |
