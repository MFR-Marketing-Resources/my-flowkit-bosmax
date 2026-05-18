# UGC VIDEO PROMPT COMPILER AND WORKSPACE IMAGE PREVIEW PLAN v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `UGC_VIDEO_PROMPT_COMPILER_AND_WORKSPACE_IMAGE_PREVIEW_PLAN` |
| `version` | `v0.1` |
| `status` | `APPROVED_FOR_IMPLEMENTATION_PLANNING` |
| `implementation_status` | `NO_IMPLEMENTATION_INSIDE_THIS_FILE` |
| `repo` | `farisdatosheikh/my-flowkit-bosmax` |
| `baseline_main_sha` | `8f3160c337bff492d7c32d49dd834986f90ce754` |
| `decision_source` | `User approval + Codex forensic report` |

## 2. Executive Decision

The next workspace production wave is:

```text
UGC_VIDEO_PROMPT_COMPILER_AND_WORKSPACE_IMAGE_PREVIEW
```

This wave is authorized as a bounded implementation lane with two
subwaves:

1. `WORKSPACE_IMAGE_PREVIEW_CONTRACT_HOTFIX`
1. `UGC_VIDEO_PROMPT_COMPILER_V1_AND_WORKSPACE_CONTROLS`

## 3. Verified Problems

### Problem A: Workspace Image Preview Bug

Remote-image product truth with `IMAGE_READY` and
`asset_source=PRODUCT_IMAGE_URL` is still treated as renderable through
the local cached-image endpoint.

Observed forensic condition:

```text
preview_url=/api/products/{product_id}/image
download_url=/api/products/{product_id}/image
asset_source=PRODUCT_IMAGE_URL
local_image_path=null
```

This creates a false renderability contract. The workspace believes the
asset is preview-ready while the endpoint only works for a readable
local cached image.

### Problem B: Prompt Field Concept Bug

The F2V textarea currently receives generic generation instruction text
instead of a final compiled engine-ready UGC video prompt.

Observed forensic condition:

```text
approved_product_package_service.py::_f2v_prompt()
```

This is used as final workspace prompt truth even though it is only an
instruction-style scaffold and not a production-ready multishot UGC
output.

## 4. Root Cause

### Image Root Cause

1. `PRODUCT_IMAGE_CACHE` and `PRODUCT_IMAGE_URL` are treated too
   similarly during workspace asset resolution.
1. `preview_url` incorrectly points to `/api/products/{id}/image` for
   remote-image-only products.
1. `/api/products/{id}/image` is local-cache truth, not universal image
   truth.
1. Frontend image rendering lacks an explicit `onError` fallback and
   actionable fallback UI.

### Prompt Root Cause

1. `_f2v_prompt()` is used as final prompt truth for F2V workspace
   loading.
1. No UGC compiler stage exists between approved product package and
   workspace textarea.
1. No camera style, character/persona, or shot-plan controls exist in
   workspace contract.
1. No compiled-prompt lineage is stored in the workspace execution
   package.

## 5. Source-of-Truth Decision

### Image Truth

1. Local cached image truth uses:

```text
/api/products/{product_id}/image
```

1. Remote image truth uses:
   - direct `image_url`, or
   - a safe image proxy that returns real `image/*` bytes

1. Preview readiness must mean:

```text
the exact preview source is renderable in the workspace
```

not merely:

```text
some image_url exists somewhere in product truth
```

### Prompt Truth

1. Approved product package remains canonical product and claim-safe
   truth.
1. UGC video prompt compiler becomes final prompt truth for workspace
   generation.
1. Workspace execution package must store compiled prompt lineage and
   selected workspace controls.

## 6. Wave A Scope

### WAVE A

```text
WORKSPACE_IMAGE_PREVIEW_CONTRACT_HOTFIX
```

### Implement

1. Backend asset contract correction.
1. `PRODUCT_IMAGE_CACHE` must resolve preview and download to the local
   cached-image endpoint.
1. `PRODUCT_IMAGE_URL` must resolve preview and download to:
   - the direct remote image URL, or
   - a safe proxy endpoint that returns valid image bytes
1. Honest image readiness semantics.
1. Frontend fallback for broken preview.
1. F2V, I2V, and IMG image slots must show actionable error state
   instead of broken image or alt-only leakage.
1. Workspace package contract must not claim preview-ready when the
   resolved preview source is not actually renderable.

### Wave A Test Scope

1. Remote-image-only product path.
1. Local-cache image path.
1. Broken or expired preview source fallback path.
1. Existing workspace package and approved package regression coverage.

## 7. Wave B Scope

### WAVE B

```text
UGC_VIDEO_PROMPT_COMPILER_V1_AND_WORKSPACE_CONTROLS
```

### Implement UGC Video Prompt Compiler v1

### Compiler Inputs

1. Product truth
1. Approved package
1. Claim-safe rewrite
1. Safe hook
1. Safe CTA
1. Mode
1. Camera style
1. Character presence
1. Creator persona
1. Shot plan
1. Target language
1. Engine target

### Supported Camera Styles

1. `UGC_IPHONE_RAW`
1. `CINEMATIC_PRO`

### Default Contract

