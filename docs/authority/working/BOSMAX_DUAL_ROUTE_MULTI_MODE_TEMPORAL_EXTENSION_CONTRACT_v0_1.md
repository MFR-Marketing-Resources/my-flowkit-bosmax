# BOSMAX Dual-Route Multi-Mode Temporal Extension Contract v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `BOSMAX_DUAL_ROUTE_MULTI_MODE_TEMPORAL_EXTENSION_CONTRACT` |
| `version` | `v0.1` |
| `status` | `DRAFT_FOR_CODEX_FORENSIC_REVIEW` |
| `implementation_status` | `NO_CODING_AUTHORIZED` |
| `reviewed_base_sha` | `6935930ddd6ef45cb9725d1d9805ab9435116a4f` |
| `reviewed_remote` | `origin/main` |
| `repo_anchor` | `C:\Users\USER\Desktop\_ref_flowkit` |

## 2. Evidence Boundary

### VERIFIED FROM REPO

- The current checkout already exposes four operator-facing mode surfaces: `T2V`, `F2V`, `I2V`, and `IMG`.
  Evidence: `dashboard/src/pages/OperatorPage.tsx`, `dashboard/src/components/workspace/T2VModule.tsx`, `dashboard/src/components/workspace/F2VModule.tsx`, `dashboard/src/components/workspace/I2VModule.tsx`, `dashboard/src/components/workspace/IMGModule.tsx`.
- The current checkout already has product mapping, product intelligence, and product physics layers.
  Evidence: `agent/services/product_mapping.py`, `agent/services/product_intelligence.py`, `agent/services/product_physics.py`, `agent/api/products.py`.
- The current checkout already has a 9-section prompt compiler contract.
  Evidence: `docs/contracts/PROMPT_COMPILER_9_SECTION_CONTRACT.md`.
- The current checkout already has product mapping and naming contracts tied to FastMoss-backed and manual product resolution.
  Evidence: `docs/contracts/PRODUCT_MAPPING_AND_FLOW_NAMING_CONTRACT.md`.
- The current checkout already has batch planning, queue, and execution-status surfaces.
  Evidence: `agent/services/batch_planner.py`, `agent/services/batch_queue.py`, `agent/services/batch_executor.py`, `agent/api/batches.py`, `agent/api/batch_executor.py`, `dashboard/src/pages/BatchesPage.tsx`.
- The current checkout already has telemetry and output-history style reporting surfaces.
  Evidence: `agent/db/crud.py`, `dashboard/src/components/reporting/ProjectHistoryPanel.tsx`, `dashboard/src/components/reporting/RequestReportPanel.tsx`.
- The current checkout already stores scene-level duration, prompt, image prompt, video prompt, character names, chain type, and transition prompt data.
  Evidence: `agent/db/crud.py`, `agent/models/scene.py`, `agent/sdk/models/scene.py`.
- The current checkout already contains operator registry-style inputs for avatar, headwear style, camera style, scene context, language, trigger, silo, and formula.
  Evidence: `agent/api/operator.py`.

### NOT VERIFIED YET

- `docs/MODULE_STATUS.yaml` does not exist in this checkout.
- `graphify-out/` does not exist in this checkout.
- `docs/authority/working/` did not exist before this contract pack.
- The requested authority filenames `SOVEREIGN_01_MASTER_SCHEMA.yaml`, `SOVEREIGN_03_CORE_LOGIC.yaml`, `SATELLITE_04D_SCENE_CAMERA_ORCHESTRATION_FINAL.yaml`, `SATELLITE_04B_CAMERA_STYLE_COMPATIBILITY.yaml`, `SATELLITE_04_MAPPING_MATRIX.yaml`, and `SATELLITE_03_VISUAL_DECK.yaml` are not present in source control in this checkout.
- `MASTER_IGNITION_TEMPLATE.yaml` and `SCRIPT_REGISTRY_UNIFIED.yaml` are referenced by `agent/api/operator.py`, but their physical files are not present in this repo. They appear to come from an external operator pack path.
- `OPERATOR_PACK_DIR` points to `Path.home() / "Desktop" / "The Real Avengers Bosmax - Copy"` by default, which is outside this repo.
  Evidence: `agent/config.py`.
