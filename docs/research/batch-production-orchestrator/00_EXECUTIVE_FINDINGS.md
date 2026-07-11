# Executive findings — Batch production orchestrator audit v1

**Examined commit:** `b271f5e162f45c75cf94e88be5c0bc9cadbd6103` (`origin/main`)

## Implementation readiness verdict

**`HOLD_RUNTIME_PROOF_REQUIRED`**

Rationale: Throughput at 200 videos + 200 images/day, safe combined concurrency, and multi-lane provider capacity are **not** established by runtime evidence. Code enforces **video serial single-flight** (`VIDEO_JOB_IN_FLIGHT`). Image bulk allows **2–3 parallel workers in-process** but provider independence is **NOT_VERIFIED**. Repository also lacks a unified daily production plan / wave / microbatch orchestrator (**MISSING** / **PROPOSED**).

## Key verified findings (code/tests)

| Finding | Classification | Anchor |
|---------|----------------|--------|
| One hardened generation door ADR-007 | VERIFIED_RUNTIME (authority) | `make_video.start_generate`, `/api/flow/execute-flow-job` |
| Production queue serial dequeue `limit=1` | VERIFIED_CODE | `production_queue_service._live_production_loop` |
| `max_parallel_jobs=1` on production run create | VERIFIED_CODE | `production_queue_service.send_to_production` |
| Video lane lock `_VIDEO_LANE_JOB` | VERIFIED_CODE | `make_video.py` ~L292–304 |
| Batch prompt builder qty 1–100, one logical mode | VERIFIED_CODE | `batch_prompt_planner`, `start_batch_prompt_run` |
| Legacy `/api/batches` queue **does not** start Flow | VERIFIED_CODE | `batch_queue.py` message |
| Bulk video `_clamp_parallel_videos` → 1 | VERIFIED_CODE | `bulk_generation_service.py` |
| Bulk IMG parallel clamp 1–3 | VERIFIED_CODE | `_clamp_parallel_images` |
| Legacy `batch_planner` max qty **20** | VERIFIED_CODE | `scheduler_safety.py` |
| Legacy batch unit tests **fail** (fixture/DB) | VERIFIED_TEST | `test_batch_planner.py`, `test_batch_queue.py` |

## Concurrency results (mandatory)

| Metric | Value |
|--------|--------|
| `VERIFIED_SAFE_VIDEO_CONCURRENCY` | `1_SAFE_DEFAULT` |
| `VERIFIED_SAFE_IMAGE_CONCURRENCY` | `NOT_VERIFIED` (code allows 2–3 workers; no live provider proof) |
| `VERIFIED_SAFE_COMBINED_CONCURRENCY` | `NOT_VERIFIED` |

## Critical blockers for 200+200/day

1. **Architecture:** No single daily production plan entity; parallel paths (`batch`, `production_run`, `bulk_generation_run`, WGP `batch_run_id`).
2. **Throughput:** Serial video + 45–120s inter-job interval + cooldown → theoretical ceiling far below 200 videos/day on one lane.
3. **Runtime:** ADR-007 live-proven **manual/single-job** lanes; **not** proven for bulk production queue at scale (**BLOCKED_BY_EXTERNAL_RUNTIME** for rate limits per CURRENT_STATE).
4. **Dedupe:** Rich planner fingerprints vs weak legacy `v{i}_productId` fingerprints; no proven max unique capacity preflight.
5. **Posters:** Poster module is prompt-first; no poster bulk orchestrator equivalent to `bulk_generation_run`.

## Authority conflicts noted (not resolved here)

- `.ai/status/CURRENT_STATE.md` last updated 2026-07-02; repo `main` has since gained bulk generation, batch-prompt split, poster modules — **secondary evidence** documents newer code; **CURRENT_STATE** remains primary for ADR-007 locked generation list until updated by maintainers.

## Tests executed (non-destructive)

```text
pytest tests/unit/test_batch_planner.py tests/unit/test_batch_queue.py \
  tests/unit/test_production_queue_service.py tests/unit/test_bulk_generation_service.py \
  tests/api/test_batch_prompt_and_production_api.py tests/api/test_bulk_generation_api.py -q
Result: 4 failed, 47 passed (legacy batch failures pre-existing per CURRENT_STATE open items)
```
