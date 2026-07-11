# 13 — Unique capacity preflight (PROPOSED functional contract)

**Classification:** `PROPOSED` — not implemented in repository at examined SHA.

## Purpose

Before committing credits to a daily production plan, compute the **maximum safe count** of unique creatives achievable from **approved** pools, minus historical collisions, under selected variation strategy and duplicate policies.

## Required inputs

| Input | Source | Required |
|-------|--------|----------|
| `product_id` | operator | Y |
| `target_video_count` | daily plan | Y if video |
| `target_poster_count` | daily plan | Y if poster |
| `variation_strategy` | batch prompt enum | Y |
| `logical_mode` | mode contract | Y |
| `avatar_pool` | approved avatars / codes | Y for video |
| `scene_pool` | approved scene asset IDs | conditional |
| `copy_pool` | approved `copy_set_id` list | conditional |
| `hook_pool` | optional explicit hooks | N |
| `history_window` | product production history | default policy |
| `controlled_reuse_policy` | D5 | Y |
| `dedupe_thresholds` | D5 | Y |

## Pool dimensions (eligibility)

Each dimension must expose: stable ID, approval flag, mode eligibility, claim-safety gate.

- Copy: `copy_set` status APPROVED; poster: `poster_copy_set` POSTER_COPY_APPROVED
- Avatar: registry + creative_asset CHARACTER_REFERENCE approved
- Scene: SCENE_CONTEXT_REFERENCE approved
- Angles: safe-angle / customer-avatar references per product truth

**Fail closed:** if any mandatory pool empty → `PREFLIGHT_BLOCKED`.

## Calculation output (PROPOSED)

```json
{
  "max_unique_video_slots": 0,
  "max_unique_poster_slots": 0,
  "max_unique_combined": 0,
  "binding_dimension": "avatar_pool|copy_pool|cartesian_product",
  "shortfall_video": 0,
  "shortfall_poster": 0,
  "warnings": [],
  "hard_blocks": [],
  "estimated_duplicate_risk": "LOW|MEDIUM|HIGH"
}
```

## Operator decision states (PROPOSED)

| State | Meaning |
|-------|---------|
| `PREFLIGHT_OK` | Requested qty ≤ max safe |
| `PREFLIGHT_SHORTFALL` | qty > max; operator must reduce qty or expand pools |
| `PREFLIGHT_BLOCKED` | mandatory pool missing |
| `PREFLIGHT_OVERRIDE_REQUESTED` | operator acknowledges risk (requires role + audit log) |

## Relationship to existing code

| Component | Reuse |
|-----------|-------|
| `batch_prompt_planner.plan_batch_prompt_variants` | Cartesian + fingerprint logic |
| `variation_matrix` | legacy strategies |
| `copy_sets` uniqueness fields | partial |
| Product history inputs | `product_history_inputs` in planner |

**Gap:** no service aggregates pools + history into a single preflight API.

## Acceptance proof (future implementation)

- Unit: fixed pools → deterministic max count
- Integration: shortfall when qty=101 with max=100
- No credit spend in preflight path