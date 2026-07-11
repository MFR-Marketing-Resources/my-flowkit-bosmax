# Data model and state machine audit (repair v1.1)

**Evidence:** `evidence/current_schema_matrix.csv`, `evidence/state_transition_matrix.csv`

## Entity summary

### workspace_generation_package (`agent/db/schema.py` L238+, migrations in `init_db`)

- **PK:** `workspace_generation_package_id`
- **Orchestrator fields:** `batch_run_id`, `logical_mode`, `variation_strategy`, `variation_index`, `prompt_fingerprint`, `production_status`, `production_run_id`, `product_id`
- **Creation:** `start_batch_prompt_run`, compile paths — `workspace_generation_package_service`
- **Restart durability:** rows persist — **VERIFIED_CODE**
- **Fit:** content item / generation package — **extend** for unified plan FK

### production_run (migration ~L1673)

- **PK:** `production_run_id`
- **Status:** PENDING|RUNNING|PAUSED|COMPLETED|FAILED|CANCELLED
- **Throttle:** interval_*, cooldown_*, `max_parallel_jobs` (forced 1 on send)
- **Fit:** microbatch execution container — **reuse**; not daily plan

### bulk_generation_run / bulk_generation_item (L2039+)

- **PK:** `bulk_run_id`, `bulk_item_id`
- **Parallelism:** `max_parallel_images`, `max_parallel_videos`
- **Item status:** QUEUED→…→REGISTERED|FAILED
- **Fit:** execution microbatch for IMG/video — **merge view** under orchestrator

### Legacy batch / batch_variant (L404+)

- **Status:** DRAFT…FAILED; variant `queue_status` enum
- **Bug:** INSERT 20 values for 21 columns — **VERIFIED_CODE** (`failed_test_baseline_matrix.csv`)
- **Fit:** **retire** per D3

### generated_artifact

- **PK:** `media_id`; optional `workspace_generation_package_id`
- **Runtime registration:** `make_video` — **VERIFIED_RUNTIME_BY_PRIMARY_AUTHORITY**, **NOT_REEXECUTED_IN_THIS_AUDIT**

### copy_set / poster_copy_set

- Separate domains — ADR-008 / poster module — **VERIFIED_TEST_IN_THIS_AUDIT** (poster tests in suite)

## Proposed requirement classification

| Requirement | Classification |
|-------------|----------------|
| daily production plan | new table likely |
| wave / microbatch | extend production_run + plan FK |
| generation attempt | new table likely |
| execution lane | new table + lease |
| capacity preflight result | new table or JSON on plan |
| partial completion | extend run totals — partial exists |

## State machines

See `state_transition_matrix.csv` for ten machines including **PROPOSED_unified_orchestrator**.

**Illegal / missing transitions:**

- WGP RUNNING without production_run_id after crash — **ambiguous recovery**
- PAUSED production run after process restart — **NOT_VERIFIED** resumes
- Legacy QUEUED → GENERATED — **missing** (no executor)