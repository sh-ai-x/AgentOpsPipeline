# slop-detector v2 — 5-dim scoring rubric (1-10, total 50)

Rate 1-10 on each dimension. Below 35/50 → revise (per hardikpandya/stop-slop).

| Dimension | Question |
|-----------|----------|
| Directness | Statements or announcements? |
| Rhythm | Varied or metronomic? |
| Trust | Respects reader intelligence? |
| Authenticity | Sounds human? |
| Density | Anything cuttable? |

## Severity ladder (matches the hook runtime — SSOT)

The `audit --slop-only` mode (inlined into `skills/inspect/SKILL.md (--slop)`) applies this ladder to translate raw match counts into a HIGH / MEDIUM / LOW bucket. The runtime hook uses the same thresholds.

| Conditions | Bucket | Rationale |
|---|---|---|
| Any KO phrase OR any KO structure | **HIGH** | KO patterns are very rare in legitimate tech prose; their presence is a strong signal. |
| ≥3 unique T1 phrases OR (≥1 T1 AND ≥1 T2) | **HIGH** | Either density of phrase tells, or one phrase + one shape tell. |
| ≥2 unique T1 phrases | **MEDIUM** | Multiple phrase tells in one Write/Edit block. |
| 1 unique T1 phrase OR 1 T2 structure | **LOW** | Single marker — may be domain jargon or intentional. |
| 0 matches | clean | n/a |

Each tier in the hook caps at 50 unique matches via `head -50` (raised from the early v2 draft's 10, which biased severity on documents with many distinct slop patterns).

## Default behavior

The post-write hook uses **bucket mode**:
- any KO structure or KO phrase  → HIGH
- ≥3 unique T1 OR (≥1 T1 AND ≥1 T2) → HIGH
- ≥2 unique T1 → MEDIUM
- 1 unique T1 OR 1 T2 → LOW
- 0 → clean

Advisory `exit 0` by default. `SLOP_STRICT=1` opts in to `exit 2` on HIGH.

## Env vars (sidebar; full table in `references/slop/README.md`)

| Var | Effect |
|---|---|
| `SLOP_LEVEL=1` | T1 only |
| `SLOP_LEVEL=2` | default; T1 + T2 |
| `SLOP_STRICT=1` | exit 2 on HIGH |
| `SLOP_QUIET=1` | suppress advisory stderr |
