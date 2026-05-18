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

### Prompt Compiler Runtime Configuration Truth

Before Control Tower UI exists, compiler runtime policy must come from
one central config service or config file. It must not live as scattered
constants across frontend and backend files.

This interim runtime configuration is the source of truth for:

1. `generation_mode`
1. allowed block durations
1. per-language WPS policy
1. deterministic shot-count policy
1. camera style registry
1. persona and character default registry
1. continuation policy
1. engine and mode capability policy

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

### Generation Mode Contract

#### SINGLE

1. one compiled final prompt block
1. one selected duration
1. output is final engine-ready prompt

#### EXTEND

1. two compiled final prompt blocks
1. `Block 1 = ANCHOR`
1. `Block 2 = CONTINUATION`
1. Block 2 must continue Block 1 narrative, dialogue, character,
   product, and camera logic
1. Block 1 and Block 2 may have different durations

Allowed standard durations:

1. `6` seconds
1. `8` seconds
1. `10` seconds
1. `12` seconds
1. `15` seconds
1. `20` seconds
1. `25` seconds

Hardcoded `8-second` logic is forbidden.

### Duration, WPS, and Shot Policy Contract

The compiler must use deterministic and config-driven runtime policy for:

1. language-aware WPS policy
1. `BM_MS` and `EN_US` as initial required language keys
1. deterministic shot-count policy by duration
1. dialogue allowance derived from selected duration and selected
   language
1. shot plan derived from duration config, not ad hoc guessing

Required config example:

```json
{
  "allowed_block_durations_seconds": [6, 8, 10, 12, 15, 20, 25],
  "default_block_duration_seconds": 8,
  "shot_count_policy": {
    "6": { "recommended": 1, "max": 2 },
    "8": { "recommended": 2, "max": 2 },
    "10": { "recommended": 3, "max": 3 },
    "12": { "recommended": 3, "max": 3 },
    "15": { "recommended": 4, "max": 4 },
    "20": { "recommended": 5, "max": 5 },
    "25": { "recommended": 6, "max": 6 }
  },
  "language_wps_policy": {
    "BM_MS": {
      "hook_wps": 2.4,
      "body_wps": 1.7,
      "cta_wps": 2.2,
      "absolute_ceiling_wps": 3.0
    },
    "EN_US": {
      "hook_wps": 2.7,
      "body_wps": 2.0,
      "cta_wps": 2.5,
      "absolute_ceiling_wps": 3.2
    }
  }
}
```

Exact WPS and shot defaults may be tuned later, but implementation must
remain deterministic and config-driven.

Compiler lineage must include:

1. `generation_mode`
1. `block_duration_seconds`
1. `language_policy_id`
1. `shot_count_policy_id`

### EXTEND Continuation Contract

The compiler must support and persist:

1. `block_index`
1. `block_role` as `ANCHOR` or `CONTINUATION`
1. `duration_seconds`
1. `shot_count`
1. `continuation_from_block_id`
1. `continuation_strategy`
1. character continuity
1. wardrobe and appearance continuity
1. product state continuity
1. scene continuity
1. dialogue and narrative continuity
1. camera continuity
1. safe claim and copy continuity

Example:

```text
Block 1 = 10 seconds, 3 shots
Block 2 = 6 seconds, 1-2 shots
Total = 16 seconds
```

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
-> choose generation mode: Single / Extend
-> choose language
-> choose Block 1 duration
-> if Extend, choose Block 2 duration
-> choose camera style
-> choose character/persona
-> accept/generated shot plan from duration config
-> Generate Final Prompt
-> textarea displays final compiled prompt block(s)
-> Start Generation sends final prompt
```

For `EXTEND`:

1. UI must show Block 1 and Block 2 outputs separately
1. Block 2 must be visibly labelled as continuation
1. User must not receive two disconnected prompts

The textarea must display the final compiled UGC prompt block or blocks,
not compiler instructions.

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

### Future Governance Dependency

This UGC wave must align with Issue `#71`.

Future Control Tower is the governance owner for:

1. admin settings
1. prompt compiler config
1. character and persona library
1. camera and shot preset library
1. user management
1. RBAC
1. page permissions
1. product content visibility
1. subscription-ready governance

Current UGC implementation may use a central config service or config
file as interim source of truth.

This UGC wave must not implement full Control Tower UI unless
separately authorized.

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
1. temporal extension beyond the bounded Single and Extend contract
1. result download or import automation
1. fake Sovereign, Satellite, or Script Registry YAML creation
1. Control Tower admin UI
1. RBAC implementation
1. page permission enforcement redesign
1. product visibility management UI
1. user management
1. subscription billing or governance implementation

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
1. prompt includes `3-shot` plan where duration policy resolves to three
   shots
1. prompt includes camera details
1. prompt includes product handling
1. prompt remains claim-safe
1. prompt is not generic instruction text
1. camera style can switch `UGC_IPHONE_RAW` and `CINEMATIC_PRO`
1. supports `SINGLE | EXTEND`
1. allowed durations include `6, 8, 10, 12, 15, 20, 25`
1. no hardcoded `8-second` logic
1. per-language WPS policy is applied
1. deterministic shot count is derived by duration
1. Extend allows different duration per block
1. continuation lineage persists
1. Block 2 continues from Block 1
1. central config service or config file drives compiler policy
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
1. duration registry tests
1. WPS policy tests
1. shot-count policy tests
1. `SINGLE` mode tests
1. `EXTEND` mode tests
1. different duration per block tests
1. continuation lineage tests
1. central config service or config file contract tests
1. workspace UI control tests for language, generation mode, and
   duration
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
1. prompt includes `3-shot` structure where duration policy resolves to
   three shots
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
