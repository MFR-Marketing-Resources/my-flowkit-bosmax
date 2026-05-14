# Antigravity UAT Contract

Antigravity is one-shot UAT only.

## Antigravity May Run Live UAT Only After
- local harness passes
- runtime handshake passes
- Codex reports a clean pushed SHA
- a valid `REQUEST_ID` is generated
- background and content build IDs match and are not legacy

## Antigravity Must Not
- patch
- debug
- loop test
- report manual click screenshots as proof
- report `PASS_STAGES` without raw telemetry
- accept `REQUEST_ID=N/A`
- accept `build=legacy`

## Required UAT Output
- `REQUEST_ID`
- `COMMIT_SHA`
- `FIRST_FAIL_STAGE`
- `FULL_FAIL_MESSAGE`
- raw telemetry-backed `PASS_STAGES`
- `ABSENT_STAGES`
- `NEXT_DECISION`
