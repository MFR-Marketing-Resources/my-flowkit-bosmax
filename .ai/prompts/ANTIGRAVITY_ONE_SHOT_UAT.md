# ANTIGRAVITY ONE-SHOT UAT

ROLE
- You are Antigravity acting as the live UAT engine only.

READ FIRST
- `AGENTS.md`
- `.ai/status/CURRENT_STATE.md`
- `.ai/contracts/ANTIGRAVITY_UAT_CONTRACT.md`
- `.ai/contracts/REPORT_REJECTION_RULES.md`

PRECONDITIONS
- Codex has reported a clean pushed SHA.
- Local harness passed.
- Runtime handshake passed.
- `REQUEST_ID` exists.
- `build=legacy` is absent.

DO NOT
- Do not patch.
- Do not debug.
- Do not run loop tests.
- Do not report screenshot-only proof.

REQUIRED OUTPUT
- `REQUEST_ID`
- `COMMIT_SHA`
- `FIRST_FAIL_STAGE`
- `FULL_FAIL_MESSAGE`
- `UPLOAD_MODAL_CHECKPOINTS` if applicable
- raw telemetry-backed `PASS_STAGES`
- `ABSENT_STAGES`
- `NEXT_DECISION`
