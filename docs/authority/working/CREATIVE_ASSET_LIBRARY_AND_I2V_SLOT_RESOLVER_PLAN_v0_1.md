# CREATIVE ASSET LIBRARY AND I2V SLOT RESOLVER PLAN v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `CREATIVE_ASSET_LIBRARY_AND_I2V_SLOT_RESOLVER_PLAN` |
| `version` | `v0.1` |
| `status` | `APPROVED_FOR_IMPLEMENTATION_PLANNING` |
| `implementation_status` | `NO_CODING_INSIDE_THIS_FILE` |
| `repo` | `farisdatosheikh/my-flowkit-bosmax` |
| `baseline_main_sha` | `be39b4257dcdba9dbb2786df4a3d515a62b28d25` |
| `decision_source` | `User Ingredients/I2V discussion + Issue #77 + Codex architecture handshake` |
| `related_issue` | `#77 Discussion authority: Creative Asset Library and I2V semantic slot resolver` |
| `related_modules` | `Workspace I2V / Asset Registry / Creative Library / Workspace Package Bridge` |

## 2. Executive Decision

The next architecture wave is:

```text
CREATIVE_ASSET_LIBRARY_AND_I2V_SLOT_RESOLVER
```

Decision:

```text
Hybrid architecture.

Keep Asset Registry as the conservative read-only provenance/audit surface.
Create a separate persisted Creative Library domain for operator-facing reusable creative assets.
Place an I2V Semantic Slot Resolver between Creative Library assets and engine-facing workspace slots.
```

This plan exists because the Ingredients/I2V workflow cannot remain dependent on manual upload into `Subject`, `Scene`, and `Style` slots. Those are engine slot labels, not durable business semantics.

## 3. Current Verified Project State

Latest smoked main reported:

```text
be39b4257dcdba9dbb2786df4a3d515a62b28d25
```

Merged baseline:

- PR72: UGC prompt compiler + image preview contract.
- PR74: unified Workspace Jobs page and removed embedded jobs panels.
- PR76: normalized workspace authoring layout and scroll ownership.

Current workspace baseline after layout cleanup:

- T2V/F2V/I2V/IMG authoring pages are clean authoring surfaces.
- `/workspace/jobs` is the unified jobs/progress page.
- PR72 manual browser smoke remains a technical verification step before Google Flow DOM handoff.

## 4. Current User Problem

Ingredients/I2V currently exposes three image upload slots:

```text
Subject
Scene
Style
```

For automation, product selection can resolve the product image into one slot. The remaining references typically need:

```text
character / creator image
scene context / environment image
optional style / mood image
```

Expected smart workflow:

```text
User selects product
-> system resolves product reference image
-> user selects character/creator from reusable library
-> user selects scene context/environment from reusable library
-> user optionally selects style/mood reference
-> system maps semantic roles into engine slots
-> system generates final blended I2V prompt
```

The system must not force users to upload the same character and scene images manually for every Ingredients job.

## 5. Root Architecture Gap

`Subject`, `Scene`, and `Style` are transport/engine labels.

They must not become permanent business logic.

Wrong architecture:

```text
subject = product
scene = character
style = environment
```

Correct architecture:

```text
semantic role first
engine slot second
```

Stable semantic roles:

```text
product_reference
character_reference
scene_context_reference
style_reference
composite_frame_reference
```

Then a resolver maps those semantic roles into engine-facing slots by recipe:

```text
subject / scene / style / start_frame / end_frame
```

If this separation is not enforced:

- product vs character precedence cannot be changed cleanly.
- engine-specific slot vocabulary leaks into business logic.
- F2V composite frames become one-off hacks.
- IMG-generated references cannot be reused consistently.
- future Control Tower governance would manage engine labels instead of creative intent.

## 6. Source-of-Truth Decision

### 6.1 Asset Registry Truth

`Asset Registry` remains:

```text
read-only provenance / audit / compatibility surface
```

It may expose repo-derived registries, built-ins, hints, compatibility diagnostics, and later Creative Library-backed read views.

It is not the operator-facing write surface for reusable creative assets in v1.

### 6.2 Creative Library Truth