1. Visible creator enabled
1. Faceless only by explicit selection
1. `3-shot` structure
1. `BM_MS` target language
1. Vertical `9:16`

### Compiler Output

1. `final_compiled_prompt_text`
1. `compiler_version`
1. `camera_style`
1. `character_presence`
1. `shot_plan`
1. `prompt_fingerprint`
1. `warnings`
1. `blockers`
1. `source_of_truth_notes`

### Final Prompt Requirements

The final compiler output must be:

1. final engine-ready prompt, not instruction-to-generate text
1. UGC oriented
1. visible creator or character by default
1. same character continuity across shots
1. multibeat and multishot
1. explicitly structured as `Shot 1 / Shot 2 / Shot 3`
1. inclusive of `CU / MCU / medium / product close-up`
1. inclusive of camera lens, motion, handheld jitter, framing, and
   lighting
1. inclusive of product handling and HOI
1. claim-safe in wording
1. inclusive of dialogue or overlay where relevant
1. scrubbed of internal metadata leakage

## 8. Workspace UX Contract

Correct UX sequence:

```text
Load product package
-> confirm image truth
-> choose camera style
-> choose character/persona
-> choose shot plan
-> Generate Final Prompt
-> textarea displays final compiled prompt
-> Start Generation sends final prompt
```

The textarea must display the final compiled UGC prompt, not compiler
instructions.

## 9. BOSMAX Authority Caveat

Sovereign, Satellite, and Script Registry YAML files are not present in
this repo. This implementation wave must not fake them, simulate them,
or claim they are already wired.

Compiler v1 may use:

1. current product intelligence
1. claim-safe package truth
1. existing copy-signal or camera services where safe
1. local deterministic compiler rules

Future wave may ingest external Sovereign, Satellite, or Script Registry
packs after they are physically present and contract-authorized.

## 10. Safety Rules

Sensitive health and wellness output must retain claim-safe gating.

Forbidden output patterns:

1. cure claims
1. treatment claims
1. sexual-performance promises
1. guaranteed results

Required safe framing:

1. self-care wording
1. routine wording
1. external-use wording where applicable
1. claim-safe rewrite preservation

This wave does not authorize claim-safe bypass.

## 11. Out of Scope

1. Google Flow DOM
1. Chrome extension runtime
1. claim-safe bypass
1. production approval bypass
1. Smart Registration rewrite
1. FastMoss importer rewrite
1. TikTok scraping
1. temporal extension
1. result download or import automation
1. fake Sovereign, Satellite, or Script Registry YAML creation

## 12. Acceptance Criteria

### Wave A Acceptance

1. remote-image-only product no longer uses the broken local
   cached-image endpoint as preview truth
1. local cached image path still renders correctly
1. broken image fallback is visible and actionable
1. no alt-only broken image UI
1. image readiness semantics are honest

### Wave B Acceptance

1. F2V textarea displays final compiled UGC prompt
1. default prompt includes visible creator
1. prompt includes `3-shot` plan
1. prompt includes camera details
1. prompt includes product handling
1. prompt remains claim-safe
1. prompt is not generic instruction text
1. camera style can switch `UGC_IPHONE_RAW` and `CINEMATIC_PRO`
1. prompt lineage is persisted in workspace execution package

## 13. Validation Matrix

### Wave A Validation

1. workspace image preview contract service tests
1. workspace image preview API tests
1. workspace image preview UI tests
1. existing approved package tests
1. existing workspace execution package tests

### Wave B Validation

1. UGC video prompt compiler unit tests
1. UGC video prompt compiler API tests
1. UGC video prompt compiler UI tests
1. F2V workspace compiler UI contract tests
1. existing approved package tests
1. existing workspace execution package tests

### Shared Validation Gates

1. dashboard build
1. `npx tsx scripts/mandor-check.ts`
1. changed-file `npx @biomejs/biome check`
1. scoped `npx depcruise`

## 14. Runtime Proof Required

Runtime proof target product:

```text
4d491c01-2c5a-40c0-869e-54c50050d95d
```

### Image Proof

1. F2V package loads
1. Start Frame is renderable or shows clean actionable fallback
1. no broken image alt-only UI

### Prompt Proof

1. F2V workspace loads final compiled prompt
1. prompt includes `UGC_IPHONE_RAW` default
1. prompt includes visible creator
1. prompt includes `3-shot` structure
1. prompt includes camera details
1. prompt includes product handling
1. prompt includes claim-safe copy
1. prompt is not generic instruction text

## 15. Final Delivery Report Format

Future implementation PR must report:

```text
# STATUS
# BASELINE
# PLANNING_AUTHORITY
# IMAGE_PREVIEW_FIX_PROOF
# UGC_PROMPT_COMPILER_PROOF
# WORKSPACE_UI_PROOF
# SAFETY_PROOF
# VALIDATION_RESULTS
# CHANGED_FILES
# PR
# MERGE_READINESS
```

## 16. Bounded Implementation Decision

The next authorized execution after this document is:

```text
bounded implementation against this planning authority only
```

Sequence:

1. Wave A image preview contract hotfix
1. Wave B UGC video prompt compiler v1 and workspace controls

No broader workspace rewrite is authorized by this document.
