# slop-detector v2 — references/ loader contract

This directory is the **SSOT** for the slop-detector v2 scanner. The hook (`hooks/slop-detector.sh`) and the `audit --slop-only` mode (inlined into `skills/inspect/SKILL.md (--slop)`) both load from here; nothing inside `hooks/slop-detector.sh` is duplicated.

## File roles

| File | Format | Loaded by | Purpose |
|---|---|---|---|
| `phrases.md` | line-delimited POSIX ERE, `# =` comment, blank = skip | hook (T1) + skill (T1) | High-signal n-gram bank. KO + EN. |
| `structures.md` | line-delimited POSIX ERE, `# =` comment, blank = skip | hook (T2) + skill (T2) | Structural regex bank (binary contrast, false agency, Wh-starters, lazy extremes, KO structure). |
| `scoring.md` | plain markdown, no machine-parsed lines | skill only | 1-10 × 5-dim rubric (Directness / Rhythm / Trust / Authenticity / Density). |
| `examples.md` | plain markdown | skill (reference only) | Before/after fixtures for human reviewers. Real fixtures live under `tests/fixtures/slop/`. |

## Loader (POSIX shell + grep)

```bash
# Strip `#`-prefixed comments and blank lines, leaving one regex per line.
grep -vE '^[[:space:]]*#|^[[:space:]]*$' "$BANK_FILE"
```

The bank file then flows into `grep -oE -f` (or is grouped by `---` section markers if the consumer wants per-bucket reporting).

## Severity tier

| Match origin | Default bucket |
|---|---|
| Any KO phrase/structure | HIGH |
| Any EN phrase | MEDIUM |
| EN structure only | LOW (consider noise) |

The hook reports a `severity:` line in stderr; the `audit --slop-only` mode (inlined into `skills/inspect/SKILL.md (--slop)`) escalates by `scoring.md` weights.

## Environment

| Var | Default | Effect |
|---|---|---|
| `SLOP_LEVEL` | `2` | `1` = phrase only, `2` = + structure; `3` is accepted as an alias of `2` (the rhythm-density patterns live inside `structures.md` and fire whenever T2 fires) |
| `SLOP_QUIET` | `0` | `1` = suppress stderr (still exit 0) |
| `SLOP_STRICT` | `0` | `1` = exit 2 on HIGH (default = advisory exit 0) |

## Fallback

If `references/slop/phrases.md` (or `structures.md`) is missing at hook startup — e.g. the plugin was installed from an older snapshot — the hook falls back to the in-script minimum bank (the v1 single regex) and prints `[slop-detector] WARN: references/slop/... not loaded, using inline v1 fallback` to stderr once. The scanner keeps working but stays at T1 only.