`Creative Library` becomes the persisted operator-facing domain for reusable creative assets.

It owns:

- creative asset categories
- semantic role metadata
- lifecycle status
- file/media references
- prompt/image-generation lineage
- mode eligibility
- engine slot eligibility
- future visibility/ownership fields

### 6.3 Semantic Slot Resolver Truth

`I2V Semantic Slot Resolver` owns:

- recipe selection
- semantic role validation
- semantic role to engine slot mapping
- resolved asset output
- warnings/blockers
- workspace execution package lineage additions

### 6.4 Product Truth

Approved product package remains product/claim-safe truth.

Creative Library assets augment visual context. They do not replace product governance, product approval, image readiness, or claim-safe approval.

## 7. Creative Asset Category Model

Required v1 categories:

```text
PRODUCT_REFERENCE
CHARACTER_REFERENCE
SCENE_CONTEXT_REFERENCE
STYLE_REFERENCE
COMPOSITE_FRAME_REFERENCE
```

### PRODUCT_REFERENCE

Product-linked image or product reference asset.

Sources:

- approved product package image
- cached product image
- remote product image URL
- manually uploaded product reference
- generated product reference only where product truth is preserved

### CHARACTER_REFERENCE

Reusable creator/persona/character image.

Examples:

- Malay female UGC creator
- Malay male wellness demonstrator
- mother/home-care persona
- professional reviewer persona

### SCENE_CONTEXT_REFERENCE

Reusable environment/location image.

Examples:

- home kitchen
- bedroom vanity
- KLCC outdoor premium lifestyle scene
- bathroom counter
- pharmacy/wellness shelf

### STYLE_REFERENCE

Reusable mood/style/visual language reference.

Examples:

- soft wellness morning light
- cinematic premium skincare lighting
- TikTok raw handheld UGC look
- luxury clean e-commerce palette

### COMPOSITE_FRAME_REFERENCE

A pre-composed image intended for F2V start frame or future image-to-video bridge.

Example:

```text
same selected character holding the selected product in selected scene context
```

## 8. Creative Asset Metadata Model

Recommended persisted fields:

```text
asset_id
semantic_role
display_name
description
source_type
storage_kind
preview_url
download_url
media_id
local_file_path
remote_source_url
product_id
category
silo
product_type
allowed_modes
engine_slot_eligibility
mode_a_metadata_handoff
visual_dna_summary
character_dna
scene_context_dna
style_mood_dna
source_prompt_fingerprint
source_workspace_execution_package_id
source_prompt_package_snapshot_id
status
created_at
updated_at
```

### Status values

```text
ACTIVE
ARCHIVED
```

Optional future values:

```text
DRAFT
REVIEW_REQUIRED
REJECTED
PURGED
```

### Source types

```text
UPLOAD
GENERATED_IMAGE
PRODUCT_CACHE
REMOTE_URL
SYSTEM_SEED
```

### Storage kinds

```text
LOCAL_FILE
REMOTE_URL
MEDIA_ID
PRODUCT_IMAGE_CACHE
```

### Mode A metadata rule

`mode_a_metadata_handoff` should be stored as opaque JSON plus a small normalized summary.

Do not claim a full Sovereign/Satellite parser exists until repo implementation proves it.

## 9. I2V Semantic Slot Resolver Contract

### 9.1 Input

```json
{
  "mode": "I2V",
  "product_id": "string",
  "product_reference_asset_id": "optional string",
  "character_reference_asset_id": "optional string",
  "scene_context_reference_asset_id": "optional string",
  "style_reference_asset_id": "optional string",
  "recipe_id": "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"
}
```

### 9.2 Output

```json
{
  "mode": "I2V",
  "recipe_id": "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
  "semantic_roles": {
    "product_reference": "asset/product reference",
    "character_reference": "asset/character reference",
    "scene_context_reference": "asset/scene context reference",
    "style_reference": "asset/style reference optional"
  },
  "engine_slot_mapping": {
    "subject": "product_reference",
    "scene": "character_reference",
    "style": "scene_context_reference"
  },
  "resolved_assets": [
    {
      "slot_key": "subject",
      "semantic_role": "product_reference",
      "asset_id": "..."
    },
    {
      "slot_key": "scene",
      "semantic_role": "character_reference",
      "asset_id": "..."
    },
    {
      "slot_key": "style",
      "semantic_role": "scene_context_reference",
      "asset_id": "..."
    }
  ],
  "compiler_context_summary": "Product reference is paired with selected creator and scene context.",
  "warnings": []
}
```

