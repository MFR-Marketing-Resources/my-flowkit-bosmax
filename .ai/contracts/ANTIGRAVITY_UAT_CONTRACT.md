# Live UAT Contract

This contract governs one-shot live UAT for any operator-authorized runner.
It supersedes the previous Antigravity-exclusive rule: live UAT may be run by
Codex, Claude Code, or Antigravity — but only one-shot, only when the operator
explicitly authorizes that specific runner, and only when every gate below passes.

(Filename retained for reference stability across existing contract pointers.)

## Authorized Runners
- Codex: may run one-shot live UAT when operator-authorized and all gates pass.
- Claude Code: may run one-shot live UAT as an evidence-collection runner only,
  when explicitly assigned by the operator and all gates pass; no patching during UAT.
- Antigravity: allowed but no longer required; the same gates apply.

## A Runner May Run Live UAT Only After
- the operator explicitly authorizes this run for this runner
- local harness passes
- runtime handshake passes
- a clean pushed SHA exists
- a valid `REQUEST_ID` is generated
- background/runner/content build IDs match and are not legacy
- exactly one active extension runtime is confirmed
- exactly one WebSocket worker is confirmed

## A Runner Must Not
- patch
- debug
- loop test
- run a second live retry without explicit operator approval
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
