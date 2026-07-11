# Data model and state machine audit

See `evidence/current_schema_matrix.csv` and `evidence/state_transition_matrix.csv`.

## Requirements vs schema

| Requirement | Status |
|-------------|--------|
| daily production plan | MISSING — new table likely required (PROPOSED) |
| wave / microbatch | MISSING |
| execution lane record | PARTIAL — `execution_lane` on WGP payload only |
| generation attempt lineage | PARTIAL — job_id on bulk items; production uses production_status |
| credit budget per day | PARTIAL — `daily_credit_limit` on legacy batch only |
| separate image/video targets | PARTIAL — bulk `kind` vs production_run |

No migrations authored in this audit (forbidden).