### 9.3 Resolver rules

- Validate each selected asset matches the required semantic role.
- Validate selected assets are `ACTIVE`.
- Validate selected assets allow `I2V` where mode eligibility exists.
- Validate selected assets are eligible for mapped engine slot.
- Product reference may default from approved product package if no explicit product asset is selected.
- Missing required semantic roles must create explicit blockers.
- Optional style reference may be omitted depending on recipe.
- Resolver output must be written into workspace execution package lineage.

## 10. Source-Controlled I2V Recipe Config

Default v1 recipes are source-controlled first.

Do not make recipes admin-editable until Control Tower governance exists.

### 10.1 PRODUCT_HELD_BY_CHARACTER_IN_SCENE

Purpose:

```text
Product is the primary reference. Character demonstrates or holds it. Scene context defines environment.
```

Mapping:

```text
subject = product_reference
scene = character_reference
style = scene_context_reference
```

Required roles:

```text
product_reference
character_reference
scene_context_reference
```

Optional roles:

```text
style_reference
```

### 10.2 CHARACTER_FIRST_PRODUCT_DEMO

Purpose:

```text
Character is primary. Product becomes demonstration object. Scene context defines environment.
```

Mapping:

```text
subject = character_reference
scene = product_reference
style = scene_context_reference
```

Required roles:

```text
product_reference
character_reference
scene_context_reference
```

### 10.3 STYLE_MOOD_DOMINANT_PRODUCT_SPOT

Purpose:

```text
Product remains primary, scene context and style/mood dominate the visual direction.
```

Mapping:

```text
subject = product_reference
scene = scene_context_reference
style = style_reference
```

Required roles:

```text
product_reference
scene_context_reference
style_reference
```

Character may be omitted or handled by prompt compiler depending on user choice.

## 11. I2V Workspace Integration

### 11.1 Current state

`I2VModule` currently exposes three engine-facing upload slots:

```text
Subject
Scene
Style
```

The product package can resolve product image into `subject`, but `scene` and `style` remain manual upload slots.

### 11.2 Required v1 behavior

I2V page should support:

```text
selected product -> product_reference
select character from Creative Library -> character_reference
select scene context from Creative Library -> scene_context_reference
optional select style/mood from Creative Library -> style_reference
select recipe -> engine slot mapping
```

The UI may still display engine slots for transparency, but the primary controls should reflect semantic roles:

- Product Reference
- Character / Creator
- Scene Context
- Style / Mood
- Recipe

### 11.3 Workspace package behavior

Workspace execution package should receive:

- resolved engine slots
- semantic role mapping
- recipe id
- asset ids
- asset fingerprints if available
- request lineage payload update
- compiler context summary

## 12. Creative Library Page Contract

Create a new operator-facing page/module:

```text
Creative Library
```

Preferred route:

```text
/assets/creative-library
```

or repo-consistent equivalent under the `ASSETS` nav group.

### 12.1 Required v1 UI

- list assets
- filter by semantic role/category
- filter by status
- search by display name/description/product/category/silo
- detail panel
- upload new asset
- edit metadata
- archive asset
- unarchive asset if implemented in v1
- select/use in workspace where relevant

### 12.2 Required v1 asset actions

```text
create/upload
edit metadata
archive
list/detail
```

Optional v1:

```text
unarchive
```

Out of v1:

```text
purge
RBAC visibility
subscription visibility
admin-controlled default catalogs
```

## 13. F2V Composite Frame Contract

F2V composite frame flow is recognized but deferred from first implementation wave.

Future behavior:

```text
Creative Library composite frame asset -> eligible as F2V start_frame
```

F2V should eventually allow start frame source selection:

