# Iron Laws (SSOT — MUST-8)

> Source of truth for project invariants. Read once before any decision.

- **L1**: No prod code without verification artifact (test/contract/domain/scenario/feature per methodology)
- **L2**: No fix without reproducing the bug (Phase 1 = reproduce)
- **L3**: No completion claim without quoted exit code / test count / build log
- **L4**: No TODO/FIXME/'we'll extend later'/'this is a starting point'
- **L5**: No option/alternative list when not asked. One answer.
- **L6**: New skills must declare `alpha: state|enforcement|analysis` in frontmatter. Reasoning-only `analysis` skills are tolerated only for distinct user intents — minimize new instances.
- **L7**: A skill's alpha lives in the parts the model can't self-impose (deterministic enforcement, stateful processes, audit artifacts). Don't spend alpha on reasoning the next-gen model will absorb.
- **L8**: Skill prompt prose that duplicates state-machine / hook / gate behavior must be trimmed. The state machine is the contract; prose is just orientation. Don't restate the contract in prose — reference the SSOT.

(hooks emit "Iron Law #N violation" stderr only. Bodies not duplicated.)
