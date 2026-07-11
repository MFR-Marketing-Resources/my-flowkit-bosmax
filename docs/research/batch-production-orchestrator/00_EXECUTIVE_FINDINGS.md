# 00 — Executive findings (repair v1.1)

**Report version:** 1.1.0-repair  
**Examined base:** `main` @ `b271f5e162f45c75cf94e88be5c0bc9cadbd6103`  
**Pre-repair PR head:** `fe6206ec4b0c9c0ca8873c0cd925a06f27291310`  
**CI_STATUS:** `NO_WORKFLOW_RUN_FOUND` (GitHub `statusCheckRollup` empty for PR #305 at repair time)

## Implementation readiness verdict

**`READY_FOR_ARCHITECTURE_LOCK_REVIEW`**

Runtime proof for image/combined concurrency and 200/day throughput remains **out of scope** of this documentation repair; see **REMAINING_RUNTIME_PROOF** below.

## Repair summary (v1.1)

| Repair | Status |
|--------|--------|
| Manifest provenance (no stale final SHA) | Done — `manifest.json` → `provenance` block |
| Runtime classification clarity | Done — `VERIFIED_RUNTIME_BY_PRIMARY_AUTHORITY`, `NOT_REEXECUTED_IN_THIS_AUDIT` |
| Failed test baseline proof | Done — `evidence/failed_test_baseline_matrix.csv` |
| Schema / state / failure / surfaces / routes | Expanded CSV + `06`, `08` |
| Unique capacity preflight contract | `13_UNIQUE_CAPACITY_PREFLIGHT_CONTRACT.md` |
| Throughput formulas | `09` expanded |
| D1–D7 decision register | `11` expanded |
| UX functional contract | `07` expanded |

## Verified findings (evidence-bound)

| Finding | Classification | Anchor |
|---------|----------------|--------|
| Video lane single-flight | `VERIFIED_CODE` | `make_video._VIDEO_LANE_JOB` |
| Production queue serial dequeue | `VERIFIED_CODE` | `production_queue_service._live_production_loop` limit 1 |
| ADR-007 door | `VERIFIED_RUNTIME_BY_PRIMARY_AUTHORITY` | `.ai/status/CURRENT_STATE.md`; **NOT_REEXECUTED_IN_THIS_AUDIT** |
| Batch prompt qty 1–100 | `VERIFIED_CODE` | `batch_prompt_planner.validate_mode_inputs` |
| Legacy batch no Flow | `VERIFIED_CODE` | `batch_queue.queue_batch` |
| Legacy batch tests fail on base + branch | `VERIFIED_TEST_IN_THIS_AUDIT` | `failed_test_baseline_matrix.csv` |

## Concurrency (explicit)

| Metric | Value |
|--------|-------|
| `VERIFIED_SAFE_VIDEO_CONCURRENCY` | `1_SAFE_DEFAULT` |
| `VERIFIED_SAFE_IMAGE_CONCURRENCY` | `NOT_VERIFIED` |
| `VERIFIED_SAFE_COMBINED_CONCURRENCY` | `NOT_VERIFIED` |

## Test subset (this audit)

Command: see `manifest.json` → `tests_executed`.

| Result | Count |
|--------|-------|
| Passed | 47 |
| Failed | 4 (legacy `test_batch_planner`, `test_batch_queue`) |

Baseline: all four failures **match** on examined base SHA `b271f5e` (detached worktree `C:/tmp/bosmax-base-audit`). Documentation changes **cannot** affect test outcome.

## Remaining runtime proof (post architecture lock)

- Live multi-image worker ceiling on Google account
- Combined video+image under rate limits
- Optional second verified execution lane
- End-to-end 200+200 day simulation (no credit spend in this mission)

## PROPOSED default architecture positions

Listed in `10_TARGET_ARCHITECTURE_PROPOSAL.md` and `manifest` — **not approved**.