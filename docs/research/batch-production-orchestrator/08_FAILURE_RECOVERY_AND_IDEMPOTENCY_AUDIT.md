# Failure recovery and idempotency audit

See `evidence/failure_recovery_matrix.csv`.

## Highlights

| Scenario | Classification |
|----------|----------------|
| VIDEO_JOB_IN_FLIGHT retry | VERIFIED_TEST |
| Production pause/cancel mid-run | PROCESS_MEMORY_ONLY |
| Agent restart during production_run RUNNING | NOT_VERIFIED |
| `recover_stuck_bulk_runs` on lifespan | VERIFIED_CODE (bulk only) |
| Duplicate credit spend protection | PARTIAL — serial video + dry_run gate; not formal idempotency keys |

Item-level failure in batch: production loop marks FAILED and continues — **VERIFIED_CODE**.
