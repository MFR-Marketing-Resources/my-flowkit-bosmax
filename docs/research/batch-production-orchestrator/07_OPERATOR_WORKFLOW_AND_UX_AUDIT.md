# Operator workflow and UX audit (functional contract)

| Screen / area | Action | Backend | DB | Classification |
|---------------|--------|---------|-----|----------------|
| Batch Prompt Builder | POST batch-prompts | `start_batch_prompt_run` | N× WGP insert | VERIFIED_CODE |
| Prompt Queue | Approve packages | `/approve` | production_status | VERIFIED_TEST |
| Production Queue UI | Send to production | `/workspace/production-queue` | production_run + QUEUED | VERIFIED_TEST |
| Production Queue | Start dry/live | `/{run_id}/start` | run status | VERIFIED_TEST |
| Avatar Registry | Bulk IMG toolbar | `/api/bulk-generation/*` | bulk_* tables | VERIFIED_TEST |
| Poster Builder | Prompt draft | `/api/poster/prompt-draft` | none persist prompt package optional | VERIFIED_TEST |
| Legacy Batches API | Draft/queue | `/api/batches` | batch* tables | PARTIALLY_IMPLEMENTED |

Monitoring: production run counters `total_completed` / `total_failed` — **VERIFIED_CODE**. No unified control tower for 200+200 targets — **MISSING**.
