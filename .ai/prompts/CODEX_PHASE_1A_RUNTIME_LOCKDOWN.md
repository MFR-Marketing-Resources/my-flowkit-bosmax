# CODEX PHASE 1A: Runtime And Telemetry Lockdown

ROLE
- You are Codex acting as the BOSMAX Flow Kit implementation owner.

READ FIRST
- `AGENTS.md`
- `.ai/status/CURRENT_STATE.md`
- `.ai/contracts/CODEX_IMPLEMENTATION_CONTRACT.md`
- `.ai/contracts/RUNTIME_TELEMETRY_LOCKDOWN.md`
- `.ai/contracts/REPORT_REJECTION_RULES.md`

OBJECTIVE
- Implement the runtime/build handshake and telemetry lockdown without touching live Google Flow.

DO NOT
- Do not run Google Flow.
- Do not run Antigravity.
- Do not patch upload strategy.
- Do not click Generate.

REQUIRED WORK
1. Verify the background/content build handshake design.
2. Enforce non-legacy build reporting.
3. Lock telemetry to the required schema.
4. Add or update local proof for the handshake.

VALIDATION
- Run the relevant local static and harness commands.
- Produce exact pass/fail output.
- Stop if the contract pack conflicts with the task.

FINAL REPORT
- `STATUS`
- `FILES_CHANGED`
- `VALIDATION_RESULTS`
- `COMMIT_SHA`
- `PUSH_STATUS`
- `NEXT_DECISION`
