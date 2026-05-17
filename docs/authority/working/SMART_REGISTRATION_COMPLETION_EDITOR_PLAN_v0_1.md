# SMART REGISTRATION COMPLETION EDITOR PLAN v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `SMART_REGISTRATION_COMPLETION_EDITOR_PLAN` |
| `version` | `v0.1` |
| `status` | `APPROVED_FOR_IMPLEMENTATION_PLANNING` |
| `implementation_status` | `NO_CODING_INSIDE_THIS_FILE` |
| `repo` | `farisdatosheikh/my-flowkit-bosmax` |
| `baseline_main_sha` | `9bd719f7b92f62cc51b731cb53e923a6f3bc6298` |
| `decision_source` | `User approval + Codex Smart Registration completion editor handshake` |
| `related_module` | `Smart Product Registration / Review Draft Authority` |

## 2. Executive Decision

The next Smart Registration production wave is:

```text
SMART_REGISTRATION_COMPLETION_EDITOR_AND_EVIDENCE_WORKBENCH
```

The current Smart Registration system has intake, review draft, approval checklist, and controlled commit authority. However, the review draft screen still behaves mostly as an approval queue. It is not yet a full evidence completion/editor workbench.

The implementation must let operators complete missing evidence, attach product images, generate or edit hook/CTA angles, recompute candidates/readiness, and commit only after the refreshed draft state is reviewed.

## 3. Current Verified Problem

Current flow:

```text
intake -> completion snapshot -> review draft -> approval toggles -> commit
```

Required flow:

```text
intake or draft -> edit missing evidence -> attach/cache image -> recompute candidates/readiness -> review -> commit
```

Observed product/draft gaps:

- commercial evidence can remain missing after draft creation
- `price`, `commission_amount`, and `commission_rate` are not first-class editable evidence in the review screen
- `image_url` and `local_image_path` can be missing or stale at draft stage
- product image upload is available in intake but not properly available in review draft workbench
- `hook_angles` and `cta_angles` can remain empty
- image semantic analysis can report `VISION_PROVIDER_NOT_CONFIGURED`, but that must not block basic image cache readiness
- review draft edits do not currently trigger full recompute of candidates, missing evidence, claim gate, or mode readiness
- commit can be attempted from a stale snapshot unless a refreshed draft pass is enforced

## 4. Current Surface Audit

| Surface | Current State | Decision |
| --- | --- | --- |
| ProductKnowledgeIntakeForm | Has price, commission, URLs, TikTok URLs, image URL, image upload | Reuse; not enough alone |
| RegistrationReviewDraftPanel | Shows evidence/candidates/readiness and approval toggles | Must become evidence workbench |
| Field decisions API | Accepts `edited_declared_evidence` but is semantically overloaded | Keep for approval; add dedicated evidence endpoint |
| Draft storage service | Persists draft JSON and can merge evidence dict | Extend with recompute-aware update path |
| Product image during intake | Partial support via image URL/base64/local path | Extend to review draft stage |
| Draft image analysis | Not callable/persisted from review draft | Add review-stage attach/reanalysis flow |
| Hook/CTA models | Fields exist as suggested arrays | Populate and expose editor/generator |
| Missing evidence | Stored as list | Recompute after evidence edits |
| Mode readiness | Frozen from initial completion snapshot | Recompute after material edits |
| Commit service | Controlled write-back exists | Enforce refreshed draft state before commit |

## 5. Root Architecture Gap

The review draft is currently treated as a mostly static snapshot plus approval decisions.

The missing architecture is:

```text
Review Draft Evidence Editor
+ Draft Image Attach/Cache
+ Hook/CTA Generation/Edit
+ Draft Recompute Pipeline
+ Refreshed Commit Gate
```

The system must support completion of incomplete product records before canonical write-back.

## 6. Source-of-Truth Decision

### 6.1 Pre-Commit Evidence Truth

Pre-commit editable evidence lives in:

```text
draft.declared_evidence_fields
```

This includes raw operator evidence such as:

- product name
- product knowledge text
- benefits
- usage
- ingredients
- warnings
- target customer
- price
- currency
- commission amount
- commission rate
- size/volume
- package notes
- product URL
- source URL
- TikTok product URL
- TikTok shop URL
- image URL
- local image path
- paste-anything text

### 6.2 Draft Image Truth

Draft-stage image truth is:

```text
draft.declared_evidence_fields.image_url
draft.declared_evidence_fields.local_image_path
draft.system_inferred_fields.image_analysis_*
draft.canonical_candidate_fields.image_* where applicable
```

Image cache readiness and semantic vision analysis are separate.

If vision provider is not configured, the system must report it honestly but still allow cached image readiness when an image is available.

### 6.3 Hook/CTA Truth

Draft-stage hook/CTA truth should live in:

```text
draft.canonical_candidate_fields.hook_angles
draft.canonical_candidate_fields.cta_angles
```

They must be generated from current evidence and remain human-editable before commit.

### 6.4 Draft Readiness Truth

Draft-stage readiness lives in:

```text
draft.readiness_by_mode
draft.missing_required_evidence
draft.human_review_fields
draft.claim_gate
draft.claim_tokens
```

These must be recomputed after material evidence edits.

### 6.5 Post-Commit Truth

After controlled commit, canonical product truth remains in the product row and related product intelligence/prompt readiness surfaces.

Product-level prompt approval/readiness remains product-level, not draft-level.

## 7. Minimum Bounded Implementation Wave

This wave must implement a bounded draft completion workbench, not a broad registration rewrite.

### 7.1 Dedicated Draft Evidence Patch API

Add a dedicated endpoint, for example:

```text
PATCH /api/product-registration/review-drafts/{draft_id}/evidence
```

Responsibilities:

- update `declared_evidence_fields`
- support commercial/source fields
- support hook/CTA manual overrides
- support image URL updates
- trigger recompute after material edits
- persist refreshed draft
- return updated draft

Do not overload `field-decisions` for full evidence editing.

### 7.2 Draft Evidence Editor UI

Inside `RegistrationReviewDraftPanel`, add an operator-facing section:

```text
Complete Missing Evidence
```

Editable fields:

- product name
- product knowledge text
- benefits text
- usage text
- target customer text
- ingredients text
- warnings text
- price
- currency
- commission amount
- commission rate
- size or volume
- package notes
- product URL
- source URL
- TikTok product URL
- TikTok shop URL
- image URL
- upload product image
- hook angles
- CTA angles
- safe copy notes / claim-safe rewrite notes where available

UX requirements:

- show missing evidence prominently
- allow save draft evidence
- show recompute status
- show before/after freshness timestamp
- prevent commit from stale recompute state

### 7.3 Draft Image Attach / Cache

Add review-stage ability to:

- upload product photo
- paste image URL
- persist image evidence to draft
- cache image locally if supported
- preview current draft image
- expose image cache readiness separately from semantic image analysis

Required behavior:

```text
image available + cached = image asset ready
vision provider missing = semantic image analysis not available, not image missing
```

### 7.4 Hook/CTA Generation and Manual Override

Generate hook and CTA suggestions from current draft evidence:

Inputs:

- product name
- benefits
- target customer
- usage
- claim gate
- copy route
- silo
- safe claim constraints

Outputs:

- `hook_angles`
- `cta_angles`

Rules:

- sensitive health products must avoid unsafe medical/sexual performance promises
- human can edit or override generated suggestions
- empty hook/CTA should be a visible completion gap where relevant

### 7.5 Draft Recompute Pipeline

After evidence edit, rerun a completion-style recompute from current draft evidence.

Refresh:

- canonical candidates
- system inferred fields
- missing required evidence
- human review fields
- claim gate
- claim tokens
- image readiness/analysis state
- readiness by mode
- review status

Avoid stale snapshot behavior.

### 7.6 Refreshed Commit Gate

Commit must only proceed when the draft is not stale.

Required checks:

- evidence has latest recompute timestamp
- no unresolved mandatory missing evidence unless lane policy allows it
- required human review fields approved
- claim gate not blocked
- image readiness requirements respected by target modes
- confirmation phrase remains required

## 8. Lane Policy

### 8.1 OWNED

Full workbench support.

Owned products require strongest completion because they become canonical BOSMAX assets.

### 8.2 MANUAL

Same workbench as OWNED.

Commit allowed when evidence/review gates pass.

### 8.3 FASTMOSS_REFERENCE

Use the same completion editor.

Rules:

- do not blindly convert affiliate/reference data into owned canonical truth
- allow completion for prompt/package generation when evidence is sufficient
- maintain source provenance
- commercial fields may come from FastMoss if available, but missing fields must be editable

### 8.4 TIKTOKSHOP_DRAFT

Use the same completion editor.

If scraping/extraction is unavailable:

- mark extraction as `NOT_IMPLEMENTED`
- allow user to complete evidence manually
- keep URL provenance

### 8.5 UNKNOWN_REVIEW_REQUIRED

Use the same completion editor with stricter review gates.

## 9. Out of Scope

Do not include in this wave:

- Google Flow DOM repair
- Chrome extension runtime repair
- workspace package bridge changes unless compatibility is broken
- FastMoss importer logic rewrite
- TikTok scraping implementation
- product lifecycle archive/unarchive changes
- full vision provider integration
- production prompt approval flow rewrite
- temporal extension / multi-block video planner
- result download/import automation
- broad product-row schema rewrite

## 10. Implementation Order

1. Inspect current draft models, draft storage, completion service, registration commit service, image cache services, and review panel.
2. Add draft evidence patch request/response models.
3. Add dedicated draft evidence patch endpoint.
4. Add recompute service for review drafts.
5. Add hook/CTA suggestion generation inside draft recompute.
6. Add draft image attach/cache support.
7. Add review draft evidence editor UI.
8. Add image preview / upload / URL controls to draft review.
9. Add missing evidence/resolved evidence UI.
10. Add stale recompute guard before commit.
11. Add tests.
12. Run dashboard build and targeted backend tests.

