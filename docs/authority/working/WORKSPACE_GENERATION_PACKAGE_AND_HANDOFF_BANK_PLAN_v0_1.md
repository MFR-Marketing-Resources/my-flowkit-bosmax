# Workspace Generation Package And Handoff Bank Plan v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `WORKSPACE_GENERATION_PACKAGE_AND_HANDOFF_BANK_PLAN` |
| `version` | `v0.1` |
| `status` | `PLANNING_DRAFT_FOR_BOUNDED_IMPLEMENTATION` |
| `repo` | `C:\Users\USER\Desktop\_ref_flowkit` |
| `reviewed_remote` | `origin/main` |
| `baseline_sha` | `3a389c27cd9127ab66db2d7fe44d7f2cc15db2b2` |
| `related_issue` | `GitHub Issue #83` |
| `related_issue_url` | `https://github.com/farisdatosheikh/my-flowkit-bosmax/issues/83` |
| `implementation_status` | `NO_CODING_INSIDE_THIS_FILE` |

## 2. Executive Decision

- New durable domain: `workspace_generation_package`.
- Recommended operator-facing UI label: `Prompt Handoff Bank`.
- `workspace_execution_package` remains the compile-time execution snapshot, readiness gate, and lineage anchor.
- `workspace_generation_package` becomes the final operator handoff source of truth.
- Final selected F2V and I2V assets must not live only in transient React state or one-shot execution payloads.
- Manual fallback must be first-class before any future Google Flow DOM automation is authorized.

## 3. Baseline Context

### Accepted Baseline

- PR72 established the UGC prompt compiler and workspace image preview contract.
- PR74 and PR76 established the workspace layout and unified jobs surface.
- PR78 established the Creative Asset Library and I2V semantic slot resolver surfaces.
- PR80 restored FastMoss product visibility.

### Current User-Facing Problem

- The repo can load approved product packages, compile prompts, resolve I2V semantic slots, and open operator workspaces.
- The repo does not yet persist a final handoff package that stores:
  - final selected F2V or I2V assets
  - final compiled prompt text
  - operator manual fallback actions
  - future DOM payload scaffold
- This gap means prompt and asset truth can become ephemeral between "package loaded" and "execute now".

## 4. Root Architecture Gap

Creative Asset Library and I2V semantic slot resolver surfaces are necessary but insufficient. They solve selection and mapping, not durable handoff truth.

The current repo already proves the following:

- approved product package truth is available from `agent/services/approved_product_package_service.py`
- compile-time workspace package creation is available from `agent/services/workspace_execution_package_service.py`
- F2V and I2V workspace modules can prefill prompts and assets in the UI
- I2V semantic slot resolution is available from `agent/services/i2v_semantic_slot_resolver_service.py`
- creative assets are durable as library records via `agent/services/creative_asset_service.py`

The missing layer is a durable final package bank where all operator-selected handoff truth is frozen together. Without that layer:

- selected F2V start or end frames can remain ephemeral UI state
- selected I2V character, scene, and style references can remain only request-time payload decisions
- final prompt and final selected assets are not reopened as one operator package artifact
- manual fallback cannot be treated as a durable operating surface
- future DOM handoff would bind directly to unstable transient payloads instead of a stable package truth plane

## 5. Relationship To Existing Modules

### `approved_product_package_service`

- Responsibility today:
  - claim-safe and production-readiness gate
  - default product prompt package
  - default asset slot requirements
  - manual fallback checklist seed
- Planned relationship:
  - remains upstream truth gate
  - must not be overloaded with final operator-selected creative assets

### `workspace_execution_package_service`

- Responsibility today:
  - creates `workspace_execution_package`
  - compiles final prompt snapshot
  - stores prompt lineage, resolved assets, manual fallback payload, and readiness
  - merges I2V semantic slot resolver output into execution package lineage