```text
approved product image default
selected COMPOSITE_FRAME_REFERENCE
manual upload
```

V1 boundary:

```text
Do not implement F2V composite frame flow in first coding wave unless explicitly authorized.
```

## 14. IMG Page Save-to-Library Contract

Image/IMG generation output is recognized but deferred from first implementation wave.

Future behavior:

```text
Image page generates character/scene/style/composite image
-> user clicks Save to Creative Library
-> system stores asset with semantic metadata and lineage
```

Required future categories:

```text
CHARACTER_REFERENCE
SCENE_CONTEXT_REFERENCE
STYLE_REFERENCE
COMPOSITE_FRAME_REFERENCE
PRODUCT_REFERENCE only when product truth is preserved
```

V1 boundary:

```text
Do not implement full IMG save-to-library in first coding wave unless explicitly authorized.
```

## 15. Relationship to UGC Prompt Compiler

Current UGC prompt compiler remains untouched in first Creative Library wave.

Future relationship:

- resolver output becomes part of workspace execution package lineage
- compiler consumes normalized semantic summaries, not raw files only
- examples consumed later:
  - selected character cues
  - scene context summary
  - style/mood summary
  - recipe id
  - slot mapping rationale

Approved product package remains product truth and claim-safe authority.

Creative Library enriches visual references only.

## 16. Relationship to Mode A / Mode B / Mode C Authority

Uploaded BOSMAX authority files establish high-level lane principles:

```text
Mode A = image generation / visual intelligence
Mode B = video generation through strict 9-section scripting
Mode C = bridge Mode A image or metadata into Mode B video generation
```

Planning implication:

- Creative Library must preserve image-generation metadata where available.
- Mode A assets should be reusable for I2V/F2V/Mode C bridge.
- Mode B prompt compiler should later consume normalized semantic summaries from those assets.
- Full parser/ingestion of all uploaded Sovereign/Satellite files is not assumed in v1.

V1 rule:

```text
Store opaque handoff payloads and normalized summaries only.
Do not claim full Mode A/B/C parser exists.
```

## 17. Control Tower Dependency

Future Control Tower owns governance for:

- who can create/edit/archive creative assets
- which roles can use which assets
- visibility by author/subscriber/team
- default characters/scenes/styles
- product and mode eligibility

Current implementation:

- do not implement RBAC
- do not implement Control Tower UI
- reserve schema room for future ownership and visibility fields
- keep v1 usable for current operator/admin workflow

## 18. Minimum Bounded Implementation Wave

First coding wave after this planning doc:

```text
CREATIVE_LIBRARY_V1_AND_I2V_SLOT_RESOLVER
```

Scope:

1. Add persisted `creative_asset` backend model/service/API.
2. Add Creative Library page/module for list/detail/upload/edit/archive.
3. Add source-controlled I2V recipe config.
4. Add I2V Semantic Slot Resolver service.
5. Extend I2V workspace only:
   - auto-fill selected product as `product_reference`
   - choose `character_reference` from Creative Library
   - choose `scene_context_reference` from Creative Library
   - choose `style_reference` from Creative Library
   - resolve to engine slots via selected recipe
   - write resolver output into workspace execution package lineage
6. Add tests and runtime proof.

## 19. Out of Scope for First Coding Wave

Do not include:

- UGC prompt compiler logic changes
- image preview backend contract changes
- Google Flow DOM
- Chrome extension runtime
- Control Tower / RBAC implementation
- full IMG save-to-library
- full F2V composite-frame flow
- broad workspace UI rewrite
- product approval/claim-safe gate changes
- full Mode A/B/C parser
- marketplace scraping
- subscription features
- purge workflow

## 20. Acceptance Criteria for First Coding Wave

### Backend

- `creative_asset` persistence exists.
- Creative asset service/API supports create/list/detail/update/archive.
- Required semantic roles are supported.
- I2V recipe config exists and is source-controlled.
- I2V resolver validates selected assets.
- I2V resolver outputs semantic roles + engine slot mapping + resolved assets.
- Workspace execution package lineage stores resolver output.

### Frontend

