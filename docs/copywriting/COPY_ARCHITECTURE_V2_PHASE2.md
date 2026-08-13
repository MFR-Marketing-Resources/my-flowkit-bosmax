# Copy Architecture V2 — Phase 2 Contract

Status: additive domain/evidence/binding contract.  The default feature flag is
OFF.  This phase does not wire pages, migrate legacy rows, call providers, or
change the canonical compiler.

## Domain contract

`agent/models/copy_blueprint_v2.py` is the first-class contract.  A V2
blueprint carries:

- `version = "2"`, stable `blueprint_id`, `copy_set_id`, positive `revision`,
  lifecycle status, objective, angle, and revision/supersession metadata;
- explicit `formula_id` and authority `formula_version`;
- an ordered tuple of `FormulaStage` objects.  The stage list is the only
  authored source of truth;
- component references, target duration/WPS metadata, and full Product Truth
  lineage;
- an immutable `ApprovalSnapshot` plus immutable approved execution text after
  the explicit human approval transition.

Hook/body/CTA are derived by `CopyBlueprintV2.derived_projections()` from the
ordered formula stages.  They are display/compatibility views and cannot
reconstruct a V2 blueprint.

## Evidence contract

Every claim-bearing stage must reference an `EvidenceReference`:

```json
{
  "snapshot_id": "pi-snapshot-1",
  "fact_id": "fact-benefit-001",
  "text_digest": "sha256-of-approved-fact-wording",
  "fact_kind": "benefit"
}
```

`fact_id` is supplied stable semantic identity.  `text_digest` detects wording
drift and is never used as durable identity.  `EvidenceRegistry` validates
product, approved snapshot, fact kind, and exact wording digest.  A wording
correction preserves `fact_id`, changes `text_digest`, and requires
revalidation/reapproval.

## Binding contract

`CopyExecutionBinding` carries:

- blueprint ID and revision;
- formula ID and formula version;
- approval snapshot ID;
- Product Truth lineage and evidence lineage/digest;
- compiler/binding contract version;
- feature-flag state, lane, media kind, and explicit copy policy.

Binding is read-only with respect to the blueprint.  It fails closed when the
flag is OFF, scope is absent, lineage is stale, evidence is invalid, approval
is missing/mutated, the formula is unknown, or a V2 error would otherwise fall
through to legacy/HSO copy.

## Universal producer/consumer matrix

The executable matrix is `agent/authority/copy_lane_matrix.py`.  It is
intentionally complete before Phase 3 page wiring begins.

| Lane | Media | Copy policy | Current API entry | Current service seam | Current page | Phase 3 adapter scope |
| --- | --- | --- | --- | --- | --- | --- |
| T2V | VIDEO | REQUIRED | `POST /api/flow/execute-flow-job` | `workspace_execution_package_service.py` | `OperatorPage.tsx (mode=T2V)` | bind selected revision into T2V package/compile |
| F2V | VIDEO | REQUIRED | `POST /api/flow/execute-flow-job` | `f2v_frame_source_resolver_service.py` | `OperatorPage.tsx (mode=F2V)` | bind revision alongside frame lineage |
| Hybrid | VIDEO | REQUIRED | `POST /api/flow/execute-flow-job` | `workspace_execution_package_service.py` | `OperatorPage.tsx` | bind revision without legacy fallback |
| I2V | VIDEO | REQUIRED | `POST /api/flow/execute-flow-job` | `i2v_semantic_slot_resolver_service.py` | `OperatorPage.tsx (mode=I2V)` | bind revision alongside reference slots |
| Faceless | VIDEO | REQUIRED | `POST /api/faceless/prepare` | `faceless_lane_service.py` | `FacelessVideoPage.tsx` | bind revision into faceless preparation |
| Montage | VIDEO | REQUIRED | `POST /api/montage/runs` | `montage_run_service.py` | `MontagePage.tsx` | bind revision into scene planning |
| Production Studio / P6 | VIDEO | REQUIRED | `POST /api/creative-production/plans` | `creative_production_compile_service.py` | `CreativeProductionStudioPage.tsx` | bind revision at compile/queue boundaries |
| Image Gen | IMAGE | NOT_REQUIRED | `POST /api/flow/generate (mode=IMG)` | `image_prompt_compiler.py` | `workspace/IMGModule.tsx` | carry explicit copy-free policy and gate proof |
| IMG Fastlane | IMAGE | NOT_REQUIRED | `POST /api/img-factory/*` | `img_asset_factory_service.py` | `ImgFastlanePage.tsx` | carry explicit copy-free policy and gate proof |
| IMG Cockpit | IMAGE | NOT_REQUIRED | `POST /api/flow/generate (mode=IMG)` | `image_prompt_compiler.py` | `ImgCockpitPage.tsx` | carry explicit copy-free policy and gate proof |
| Poster Builder | IMAGE | REQUIRED | `POST /api/poster/compose` / `POST /api/poster/prompt-draft` | `poster_composition_service.py` | `PosterBuilderPage.tsx` | bind poster-aware copy explicitly; no video-stage assumption |

`VideoCopyProjection` is the required-copy adapter for all seven video lanes.
`ImageCopyProjection` handles all four image lanes.  Image Gen, IMG Fastlane,
and IMG Cockpit are explicitly copy-free; their adapter still requires proof of
readiness, provenance, and safety and refuses an accidental V2 binding.  Poster
Builder is explicitly copy-aware.

## Validation and safety boundaries

The read-only API is:

- `GET /api/copy-architecture/v2/lanes`;
- `POST /api/copy-architecture/v2/validate`;
- `POST /api/copy-architecture/v2/bind`.

These routes do not persist, approve, invoke the compiler, call a provider, or
spend credits.  Human approval is only performed by the explicit domain
service transition, never by validation or binding.

The legacy `CopySet`, legacy compiler, legacy API signatures, and flag-off
golden projection remain untouched.  No mass migration, backfill, or database
data mutation is part of Phase 2.

## Phase 3 implementation scope (not implemented here)

Phase 3 must wire the same adapters and binding lineage at each matrix seam:

1. T2V — workspace package, prompt preparation, and API-first execution binding.
2. F2V — frame-source package and execution binding.
3. Hybrid — Operator package and final-prompt binding.
4. I2V — semantic reference package and execution binding.
5. Faceless — faceless prepare/queue contract.
6. Montage — montage run/scene orchestration contract.
7. Production Studio / P6 — compile, queue, and production item boundaries.
8. Image Gen — explicit copy-free adapter at the IMG generation boundary.
9. IMG Fastlane — explicit copy-free adapter at the Fastlane boundary.
10. IMG Cockpit — explicit copy-free adapter at the Cockpit boundary.
11. Poster Builder — copy-aware poster composition/prompt boundary.

Phase 3 must not remove legacy compatibility, enable V2 globally, rewrite
approved text, or add provider/credit behavior without a later explicit
authorization and acceptance gate.