- Planned relationship:
  - remains compile/readiness snapshot
  - should feed `workspace_generation_package`
  - should not become the mutable home for final operator handoff state

### `ugc_video_prompt_compiler_service`

- Responsibility today:
  - builds final compiled prompt blocks
  - governs F2V timing, shot count, language policy, continuation, camera style, and creator continuity
- Planned relationship:
  - remains the F2V prompt engine
  - remains the baseline compiler layer reused by I2V handoff prompt building

### `i2v_semantic_slot_resolver_service`

- Responsibility today:
  - maps semantic roles to engine slots
  - validates selected creative assets
  - returns resolved assets, warnings, blockers, and compiler context summary
- Planned relationship:
  - remains the semantic role mapper
  - feeds `workspace_generation_package.resolver_output_json`
  - must not be treated as the package bank itself

### `creative_asset_service`

- Responsibility today:
  - persists creative assets
  - validates selectable assets for semantic role, mode, and engine slot eligibility
  - builds resolved workspace asset payloads
- Planned relationship:
  - remains the creative asset truth store
  - selected creative asset references are copied into the handoff package as chosen references, not elevated into product truth

### Product Image Preview / Download

- Responsibility today:
  - approved product package defaults use `/api/products/{product_id}/image`
  - product image can seed F2V start frame and I2V subject/product reference
- Planned relationship:
  - remains upstream source
  - handoff package stores the chosen image references and upload order

### Workspace Jobs

- Responsibility today:
  - request telemetry and jobs surfaces show execution status and failure reporting
- Planned relationship:
  - jobs remain execution reporting
  - jobs are not the package bank
  - future telemetry should reference `workspace_generation_package_id`

### `ApprovedPackagesPage`

- Responsibility today:
  - exposes approved prompt packages, default asset slots, manual fallback checklist, and workspace package history
- Planned relationship:
  - remains truth and readiness gateway
  - links into the Prompt Handoff Bank
  - does not replace the handoff bank detail surface

### `OperatorPage`

- Responsibility today:
  - loads approved workspace package
  - exposes F2V prompt compiler controls
  - launches execution
- Planned relationship:
  - becomes the package composition and save surface
  - gains `Generate / Save Package`
  - gains `Open Saved Package`
  - does not require DOM execution to persist or review a package

### `F2VModule`

- Responsibility today:
  - preloads prompt and start/end frame UI state
  - allows prompt override and asset upload
- Planned relationship:
  - becomes the F2V package editing surface
  - its selected asset state must persist into `workspace_generation_package`

### `I2VModule`

- Responsibility today:
  - preloads prompt and subject/scene/style UI state
  - allows prompt override and asset upload
- Planned relationship:
  - becomes the I2V package editing surface
  - selected semantic assets and final prompt must persist into `workspace_generation_package`

## 6. Storage Model

### New Durable Table / Model

`workspace_generation_package`

### Recommended Fields

- `workspace_generation_package_id`
- `mode`
- `product_id`
- `product_name_snapshot`
- `source_lane`
- `prompt_package_snapshot_id`
- `workspace_execution_package_id`
- `generation_mode`
- `final_prompt_text`
- `prompt_blocks_json`
- `selected_assets_json`
- `resolved_engine_slots_json`
- `resolver_output_json`
- `image_assets_json`
- `manual_handoff_json`
- `dom_handoff_payload_json`
- `blockers_json`
- `warnings_json`
- `status`
- `created_at`
- `updated_at`

### Status Values

- `DRAFT`
- `READY_MANUAL`
- `READY_DOM_STAGED`
- `BLOCKED`

### Storage Rules

- `workspace_generation_package` is the durable handoff artifact.
- `workspace_execution_package_id` remains the upstream compile snapshot reference.
- `prompt_package_snapshot_id` remains the upstream approved package reference.
- `selected_assets_json` stores what the operator actually selected.
- `resolved_engine_slots_json` stores what the system will actually hand off to the engine.
- `manual_handoff_json` stores manual fallback steps and URLs.
- `dom_handoff_payload_json` stores a future-ready scaffold only; it does not authorize execution.