- Native in-repo `TEXT_TO_VIDEO` queue wiring is not proven. Existing repo evidence says T2V UI exists, but native queue support remains not wired.
  Evidence: `dashboard/src/components/operator/OperatorManual.tsx`.
- Exact existing `ProductKnowledge` and `ProductCopyCore` classes or files are not proven by those literal names in this checkout.
- Exact wardrobe registry surfaces are not proven in this checkout.
- Exact Google Flow multi-block continuation automation, per-block composer-state detection, and extend/insert button handling are not proven in this checkout.

### ASSUMPTIONS

- The user intentionally wants this contract written for `_ref_flowkit`, not the BOSMAX SaaS repo named in the original request.
- External operator-pack assets may contain additional authority registries beyond what is visible in source control.
- Existing runtime and UI naming in this checkout can be mapped to BOSMAX contract language without changing code.
- Some requested BOSMAX truth planes may exist in another repository or external pack, but they cannot be treated as repo fact here.

### RECOMMENDATIONS

- Treat this contract as a bridge artifact between current `_ref_flowkit` surfaces and a future governed BOSMAX Prompt Production OS.
- Keep all forward-looking schema, orchestration, and temporal-extension material explicitly marked `PROPOSED`, `NOT VERIFIED`, or `LATER IMPLEMENTATION ONLY`.
- Reconcile this contract against the external operator-pack files before any runtime work begins.
- Do not interpret this contract as authorization to build orchestration, migrations, or registry writes.

## 3. Executive Thesis

BOSMAX should evolve from manual prompt injection into a governed Prompt Production OS:

`Product / Registered Asset / Governed Registry`
`-> Source Route Resolver`
`-> Prompt Planning Engine`
`-> Prompt Block Compiler`
`-> Destination Mode Adapter`
`-> Optional Google Flow Execution Orchestrator`
`-> Batch Queue / Output History`

In the current checkout, the front-end mode surfaces, product intelligence, batch planning, and telemetry foundations already exist. The missing layer is not raw UI presence. The missing layer is a governed, fail-closed prompt planning contract that unifies product-driven and registry-driven prompt production across `TEXT_TO_VIDEO`, `FRAMES`, `INGREDIENTS`, and `IMAGE`, then stages Google Flow execution only after offline planning is proven.

## 4. Source Routes

### `PRODUCT_DRIVEN_AUTO`

- Backward formula: `Product -> Product Intelligence -> Character / Scene / Handling / Copy -> Prompt`.
- Repo-grounded inputs already visible in the product layer:
  - `category`
  - `subcategory`
  - `type`
  - `product_type`
  - `product_scale`
  - `copywriting_angle`
  - `scene_context`
  - `camera_style`
  - `camera_behavior`
  - `section_5_product_physics_prompt`
- Source truth should come from verified product rows plus verified mapping and physics fields, not free-text hallucination.

### `REGISTRY_DRIVEN_MANUAL_ASSISTED`

- Forward formula: `Selected registry assets -> legality / mapping validation -> prompt compiler`.
- Repo-grounded manual inputs already visible:
  - product
  - avatar
  - headwear style
  - camera style
  - scene context
  - language
  - silo
  - trigger
  - formula
- This route should compile from governed selections and validated tuples, not from unchecked creative text alone.

## 5. Destination Modes

### `TEXT_TO_VIDEO`

- VERIFIED FROM REPO: T2V UI surface exists.
- NOT VERIFIED YET: native queue wiring for direct T2V execution.

### `FRAMES`

- VERIFIED FROM REPO: start-frame and optional end-frame workflow exists.
- VERIFIED FROM REPO: Frames maps to a repo-wired video lane.

### `INGREDIENTS`

- VERIFIED FROM REPO: subject, scene, and style asset workflow exists.
- VERIFIED FROM REPO: Ingredients maps to a repo-wired video lane.

### `IMAGE`

