# CODEX PHASE 1C: Selector And Evidence Registry

ROLE
- You are Codex acting as selector-registry engineer.

READ FIRST
- `AGENTS.md`
- `.ai/status/CURRENT_STATE.md`
- `.ai/architecture/SELECTOR_REGISTRY_PLAN.md`

OBJECTIVE
- Extract and classify selectors into a registry that separates proven, unstable, and deprecated paths.

DO NOT
- Do not patch live upload behavior as a shortcut.
- Do not mix failed selectors back into the proven path.

REQUIRED WORK
1. Freeze proven mode/config selectors.
2. Mark unstable upload selectors explicitly.
3. Add evidence metadata and fallback policy.
4. Add local validation for the registry consumer.

FINAL REPORT
- `STATUS`
- `FILES_CHANGED`
- `VALIDATION_RESULTS`
- `COMMIT_SHA`
- `PUSH_STATUS`
- `NEXT_DECISION`
