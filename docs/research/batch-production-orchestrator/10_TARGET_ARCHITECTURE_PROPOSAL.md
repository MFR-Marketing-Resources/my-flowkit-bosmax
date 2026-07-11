# Target architecture proposal (PROPOSED — not approved)

## Smallest architecture to discuss 200+200/day

1. **PROPOSED** `daily_production_plan` record: targets (video_count, image_count, poster_count), credit_budget, status.
2. **PROPOSED** Unified scheduler facade over existing:
   - WGP batch prompt + approval (keep)
   - `production_run` for video serial lane (keep, extend metrics)
   - `bulk_generation_run` for IMG (keep or merge table view)
3. **PROPOSED** Capacity preflight service using `batch_prompt_planner` pools + copy set counts — **new**.
4. **PROPOSED** Durable run control (replace `_run_control` process memory) — **new table or Redis** — DECISION_REQUIRED.
5. **PROPOSED** QA/replacement loop: FAILED → replacement WGP generation — partial today via retry endpoints.

## Phased vs atomic

**PROPOSED:** Phased safer — Phase A capacity preflight + observability; Phase B durable pause/resume; Phase C optional multi-lane only after runtime proof per lane.

## Reuse (do not rewrite)

- `make_video.start_generate` + ADR-007 manual lane
- `build_execution_payload`
- `batch_prompt_planner` variation law
- `generated_artifact` library

## Migration risk

Merging `production_run` and `bulk_generation_run` risks regression in merge-ready bulk PR — **HIGH** if done atomically.
