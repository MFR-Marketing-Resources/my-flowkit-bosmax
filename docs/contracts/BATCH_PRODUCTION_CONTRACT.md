# BATCH PRODUCTION CONTRACT

## OBJECTIVE
Define the schema and lifecycle for multi-variant generation batches.

## BATCH REQUEST SCHEMA
```json
{
  "batch_id": "uuid",
  "product_id": "uuid",
  "brief_id": "uuid",
  "quantity": 10,
  "platform": "TikTok",
  "objective": "conversion",
  "language": "Malay",
  "engine": "VEO_3_1",
  "duration": 8,
  "mode": "Frames",
  "variation_level": "medium",
  "max_parallel_jobs": 1,
  "interval_min_seconds": 45,
  "interval_max_seconds": 120,
  "cooldown_after_n_jobs": 5,
  "cooldown_seconds": 300,
  "daily_credit_limit": 0,
  "approval_required": true
}
```

## BATCH LIFECYCLE STATES
- `DRAFT`: Initial configuration.
- `READY`: Validated and ready for queue.
- `QUEUED`: Accepted by scheduler.
- `WAITING_INTERVAL`: In cooldown or jitter interval.
- `RUNNING`: Actively being processed by executor.
- `FLOW_MODE_VERIFIED`: Extension confirmed correct Google Flow UI mode.
- `PROMPT_INSERTED`: Content injected into Google Flow prompt field.
- `GENERATION_STARTED`: Generate button clicked.
- `GENERATED`: Video generation complete on platform.
- `DOWNLOADED`: Asset retrieved and stored locally.
- `QA_PASSED`: Automation or manual review successful.
- `QA_FAILED`: Rejected by quality gates.
- `FAILED`: Technical error during lifecycle.
- `RETRY_PENDING`: Scheduled for automated retry.
- `CANCELLED`: User-aborted batch.