- VERIFIED FROM REPO: subject, scene, and style asset workflow exists for image generation.

## 6. Asset Roles

The governed prompt planner should define these asset roles:

- `SUBJECT_CHARACTER`
- `PRODUCT`
- `SCENE`
- `STYLE`
- `START_FRAME`
- `END_FRAME`

Repo-fit mapping:

- `SUBJECT_CHARACTER`
  - VERIFIED FROM REPO for `subjectAsset` and character/media concepts.
- `PRODUCT`
  - VERIFIED FROM REPO for product row, product image, and product media concepts.
- `SCENE`
  - VERIFIED FROM REPO for `sceneAsset` and `scene_context`.
- `STYLE`
  - VERIFIED FROM REPO for `styleAsset`.
- `START_FRAME`
  - VERIFIED FROM REPO for `startAsset`.
- `END_FRAME`
  - VERIFIED FROM REPO for `endAsset`.

Canonical cross-mode use of all six roles in one unified planning schema is PROPOSED / NOT VERIFIED.

## 7. Product-Driven Auto Generator

### Objective

Use a FastMoss or registered product row as the entry point for prompt production.

### Governing flow

1. Pick up a verified product row from current product storage.
2. Resolve product mapping truth:
   - category
   - subcategory
   - type
   - product type
   - silo
   - trigger
   - formula
   - copywriting angle
3. Resolve product image truth and asset readiness.
4. Resolve product physics truth:
   - product scale
   - grip logic
   - handling notes
   - unsafe handling rules
   - section 5 handling prompt
5. Infer compatible character pattern, scene pattern, and copy angle from verified truth.
6. Compile mode-specific prompt outputs.

### Verified repo fit

- FastMoss-backed product resolution is already part of the repo vocabulary.
- Product analyzer equivalents already exist through mapping, intelligence, preflight, and physics services.
- Product image readiness logic already exists.
- Product scale and handling logic already exist.
- Scene context, camera style, and camera behavior fields already exist on product rows.

### Inference boundaries

- Character inference from product truth is PARTIALLY VERIFIED. The repo has avatar/operator concepts, but automatic population of ethnicity, gender, age band, or full character persona from product truth is not proven as current runtime behavior.
- Scene inference from product truth is PARTIALLY VERIFIED. Scene-context fields exist, but the exact auto-generator logic requested here is not proven end to end.
- Copy angle inference is PARTIALLY VERIFIED. `copywriting_angle`, `trigger_id`, `formula`, and silo fields exist, but a unified dual-route planner is not yet proven.

### Perfume example

Example only. Do not treat as current implementation fact.

- Product type: fragrance or body spray.
- Verified product truth may yield:
  - handheld rigid product class
  - small-scale product handling
  - camera-safe grip logic
  - likely scene context
  - likely camera style and copy route
- Proposed planner output may suggest:
  - a character profile
  - a scene such as car interior UGC
  - action such as holding, spraying, or showing the label
  - an image prompt
  - a 9-section video prompt

Ethnicity, exact wardrobe, exact age range, and exact scene specifics remain NOT VERIFIED unless explicitly sourced from governed registries or operator input.

## 8. Registry-Driven Manual/Assisted Generator

### Objective

Allow the operator to assemble prompts from governed dropdowns, validated tuples, and assisted defaults.

### Expected manual flow

1. Select product.
2. Select character or avatar.
3. Select wardrobe or headwear.
4. Select scene context.
5. Select camera style.
6. Select camera behavior.
7. Select product handling logic or allow it to resolve from product physics.
8. Select copywriting formula.
9. Select dialogue language.
10. Select platform.
11. Select engine.
12. Select destination mode.
13. Select duration.
14. Review suggestions and validation report.
15. Compile prompt.

### Repo-grounded current inputs

- VERIFIED FROM REPO:
  - product selection
  - avatar selection
  - headwear style selection
  - camera style selection
  - scene context selection
  - formula selection
  - language defaults
- PARTIALLY VERIFIED:
  - engine and duration exist in various UI and batch surfaces, but not yet as one canonical dual-route planner form.