- Creative Library page exists under Assets or repo-consistent route.
- User can upload asset and assign semantic role.
- User can edit metadata.
- User can archive asset.
- I2V page exposes semantic controls:
  - Product Reference
  - Character / Creator
  - Scene Context
  - Style / Mood
  - Recipe
- I2V page still shows resolved engine slots for transparency.
- I2V can run using product + selected creative assets.

### Safety/Governance

- Archived assets cannot be selected for new jobs.
- Asset semantic role mismatch blocks resolver.
- Product truth still comes from approved package/product selection.
- No claim that full Mode A/B/C parser exists.
- No Control Tower/RBAC implementation in this wave.

## 21. Validation Matrix

Suggested tests:

```text
pytest tests/unit/test_creative_asset_service.py -q
pytest tests/api/test_creative_asset_api.py -q
pytest tests/unit/test_i2v_semantic_slot_resolver_service.py -q
pytest tests/api/test_i2v_semantic_slot_resolver_api.py -q
pytest tests/ui/test_creative_library_page_ui_contract.py -q
pytest tests/ui/test_i2v_creative_asset_resolver_ui_contract.py -q
pytest tests/ui/test_workspace_package_bridge_ui_contract.py -q
pytest tests/ui/test_workspace_authoring_layout_ui_contract.py -q
```

Build:

```text
cd dashboard
npm run build
```

Governance:

```text
npx tsx scripts/mandor-check.ts
npx @biomejs/biome check <changed frontend/ts files>
npx --yes --package dependency-cruiser depcruise dashboard/src --config .dependency-cruiser.cjs --output-type err
```

## 22. Runtime Proof Required

Use I2V/Ingredients workspace.

Prove:

1. Creative Library page exists.
2. Create/upload a `CHARACTER_REFERENCE` asset.
3. Create/upload a `SCENE_CONTEXT_REFERENCE` asset.
4. Optional: create/upload a `STYLE_REFERENCE` asset.
5. Open I2V workspace.
6. Select product.
7. Product image auto-resolves as `product_reference`.
8. Select character from Creative Library.
9. Select scene context from Creative Library.
10. Select recipe `PRODUCT_HELD_BY_CHARACTER_IN_SCENE`.
11. Resolver maps semantic roles to engine slots.
12. `Subject`, `Scene`, `Style` show resolved engine assets.
13. Prompt/lineage includes resolver output.
14. Archived assets cannot be selected.

## 23. Required Final Delivery Format for Implementation PR

Future implementation PR must report:

```text
# STATUS
PASS_PR_OPENED / BLOCKED

# BASELINE
main SHA

# PLANNING_AUTHORITY
docs/authority/working/CREATIVE_ASSET_LIBRARY_AND_I2V_SLOT_RESOLVER_PLAN_v0_1.md
planning commit SHA

# IMPLEMENTATION_SUMMARY
what was built

# CREATIVE_LIBRARY_PROOF
page/API/service and asset lifecycle proof

# I2V_RESOLVER_PROOF
recipe, semantic roles, engine slot mapping proof

# I2V_UI_PROOF
product/character/scene/style selection and resolved slot proof

# LINEAGE_PROOF
workspace execution package carries resolver output

# SAFETY_PROOF
archive/mismatch/product-truth boundaries

# VALIDATION_RESULTS
tests/build/governance

# REPO_HYGIENE_PROOF
no runtime artifacts

# CHANGED_FILES
exact files

# PR
actual PR URL

# HEAD_SHA
remote branch head SHA

# MERGE_READINESS
MERGE_READY / NOT_MERGE_READY with exact reason
```

## 24. Required Follow-Up Planning

After v1 implementation is merged and smoked, revisit:

1. F2V composite frame library flow.
2. IMG generated asset save-to-library flow.
3. UGC prompt compiler consumption of semantic summaries.
4. Control Tower/RBAC governance for Creative Library.
5. Mode A/B/C authority pack ingestion and parser design.

## 25. Final Decision

This plan authorizes the next bounded implementation wave:

```text
CREATIVE_LIBRARY_V1_AND_I2V_SLOT_RESOLVER
```

Do not begin coding until this planning document is committed to main and referenced as the implementation authority.
