# Batch prompt and variation audit

## Modern batch prompt planner (`batch_prompt_planner.py`)

| Attribute | Value | Classification |
|-----------|-------|----------------|
| Logical modes | T2V, HYBRID, F2V, I2V | VERIFIED_CODE |
| Variation strategies | SAME_SCRIPT_DIFF_VISUALS, DIFF_SCRIPT_DIFF_VISUALS, SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS | VERIFIED_CODE |
| Quantity range | 1–100 | VERIFIED_CODE (`validate_mode_inputs`) |
| Rotation | avatars, scenes, hooks per strategy | VERIFIED_CODE |
| Fingerprints | sha1 on dialogue/hook/avatar/scene fields | VERIFIED_TEST |
| Dialogue similarity soft ceiling | 0.90 | VERIFIED_CODE |
| DB writes | **None** in planner (pure) | VERIFIED_CODE |

## `start_batch_prompt_run` (`workspace_generation_package_service.py` ~L1416+)

- Compiles N packages into Prompt Queue with `batch_run_id`, `logical_mode`, `variation_strategy`, fingerprints.
- Duration authority fail-closed via `canonical_prompt_compiler.resolve_block_plan` (ADR-008).

## Legacy `batch_planner.py`

| Attribute | Value | Classification |
|-----------|-------|----------------|
| Max quantity | 20 | VERIFIED_CODE (`scheduler_safety`) |
| max_parallel_jobs | Must be 1 | VERIFIED_CODE |
| Variation | `variation_matrix.generate_variation_plan` modulo hooks/scenes | VERIFIED_CODE |
| Fingerprint | `v{{i+1}}_{{product_id[:8]}}` | VERIFIED_CODE — **weak** |
| Execution | **Not** wired to production queue | VERIFIED_CODE |

## Rerun / stable batch identity

- WGP: `batch_run_id` on packages — **VERIFIED_CODE** (field in crud whitelist).
- Legacy `batch.id` new UUID each draft — reruns create **new** batch rows unless operator reuses id manually — **VERIFIED_CODE**.