## 11. Acceptance Criteria

### Backend

- Dedicated evidence endpoint exists.
- Evidence edits persist to `declared_evidence_fields`.
- Price, currency, commission amount, and commission rate can be edited after draft creation.
- Image URL/local image path can be updated after draft creation.
- Draft image can be cached or marked available for asset generation.
- Hook/CTA suggestions are generated or can be manually edited.
- Missing evidence is recomputed after edits.
- Mode readiness is recomputed after edits.
- Claim gate and claim tokens refresh after material text edits.
- Commit rejects stale draft if material edits have not been recomputed.

### Frontend

- Review draft page exposes `Complete Missing Evidence` editor.
- Missing evidence fields are highlighted.
- User can edit price/commission/source/image/hook/CTA fields.
- User can save evidence edits without committing.
- User can attach product image in draft review.
- User can see image preview and image readiness state.
- User can generate or edit hook/CTA angles.
- User can rerun recompute and see refreshed readiness.
- Commit button reflects refreshed readiness.

### Lane Coverage

- OWNED supported.
- MANUAL supported.
- FASTMOSS_REFERENCE supported with provenance caution.
- TIKTOKSHOP_DRAFT supported as manual completion fallback.

### Safety

- Sensitive health claims remain gated.
- Unsafe hook/CTA claims are not generated.
- `VISION_PROVIDER_NOT_CONFIGURED` does not falsely mean image asset missing.
- No blind commit from stale draft snapshot.

## 12. Validation Matrix

Existing tests to preserve:

```text
pytest tests/api/test_product_knowledge_completion_api.py -q
pytest tests/unit/test_product_knowledge_completion_service.py -q
pytest tests/api/test_product_registration_api.py -q
pytest tests/unit/test_product_registration_service.py -q
pytest tests/unit/test_product_registration_commit_service.py -q
pytest tests/unit/test_product_registration_review_service.py -q
```

New tests to add:

```text
pytest tests/unit/test_registration_draft_evidence_editor_service.py -q
pytest tests/api/test_registration_draft_evidence_editor_api.py -q
pytest tests/ui/test_registration_draft_evidence_editor_ui_contract.py -q
pytest tests/unit/test_registration_draft_recompute_service.py -q
pytest tests/api/test_registration_draft_image_attach_api.py -q
pytest tests/unit/test_registration_hook_cta_generation_service.py -q
```

Build:

```text
cd dashboard
npm run build
```

Governance:

```text
npx tsx scripts/mandor-check.ts
npx @biomejs/biome check <changed frontend files>
npx depcruise agent dashboard/src
```

## 13. Runtime Proof Required

Use Bosmax Herbs draft with missing evidence.

Prove:

1. Draft opens in review page.
2. `Complete Missing Evidence` editor appears.
3. Price can be entered.
4. Commission amount/rate can be entered.
5. Image URL can be entered or product image uploaded.
6. Image preview appears.
7. Hook/CTA suggestions can be generated or manually edited.
8. Save evidence persists draft.
9. Recompute refreshes missing evidence.
10. Recompute refreshes claim gate/readiness.
11. Prompt generation blocker reduces when evidence is completed.
12. Commit remains gated until review requirements are approved.
13. Same editor is available for FASTMOSS_REFERENCE and TIKTOKSHOP_DRAFT drafts.

## 14. Required Final Delivery Format for Implementation PR

Future implementation report must include:

```text
# STATUS
PASS_PR_OPENED / BLOCKED

# BASELINE
main SHA

# PLANNING_AUTHORITY
docs/authority/working/SMART_REGISTRATION_COMPLETION_EDITOR_PLAN_v0_1.md
planning commit SHA

# IMPLEMENTATION_SUMMARY
what was built

# EVIDENCE_EDITOR_PROOF
fields editable, save persistence, missing evidence visibility

# IMAGE_ATTACH_PROOF
upload/url/cache/preview behavior

# HOOK_CTA_PROOF
generation/edit behavior and safety constraints

# RECOMPUTE_PROOF
missing evidence, candidates, claim gate, readiness refreshed

# COMMIT_GATE_PROOF
stale commit blocked, refreshed review allowed only after gates pass

# LANE_PROOF
OWNED / MANUAL / FASTMOSS_REFERENCE / TIKTOKSHOP_DRAFT

# VALIDATION_RESULTS
test/build/governance results

# REPO_HYGIENE_PROOF
no runtime artifacts

# CHANGED_FILES
exact files

# PR
actual PR URL

# HEAD_SHA
remote branch head SHA

# MERGE_READINESS
MERGE_READY / NOT_MERGE_READY with reason
```

## 15. Final Decision

This plan authorizes implementation planning only.

Implementation should proceed as a bounded wave:

```text
SMART_REGISTRATION_COMPLETION_EDITOR_AND_EVIDENCE_WORKBENCH
```

Do not resume Google Flow DOM handoff, temporal extension, or result return-loop work until this Smart Registration completion editor is either implemented or explicitly deferred by the product owner.