- NOT VERIFIED YET:
  - wardrobe registry
  - canonical preview-only value separation
  - one unified legality validator for all manual tuple combinations

### Canonical vs preview-only rule

- Canonical values should come from governed registries or verified database truth.
- Preview-only suggestions should be visibly labeled as non-canonical until saved through an approved workflow.
- AI suggestions must never overwrite canonical registry truth automatically.

This rule is REQUIRED by contract. Current full implementation is NOT VERIFIED.

## 9. Text to Video Mode

### Contract position

- No image is required by definition.
- Prompt must explicitly describe:
  - character
  - product
  - scene
  - action
  - camera
  - dialogue or narration
- Product detail risk is high because text-only prompts can easily invent unsupported product truth.
- Unknown product dimensions, material response, and handling properties must be labeled `NOT VERIFIED` unless verified from product truth.
- This mode is useful when no product or character asset exists, but it carries the highest claim-drift risk.

### Repo fit

- VERIFIED FROM REPO: T2V prompt UI exists.
- VERIFIED FROM REPO: operator manual explicitly says direct T2V queue is not wired.
- Therefore this contract treats T2V prompt planning as valid, but T2V execution orchestration remains partially unverified.

## 10. Frames Mode

### Contract position

- Uses start and end frame or image-reference workflow.
- Prompt elaborates the uploaded visual source rather than replacing it.
- Valid cases include:
  - product-only frame plus imagined character continuation
  - character-holding-product frame continuation
  - start frame only
  - start plus optional end frame
- The prompt must not contradict the uploaded visual source.

### Repo fit

- VERIFIED FROM REPO: `F2VModule` exposes `startAsset` and optional `endAsset`.
- VERIFIED FROM REPO: operator manual documents Frames as a wired lane.

## 11. Ingredients Mode

### Contract position

- Uses subject image, product image, scene image, and style image as applicable.
- Example target pattern:
  - passport-style character image
  - product image
  - car interior or other scene reference
  - style reference
- This is the preferred high-consistency production mode when high visual continuity matters.
- Prompt must describe how the assets combine rather than competing with them.

### Repo fit

- VERIFIED FROM REPO: `I2VModule` exposes `subjectAsset`, `sceneAsset`, and `styleAsset`.
- VERIFIED FROM REPO: Ingredients is documented as a repo-wired lane.
- NOT VERIFIED YET: product image is not exposed as a first-class dedicated slot in the current `I2VModule` UI by that exact name.

## 12. Image Mode

### Contract position

Use image generation as upstream asset creation for later video work:

- create character asset
- create character holding product
- create product lifestyle image
- combine character image plus product image
- create scene or style reference

### Repo fit

- VERIFIED FROM REPO: `IMGModule` already accepts subject, scene, and style assets plus prompt text.
- NOT VERIFIED YET: a dedicated governed image planner that explicitly distinguishes character-asset creation, product-holding composition, and scene-reference generation as separate planning intents.

## 13. Temporal Extension Model

### Contract rule

Long video is not one monolithic prompt. It is a sequence of prompt blocks.

- `8s = 1 block`
- `16s = 2 blocks`
- `24s = 3 blocks`
- `32s = 4 blocks`

Engine-specific override is required where applicable.

Continuation prompt pattern should follow:

`From the last frame, the same character continues...`

### Repo status

- PROPOSED / NOT VERIFIED as current runtime behavior.
- The repo already stores scene duration and chaining fields, but a formal multi-block temporal planner is not yet proven.

## 14. Extend vs Insert / Jump-To

### `EXTEND_CONTINUITY`

- same character
- same scene or logically continuous scene
- same product
- same story thread

### `INSERT_JUMP_TO`

- deliberate cutaway
- product close-up
- CTA packshot
- angle switch
- new image insertion

Every block must define:

- `flow_action`
- `transition_intent`

This is a REQUIRED planning rule and a PROPOSED implementation surface.

## 15. Prompt Block Plan Schema

### PROPOSED / NOT VERIFIED

