# Production queue and concurrency audit

## Video queue (`production_queue_service.py`)

- Run created with `dry_run=True`, `max_parallel_jobs=1` (hardcoded in `send_to_production`).
- Loop selects **one** QUEUED package at a time (`list_production_queue_packages` limit=1).
- Fires `make_video.start_generate`; on `VIDEO_JOB_IN_FLIGHT` retries up to 20 × 30s.
- Pause/cancel via `_run_control` dict — **PROCESS_MEMORY_ONLY**.

## Lock scope (`make_video.py`)

| Scope | Mechanism | Classification |
|-------|-----------|----------------|
| Process | `_VIDEO_LANE_JOB` global | VERIFIED_CODE |
| Video modes | T2V, I2V, F2V | VERIFIED_CODE |
| IMG | Exempt from video lane lock | VERIFIED_CODE |

**Not** scoped per: account, Flow project, browser tab, extension connection (single in-process lock).

## Bulk generation (`bulk_generation_service.py`)

- Video: `_clamp_parallel_videos` forces **1**.
- IMG: semaphore `max_parallel` 1–3, each calls `make_video.start_generate("IMG", ...)`.

## Mandatory concurrency declaration

```
VERIFIED_SAFE_VIDEO_CONCURRENCY=1_SAFE_DEFAULT
VERIFIED_SAFE_IMAGE_CONCURRENCY=NOT_VERIFIED
VERIFIED_SAFE_COMBINED_CONCURRENCY=NOT_VERIFIED
```

Async `asyncio.gather` workers ≠ proven independent Google Flow lanes.