## 7. F2V Package Contract

### Inputs

- `product_id`
- `workspace_execution_package_id`
- `generation_mode`
- duration blocks
- language
- camera style
- character presence
- creator persona
- `start_frame`
- optional `end_frame`
- operator notes

### Outputs

- final compiled F2V prompt
- prompt blocks
- continuation lineage
- selected start frame asset
- selected end frame asset when supplied
- manual handoff payload
- future DOM payload scaffold

### Rules

- Product image auto-seeds `Start Frame`.
- Operator may replace `Start Frame`.
- `End Frame` remains optional.
- Package revision persists the exact selected start and end assets.
- Prompt fingerprint and lineage IDs must remain visible in the package.
- Upload order is fixed as `Start Frame -> End Frame`.

## 8. I2V Package Contract

### Inputs

- `product_id`
- `workspace_execution_package_id`
- `product_reference`
- character or creator asset
- `scene_context`
- optional `style` or `mood`
- recipe or resolver strategy
- prompt settings

### Outputs

- final blended I2V prompt
- semantic selections
- resolved `Subject / Scene / Style`
- resolver metadata
- manual handoff payload
- future DOM payload scaffold

### Rules

- Product Reference auto-loads from the selected product package.
- User selects Character and Scene Context from Creative Asset Library.
- Optional Style or Mood comes from Creative Asset Library.
- Resolver maps semantic roles to engine slots.
- Package stores final selected assets, slot mapping, warnings, blockers, and final prompt.
- Upload order is fixed as `Subject -> Scene -> Style`.

## 9. Final Prompt Generation Strategy

### F2V

- Reuse PR72 UGC compiler directly.
- F2V package generation should call the existing compiler pipeline and persist the resulting final prompt blocks unchanged.

### I2V

- Add a thin I2V handoff prompt builder layered on the existing compiler and resolver surfaces.
- The thin builder should inject:
  - product knowledge
  - approved product package truth
  - semantic resolver output
  - semantic asset summaries
  - selected recipe
  - engine slot mapping
- This layer should not become a second full compiler stack.
- This layer should not rewrite the existing UGC compiler.

## 10. Manual Handoff Model

Each durable package must expose:

- `Copy Final Prompt`
- `Open Image`
- `Download Image`
- upload order instructions
- warnings
- blockers
- prompt fingerprint
- lineage IDs

### Upload Order

- F2V: `Start Frame -> End Frame`
- I2V: `Subject -> Scene -> Style`

### Manual Fallback Principle

Even when Google Flow DOM automation is unavailable, the package must still be usable as a complete operator handoff artifact.

## 11. Future DOM Payload Model

The stored scaffold should use the following shape:

```json
{
  "mode": "F2V|I2V|T2V|IMG",
  "lineage": {
    "product_id": "...",
    "prompt_package_snapshot_id": "...",
    "workspace_execution_package_id": "...",
    "workspace_generation_package_id": "...",
    "prompt_fingerprint": "...",
    "asset_fingerprints": []
  },
  "prompt": {
    "final_text": "...",
    "blocks": [],
    "generation_mode": "SINGLE|EXTEND"
  },
  "assets": {
    "start_frame": null,
    "end_frame": null,
    "subject": null,
    "scene": null,
    "style": null,
    "product_reference": null
  },
  "settings": {},
  "semantic_resolution": {},
  "manual_handoff": {
    "upload_order": []
  },
  "readiness": {
    "manual_handoff_ready": true,
    "dom_handoff_ready": false,
    "blockers": [],
    "warnings": []
  }
}
```

### DOM Readiness Rule

- `dom_handoff_ready` must remain `false` in the first implementation wave.
- Storing the scaffold does not authorize DOM execution.
- DOM handoff is blocked until a later approved implementation wave.