```json
{
  "content_id": "string",
  "source_route": "PRODUCT_DRIVEN_AUTO | REGISTRY_DRIVEN_MANUAL_ASSISTED",
  "destination_mode": "TEXT_TO_VIDEO | FRAMES | INGREDIENTS | IMAGE",
  "target_duration_seconds": 8,
  "block_duration_seconds": 8,
  "block_count": 1,
  "extension_strategy": "EXTEND_CONTINUITY | INSERT_JUMP_TO",
  "blocks": [
    {
      "block_index": 0,
      "flow_action": "INITIAL | EXTEND | INSERT",
      "depends_on_block_index": null,
      "prompt_role": "PRIMARY | CONTINUATION | INSERTION | CTA",
      "prompt_text": "string",
      "dialogue_text": "string",
      "validation_status": "PENDING | PASS | FAIL | NEEDS_REVIEW",
      "execution_status": "PLANNED | QUEUED | RUNNING | COMPLETED | FAILED | SKIPPED"
    }
  ]
}
```

This object is planning-only. It does not assert that these fields already exist in the database or API.

## 16. Google Flow Execution Orchestration

### LATER IMPLEMENTATION ONLY

Do not build until offline prompt planning is proven.

### Proposed state machine

`QUEUED`
`-> PREPARE_ASSETS`
`-> INJECT_INITIAL_PROMPT`
`-> GENERATE_BLOCK_1`
`-> WAIT_RENDER_COMPLETE`
`-> SELECT_EXTEND_OR_INSERT`
`-> INJECT_NEXT_BLOCK_PROMPT`
`-> GENERATE_NEXT_BLOCK`
`-> WAIT_RENDER_COMPLETE`
`-> REPEAT_UNTIL_TARGET_DURATION`
`-> SAVE_OUTPUT_REFERENCE`
`-> COMPLETE_OR_NEXT_BATCH_ITEM`

### Codex verification backlog

- composer state detection
- prompt injection reliability
- image upload or selection reliability
- render completion detection
- correct generated clip selection
- Extend button detection
- Insert button detection
- failure recovery
- per-block logs

### Repo fit

- VERIFIED FROM REPO: batch, telemetry, and smoke-execution surfaces exist.
- NOT VERIFIED YET: full per-block continuation orchestration and extend/insert loop.

## 17. Batch Production Model

### Contract rule

- batch size counts content units
- execution units expand by duration blocks
- formula:
  - `execution_units = content_count * block_count`

Examples:

- `10 x 8s = 10 actions`
- `10 x 16s = 20 actions`
- `10 x 24s = 30 actions`
- `10 x 32s = 40 actions`

Batch should track:

- current block index
- retry count
- status
- output reference
- resume point from last successful block

### Repo fit

- VERIFIED FROM REPO: batch draft, queue, events, and execution surfaces exist.
- NOT VERIFIED YET: block-aware temporal batch expansion and per-block resume semantics.

## 18. Technical Architecture

Required layers:

1. `Source Intelligence`
2. `Asset Registry / Library`
3. `Prompt Route Resolver`
4. `Prompt Planning Engine`
5. `Prompt Compiler Core`
6. `Destination Adapters`
7. `Flow Execution Orchestrator`
8. `Batch Queue Manager`

Repo fit:

- `Source Intelligence`
  - PARTIALLY VERIFIED through mapping, intelligence, preflight, and physics services.
- `Asset Registry / Library`
  - PARTIALLY VERIFIED through product, character, and uploaded asset flows.
- `Prompt Route Resolver`
  - PARTIALLY VERIFIED across mode surfaces and product mapping, but not yet formalized as one planner.
- `Prompt Planning Engine`
  - NOT VERIFIED as a unified governed engine.
- `Prompt Compiler Core`
  - PARTIALLY VERIFIED through 9-section contract artifacts.
- `Destination Adapters`
  - PARTIALLY VERIFIED through mode-specific UI and request lanes.
- `Flow Execution Orchestrator`
  - PARTIALLY VERIFIED through current extension/manual/queue surfaces.
