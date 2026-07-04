# AI Model Routing Settings Foundation V1

## Scope

This document defines the BOSMAX Flow Kit foundation for operator-managed AI
model routing. It adds a checked-in model catalog, local lane-routing
configuration, read/update/reset APIs, and Engine Room controls without
rewiring the canonical final prompt compiler to any external LLM.

## Model Catalog

The model catalog is the approved list of provider/model options exposed to the
operator. Each entry includes:

- `provider_id`
- `model_id`
- `label`
- `capability_tags`
- `recommended_lanes`
- `status`
- `notes`
- `default_for_lanes`
- `locked`

Catalog authority lives in `agent/services/ai_provider_settings_service.py`.
Repo-proven Anthropic and Qwen models are preferred where the codebase already
has runtime authority. Foundation-only provider/model entries remain
`registry_only` or `experimental` until a real adapter is wired.

## Lane Routing

The routing registry stores one route per BOSMAX lane:

- `product_image_analysis`
- `copywriting_assist`
- `angle_hook_subhook_expansion`
- `claim_risk_qa`
- `product_truth_extraction`
- `video_review`
- `final_prompt_compiler`

Each lane stores:

- `provider_id`
- `model_id`
- `enabled`
- `execution_mode`
- `locked`
- `updated_at`
- `source`

The routing state is persisted only in the local Flow Kit state file under
`.local-agent/ai-provider-settings.json`. No secret is written into tracked repo
files.

## Locked Final Compiler

`final_prompt_compiler` is hard-locked to:

- `provider_id = deterministic`
- `model_id = bosmax-canonical-compiler`
- `enabled = true`
- `execution_mode = live`
- `locked = true`

This protects the canonical 9-section BOSMAX compiler and prevents external LLM
routing from contaminating final prompt generation.

## Runtime Behavior

This phase is foundation-first:

- Existing Anthropic-compatible product-image analysis and video-review lanes
  keep their compatibility path.
- Existing Qwen copywriting-assist compatibility is preserved.
- Unsupported provider/lane live combinations fail closed.
- `registry_only` routes may be saved for later wiring without pretending the
  lane is executable now.

Helper accessors are provided in `agent/services/ai_provider_settings_service.py`:

- `get_ai_lane_route`
- `get_ai_lane_model`
- `is_ai_lane_executable`
- `require_ai_lane_or_fail_closed`

## Validation Rules

Backend validation is the source of truth. The routing API rejects:

- locked-lane updates
- unknown providers
- unknown models
- incompatible model/lane pairs
- live execution on lanes without a wired adapter
- live execution without the required provider key

The frontend filters provider/model dropdowns by lane compatibility, but the
backend remains authoritative.

## Adding A New Model Safely

When adding a new model:

1. Add the catalog entry in `agent/services/ai_provider_settings_service.py`.
2. Mark it `available` only if a real adapter exists in repo authority.
3. Otherwise mark it `registry_only` or `experimental`.
4. Restrict `recommended_lanes` to compatible lanes only.
5. Add or update tests before exposing live mode.

## Enabling Live Execution Later

To promote a route from foundation-only to live:

1. Wire the provider adapter in the relevant service.
2. Add the provider/lane pair to the live-support matrix.
3. Add backend tests that prove key gating and fail-closed behavior.
4. Re-run the local validation gates before any Git delivery.

## Secret Handling

- Provider API keys remain in local state / environment only.
- Routing stores only provider/model choices and execution flags.
- API responses expose masked key status only.
- Tests and docs must never print raw API keys.
