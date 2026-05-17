# APPROVED PRODUCT PACKAGE WORKSPACE BRIDGE PLAN v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `APPROVED_PRODUCT_PACKAGE_WORKSPACE_BRIDGE_PLAN` |
| `version` | `v0.1` |
| `status` | `APPROVED_FOR_IMPLEMENTATION_PLANNING` |
| `implementation_status` | `NO_CODING_INSIDE_THIS_FILE` |
| `repo` | `farisdatosheikh/my-flowkit-bosmax` |
| `baseline_main_sha` | `ccb179d505311f5511b93695671a5f6be8a6ec1b` |
| `decision_source` | `User approval + Codex architecture handshake` |

## 2. Executive Decision

The next production wave is not Google Flow DOM repair first.

The next production wave is:

```text
APPROVED_PRODUCT_PACKAGE_HISTORY_AND_WORKSPACE_BRIDGE
```

Reason: the backend product and prompt approval pipeline is ahead of the workspace execution layer. The workspaces still behave like manual forms with manual prompt textareas and manual upload slots. A fixed DOM handoff can still submit a weak, wrong, empty, or manually improvised payload unless the workspaces consume a canonical approved package.

## 3. Root Architecture Problem

The system currently separates five concerns without a strong bridge:

```text
Product Truth
Approval Truth
Prompt Text
Workspace Payload
Flow Request / Telemetry
```

This creates a split-brain architecture:

```text
Product / approval / prompt backend says READY.
Workspace UI still begins from manual textarea and manual uploads.
```

The missing layer is:

```text
Approved Product Package -> Workspace Execution Package -> Flow Handoff Request
```

## 4. Source-of-Truth Separation

### 4.1 Product Record

Canonical for product identity, source, taxonomy, lifecycle, cached product image, claim gate, product family, and commercial/source metadata.

### 4.2 Prompt Package Truth

Canonical for generated prompt, approved prompt, mode, version, duration, claim-safe rewrite, approval state, asset requirements, and provenance.

Wave 1 may start as a materialized approved package read-model derived from existing product, claim-safe, production approval, and dry-run services. A full normalized prompt-package table is not mandatory unless required for persistence, batch, or history correctness.

### 4.3 Workspace Execution Package

A derived operator payload, not canonical truth. It contains product, mode, approved prompt, asset slots, resolved asset sources, readiness, manual fallback data, and execution eligibility.

### 4.4 Flow Handoff Request

Runtime truth for request id, product id, prompt package or snapshot id, asset package or snapshot id, mode, prompt fingerprint, asset fingerprints, extension build id, DOM stage telemetry, and terminal success/failure state.

### 4.5 Flow Result / Output

Later-wave output lineage linking product -> prompt package -> workspace execution package -> Flow request -> generated result.

## 5. Minimum Solid Architecture

The next bounded wave must add:

1. Approved Product Package read-model endpoint/service.
2. Workspace Execution Package endpoint/service.
3. Package/history/manual fallback page or panel.
4. T2V workspace package load and prompt prefill.
5. F2V product cached image as default start frame; end frame optional.
6. I2V product cached image as subject option; scene/style can remain manual in wave 1.
7. IMG product cached image as subject/reference plus approved IMG prompt.
8. Request lineage additions for product/package/execution payload.
9. Tests and dashboard build proof.

## 6. Mode Contracts

### T2V

- Product selector loads approved T2V prompt.
- No image required by default.
- Manual override remains possible but must be visibly marked as override.
- Submit uses locked package payload by default.

### F2V / Frames

- Start frame is required.
- End frame is optional.
- Product cached image becomes default start frame when available.
- If no cached product image exists, block with `START_FRAME_REQUIRED`.
- Approved/generated F2V prompt prefills the prompt area.

### I2V / Ingredients

- Subject can come from product cached image.
- Scene and style can remain manual upload in wave 1.
- Do not force all three slots to manual-upload only.

### IMG

- Product selector loads approved IMG prompt.
- Product cached image becomes default subject/reference.
- Scene/style remain optional manual additions.
- Do not fabricate label details.

## 7. Manual Fallback Contract

Manual fallback is mandatory and extension-independent.

Operator must be able to:

- select product
- select approved mode
- view approved prompt
- copy approved prompt
- preview cached product image
- download/open cached product image
- view exact asset requirements
- view execution checklist
- manually use the prompt and image in Google Flow
- later record manual execution attempt

## 8. Batch Contract

Batch execution must not rely on ephemeral UI state.

Each batch item should reference or snapshot:

- product id
- mode
- prompt package id or prompt package snapshot
- asset package id or asset package snapshot
- execution package id
- status
- retry count
- last successful stage

Batch must be resumable from persisted package state, not regenerated blindly from mutable product fields each time.

Temporal extension is deferred until package/workspace bridge is stable.

