# QUEUE SCHEDULER SAFETY CONTRACT

## OBJECTIVE
Define reliability gates and pacing controls for responsible automation execution.

## RELIABILITY SETTINGS
- `interval_min_seconds`: Minimum rest between job starts.
- `interval_max_seconds`: Maximum rest between job starts.
- `random_jitter`: Dynamic variance added to intervals to normalize traffic patterns.
- `max_parallel_jobs`: Concurrency limit for browser/tab execution.
- `max_jobs_per_burst`: Limit on consecutive jobs before a mandatory extended cooldown.
- `cooldown_after_n_jobs`: Trigger for extended rest period.
- `cooldown_after_failure`: Mandatory recovery delay after a technical abort.
- `daily_job_limit`: Hard cap on daily total generations.
- `daily_credit_limit`: Hard cap on platform credit consumption.

## STOP GATES (CIRCUIT BREAKERS)
- **Flow Mismatch**: Stop execution if repeated Google Flow mode mismatches occur.
- **Extension Errors**: Stop execution if MV3 telemetry or communication errors exceed threshold.
- **Manual Intervention**: Require manual approval for any variation flagged with `claim_risk_level: high`.

## GUIDELINES
- This contract focuses exclusively on **reliability** and **rate-control**.
- Do not use language describing "bypassing" or "evading" platform systems.
- Focus on maintaining a healthy, predictable load on the automation targets.