## 12. Frontend UX Model

### Recommended Route

Canonical concept route:

- `/workspace/generation-packages`

Repo-consistent UI route if flat routing is preserved:

- `/generation-packages`

API recommendation:

- `/api/workspace/generation-packages`

### Required UI Capabilities

- saved package list or table
- filter by mode
- filter by status
- filter by product
- package detail panel
- copy prompt action
- open image action
- download image action
- upload order panel
- blockers and warnings panel
- future `Send to Google Flow` button present but disabled until approved DOM readiness exists

### OperatorPage Requirements

- `Generate / Save Package` for F2V
- `Generate / Save Package` for I2V
- open saved package detail from the operator surface
- no DOM execution required to review saved package truth

## 13. First Implementation Wave

Smallest bounded coding wave:

1. add `workspace_generation_package` table, model, service, and API
2. create F2V package save path
3. create I2V package save path
4. create package bank list and detail page
5. add manual copy, open, and download handoff actions
6. thread `workspace_generation_package_id` into future request telemetry
7. do not touch Google Flow DOM

## 14. Out Of Scope

Explicitly excluded from this plan and first implementation wave:

- Google Flow DOM automation
- Chrome extension runtime
- Control Tower or RBAC
- claim-safe gate changes
- production approval gate changes
- Creative Asset Library rewrite
- provider-side generation changes
- UGC prompt compiler rewrite
- full T2V or IMG package-bank expansion unless a narrow safe extension is trivially compatible

## 15. Acceptance Criteria

- F2V can create a complete durable package with final prompt and selected image assets.
- I2V can create a complete durable package with selected Subject, Scene, and Style assets plus final blended prompt.
- Package can be reopened after creation.
- Copy prompt action works from saved package detail.
- Open and download actions work for each image referenced by the package.
- Manual upload order is visible.
- DOM payload scaffold is stored.
- DOM readiness remains false.
- Tests are defined before implementation is declared complete.

## 16. Validation Matrix

### Service Tests

- `tests/unit/test_workspace_generation_package_service.py`
- F2V package creation path
- I2V package creation path
- manual handoff payload generation
- DOM scaffold generation

### API Tests

- `tests/api/test_workspace_generation_package_api.py`
- create package
- list packages
- get package detail
- filter by mode and status

### UI Tests

- `tests/ui/test_workspace_generation_package_ui_contract.py`
- package list and detail rendering
- copy prompt affordance
- image open and download affordances
- upload-order display
- disabled future DOM handoff button

### Contract-Specific Tests

- F2V selected start and end frame persistence tests
- I2V selected semantic asset persistence tests
- lineage propagation tests
- blockers and warnings persistence tests

### Governance / Build Checks

- `git status --short`
- `git diff --stat`
- markdown validation if available
- Mandor and Biome checks only when the implementation wave touches governed runtime files

## 17. Delivery Report Format For Future Implementation PR

The future bounded implementation PR report should include:

- `STATUS`
- `ISSUE_AUTHORITY`
- `BASELINE`
- `IMPLEMENTATION_SCOPE`
- `NEW_DOMAIN`
- `STORAGE_PROOF`
- `F2V_PACKAGE_PROOF`
- `I2V_PACKAGE_PROOF`
- `MANUAL_HANDOFF_PROOF`
- `DOM_SCAFFOLD_PROOF`
- `VALIDATION_RESULTS`
- `SAFETY_PROOF`
- `CHANGED_FILES`
- `COMMIT_SHA`
- `PUSH_TARGET`
- `PUSH_RESULT`
- `NEXT_DECISION`

## 18. Final Planning Decision

- Keep `workspace_execution_package` narrow and stable.
- Add `workspace_generation_package` as the durable final handoff truth plane.
- Ship manual fallback before DOM handoff.
- Treat Prompt Handoff Bank as a first-class workspace surface, not a hidden side effect of execute-now flows.