## 9. In Scope

- approved product package read-model
- package/history operator page
- workspace prefill bridge for T2V/F2V/I2V/IMG
- product cached image to workspace asset conversion
- single execution package persistence
- batch variant linkage to approved package snapshot
- request log references to package/execution ids or snapshots
- manual fallback copy/download/checklist

## 10. Out of Scope

- Google Flow DOM repair
- Chrome extension stale build repair
- product registration rebuild
- FastMoss changes
- TikTok intake changes
- temporal extension execution
- result download/import automation
- broad UI redesign
- full prompt package versioning table unless absolutely necessary

## 11. Implementation Order Inside the Wave

1. Inspect existing product, readiness, dry-run, and production approval services.
2. Create approved product package read-model.
3. Create workspace execution package endpoint/service.
4. Add product cached image to workspace asset conversion.
5. Add package/history/manual fallback surface.
6. Wire T2V package load/prefill.
7. Wire F2V product image start-frame default.
8. Wire IMG package load/product image default.
9. Wire I2V subject source selector for product image.
10. Add request lineage fields or payload metadata for prompt/execution package.
11. Add tests.
12. Run dashboard build.

## 12. Acceptance Criteria

### Backend

- Approved package endpoint returns T2V and IMG package for Bosmax Herbs 5 ML.
- F2V package returns `START_FRAME` requirement and product cached image if available.
- I2V package exposes product image as subject source.
- Workspace execution package can be created without manual upload when product image exists.
- Package response includes manual fallback data.
- Request/handoff payload can carry product/package/execution lineage.

### Frontend

- T2V page can load product and approved prompt.
- F2V page can load product image as start frame automatically.
- I2V page can select product image as subject.
- IMG page can load product image and approved IMG prompt.
- Manual fallback UI exposes copy prompt and image access.
- Manual text/upload remains possible but is clearly override behavior.

### Safety and Regression

- No unsafe claim terms introduced.
- No metadata leaks in displayed prompt package.
- Archived products cannot create executable packages.
- Unapproved packages cannot be sent as production packages.
- Existing production approval, dry-run, readiness, and asset upload behavior remain intact.
- FastMoss remains unchanged.

## 13. Validation Matrix

Existing targeted suites:

```text
pytest tests/api/test_prompt_package_dryrun_api.py -q
pytest tests/api/test_production_prompt_approval_api.py -q
pytest tests/api/test_prompt_pipeline_readiness_api.py -q
pytest tests/unit/test_prompt_package_dryrun_service.py -q
pytest tests/unit/test_prompt_pipeline_readiness_service.py -q
pytest tests/unit/test_product_intelligence_service.py -q
```

New suites to add:

```text
pytest tests/unit/test_approved_product_package_service.py -q
pytest tests/api/test_approved_product_package_api.py -q
pytest tests/unit/test_workspace_execution_package_service.py -q
pytest tests/api/test_workspace_execution_package_api.py -q
pytest tests/ui/test_workspace_package_bridge_ui_contract.py -q
```

Build:

```text
cd dashboard
npm run build
```

## 14. Governance Notes

Known repo governance-surface gaps:

- `docs/MODULE_STATUS.yaml` missing
- `graphify-out/` missing
- `scripts/mandor-check.ts` missing
- local dependency-graph tooling may be unavailable
- repo-wide formatting diagnostics may pre-exist

These must be reported. They should not silently derail this bounded wave unless repo owner explicitly requires them as hard merge gates.

## 15. Required Final Delivery Format for Implementation PR

Future Codex implementation report must include:

```text
# STATUS
PASS_PR_OPENED / BLOCKED

# BASELINE
main SHA

# PLANNING_AUTHORITY
path to this document and commit SHA

# APPROVED_PACKAGE_PROOF
T2V / F2V / I2V / IMG package examples

# WORKSPACE_BRIDGE_PROOF
UI/source proof for each workspace

# MANUAL_FALLBACK_PROOF
copy prompt / image access / checklist proof

# BATCH_LINKAGE_PROOF
single/batch lineage behavior

# FLOW_REQUEST_LINEAGE_PROOF
product/package/execution IDs in payload or request log

# VALIDATION_RESULTS
test/build pass counts

# REPO_HYGIENE_PROOF
no runtime artifacts

# CHANGED_FILES
exact files

# PR
actual PR URL

# MERGE_READINESS
MERGE_READY / NOT_MERGE_READY with reason
```

## 16. Final Decision

This plan authorizes implementation planning only.

Implementation should proceed as a bounded wave:

```text
APPROVED_PRODUCT_PACKAGE_HISTORY_AND_WORKSPACE_BRIDGE
```

Do not resume Google Flow DOM execution until the workspace bridge can send a locked product/package payload.

Do not start temporal extension until approved package/workspace bridge is stable.
