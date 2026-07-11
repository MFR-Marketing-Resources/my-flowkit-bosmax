# Operator workflow and UX audit (repair v1.1 — functional contract)

No UI mock-ups. Each row: surface → action → API → DB → state.

| Step | Surface | Action | API | DB mutation | Result state | Proof to operator |
|------|---------|--------|-----|-------------|--------------|-------------------|
| Create daily plan | **MISSING** | set video/poster targets | PROPOSED | PROPOSED plan row | PLANNED | shortfall summary |
| Select product | Batch Prompt Builder / modes | pick product | batch-prompts body | WGP product_id | DRAFT WGPs | product name snapshot |
| Variation strategy | Batch Prompt Builder | dropdown | `variation_strategy` | per WGP fields | planned variants | matrix preview |
| Capacity preflight | **MISSING** | run preflight | PROPOSED | none | PREFLIGHT_* | max safe count doc 13 |
| Compile prompts | Batch Prompt Builder | submit | POST batch-prompts | WGP rows | DRAFT/READY | fingerprints, warnings |
| Duplicate risk | Prompt Queue | review list | GET packages | read | warnings_json | soft/hard flags |
| Bulk approve | Prompt Queue | approve | POST approve | production_status APPROVED | APPROVED | count approved |
| Assign production | Production Queue | send | POST production-queue | QUEUED + run | QUEUED | run id, dry_run |
| Credit confirm | Production Queue / bulk | confirm live | start with flags | run RUNNING | RUNNING | confirm checkbox |
| Monitor | Production Queue, bulk toolbar | poll | GET status | read | progress % | completed/failed |
| Pause/resume/cancel | Production Queue | buttons | pause/resume/cancel | run status* | PAUSED/CANCELLED | *process memory |
| Retry failed | per-item UI partial | retry item | PROPOSED / manual requeue | item status | QUEUED | error_log |
| QA output | Creative Library | approve/reject | creative asset APIs | review_status | ACTIVE/ARCHIVED | QA fields |
| Poster | Poster Builder | draft/save | poster APIs | poster_deliverable | POSTER_* | copy gate |
| Export/publish | Postiz / social copy | publish | postiz APIs | publish records | PUBLISHED | record ids |

**Gaps:** daily plan, preflight, unified control tower, durable pause proof — see `11` D7.