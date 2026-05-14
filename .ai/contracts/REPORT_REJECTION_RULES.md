# Report Rejection Rules

Reject the report if any of the following is true:

- `REQUEST_ID = N/A`
- `build=legacy`
- no raw telemetry
- manual click screenshots only
- `PASS_STAGES` without DB-backed rows or raw stage telemetry
- missing `FIRST_FAIL_STAGE`
- missing `ABSENT_STAGES`
- no commit SHA for a code change
- a "pushed" claim has no remote proof
- the report claims live UAT success without the preflight gates
