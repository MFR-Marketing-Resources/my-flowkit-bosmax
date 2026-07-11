# Failure recovery and idempotency (repair v1.1)

**Evidence:** `evidence/failure_recovery_matrix.csv`

## Inherited runtime claims

| Claim | Authority | Re-run this audit? |
|-------|-----------|-------------------|
| ADR-007 job completion + artifact insert | CURRENT_STATE, ADR-007 | **NO** — `NOT_REEXECUTED_IN_THIS_AUDIT` |
| Extension WS telemetry | RUNTIME_TELEMETRY_LOCKDOWN | **NO** |

## Scenario coverage (summary)

| Scenario | Classification |
|----------|----------------|
| Local agent restart | bulk `recover_stuck_bulk_runs` partial; production **manual** |
| Backend restart | in-memory `_run_control` lost — **PROCESS_MEMORY_ONLY** |
| Extension disconnect | jobs may stall; poll timeout paths — **VERIFIED_CODE** partial |
| VIDEO_JOB_IN_FLIGHT | retry loop — **VERIFIED_TEST_IN_THIS_AUDIT** |
| Duplicate submission | **NOT_VERIFIED** — no idempotency key |
| Lost response after provider accept | **NOT_VERIFIED** |
| Artifact DB fail after download | logged; re-harvest possible — **VERIFIED_CODE** |
| QA reject → replacement | **MISSING** unified replacement item |
| Pause / resume / cancel | signals only — restart **NOT_VERIFIED** |
| Provider rate limit | **BLOCKED_BY_EXTERNAL_RUNTIME** |

## Target behaviours (PROPOSED)

- Durable `generation_attempt` with idempotency key per item+attempt index
- Lane lease with TTL and fencing token
- Transactional artifact register (media_id + WGP FK)

## Acceptance proof required later

Integration: kill process mid-run → resume without double credit spend.
Live: authorized smoke only.