- `Batch Queue Manager`
  - VERIFIED through batch planning and queue services.

## 19. Proposed Data Model

### PROPOSED / NOT VERIFIED

The following names are recommended planning entities only:

- `PromptJob`
- `PromptBlock`
- `AssetBinding`

Possible intent:

- `PromptJob`
  - owns source route, destination mode, target duration, and top-level validation state
- `PromptBlock`
  - owns per-block prompt text, block order, continuity metadata, and execution metadata
- `AssetBinding`
  - owns canonical asset-role binding and provenance

Do not interpret this section as a migration instruction.

## 20. Validation Requirements

The governed planner must validate:

- source route declared
- destination mode declared
- required asset roles present or marked missing
- product truth present or `NOT VERIFIED`
- registry selections legal together
- product handling matches scale class where known
- 9-section output complete when required
- prompt blocks match target duration
- continuation blocks have continuity intent
- no internal ID leakage
- dialogue language correct
- claims stay inside verified product truth

## 21. Fail-Closed Rules

Generation must fail closed when:

- required canonical truth missing
- illegal visual tuple selected
- duration cannot be represented by engine rules
- product claim exceeds verified knowledge
- required asset missing and no fallback allowed
- 9-section incomplete
- internal technical markers leak

## 22. UI Strategy

Recommended operator surfaces:

- `Product-Driven Auto Generator` page
- `Registry-Driven Manual/Assisted Generator` page
- `Asset Library`
- `Product Registry`
- `Character Registry`
- `Batch Queue`
- `Output History`
- `Output Preview` with block plan and validation report

Repo fit:

- VERIFIED FROM REPO:
  - operator workspaces
  - product surfaces
  - batch page
  - history and request reporting surfaces
- NOT VERIFIED YET:
  - a dedicated dual-route planner page
  - a unified output preview with block-plan validation report
  - dedicated asset, product, and character registry pages under this exact naming contract

## 23. Implementation Phases

### Phase 0

Contract review only. No coding.

### Phase 1

Offline prompt planning only.

### Phase 2

Manual Google Flow validation only.

### Phase 3

Single-job Flow orchestrator.

### Phase 4

Batch queue execution with temporal block awareness.

## 24. Hard No List

Codex must not:

- implement broad coding now
- duplicate asset registry
- duplicate prompt compiler
- auto-write canonical registry truth from AI suggestions
- invent product dimensions
- invent product claims
- build DOM automation before offline prompt block planning
- build batch automation before single-job proof
- leak internal IDs into final prompt
- collapse 9-section into one monolithic prompt blob

## Existing Authority Files To Respect

The following authority surfaces must be treated carefully:

- `MASTER_IGNITION_TEMPLATE.yaml`
  - REPO-REFERENCED but external to source control in this checkout.
- `SCRIPT_REGISTRY_UNIFIED.yaml`
  - REPO-REFERENCED but external to source control in this checkout.
- `SOVEREIGN_01_MASTER_SCHEMA.yaml`
  - NOT VERIFIED in this checkout.
- `SOVEREIGN_03_CORE_LOGIC.yaml`
  - NOT VERIFIED in this checkout.
- `SATELLITE_04D_SCENE_CAMERA_ORCHESTRATION_FINAL.yaml`
  - NOT VERIFIED in this checkout.
- `SATELLITE_04B_CAMERA_STYLE_COMPATIBILITY.yaml`
  - NOT VERIFIED in this checkout.
- `SATELLITE_04_MAPPING_MATRIX.yaml`
  - NOT VERIFIED in this checkout.
- `SATELLITE_03_VISUAL_DECK.yaml`
  - NOT VERIFIED in this checkout.

This contract must not duplicate or replace those authority layers. It only defines the governance envelope for future dual-route prompt planning.

## Final Contract Status

- `status`: `DRAFT_FOR_CODEX_FORENSIC_REVIEW`
- `implementation_status`: `NO_CODING_AUTHORIZED`
- `reviewed_base_sha`: `6935930ddd6ef45cb9725d1d9805ab9435116a4f`
- `current_position`: planning contract only
