# Copy Architecture V2 — Phase 3 consumer/lane cutover

Status: implemented on the Phase 3 branch; default-off until an explicit
feature-flag rollout.

Baseline: `origin/main=241c4f6e540c04c2d708c5a2467745cdd468bf71`

Phase 3 makes the Phase 2 contract executable at every listed consumer seam.
It does not enable the flag globally, migrate `CopySet` data, alter the legacy
compiler, call a provider, or spend credits.

## One consumer boundary

`agent/services/copy_execution_resolver.py` is the shared synchronous boundary.
Every V2-enabled consumer submits the product id, lane, and the immutable
blueprint/evidence/Product Truth context. The resolver creates the binding and
projection; consumers cannot submit a binding as authority.

With V2 OFF, the resolver returns `LEGACY_COMPATIBLE` and callers continue into
the existing legacy path. With V2 ON, the resolver fails closed for missing or
stale Product Truth lineage, malformed evidence, unknown formulas, missing or
non-production-valid copy, policy violations, and invalid adapter readiness,
provenance, or safety state.

Durable package, run, plan, poster, and queue handoffs persist the validated
`copy_architecture_v2` receipt and `copy_execution_binding`. The original
validated context is carried only for re-entry validation; it is not a caller-
supplied binding and it preserves the original `bound_at` identity.

## Complete consumer matrix

| Lane | Policy | API entry point(s) | Service boundary | UI surface | V2 Phase 3 behavior |
| --- | --- | --- | --- | --- | --- |
| T2V | REQUIRED | `/api/flow/execute-flow-job`, `/api/flow/generate` | workspace execution package → API-first generation | `OperatorPage` | bind approved dialogue before compile/generation |
| F2V | REQUIRED | `/api/flow/execute-flow-job`, `/api/flow/generate` | workspace generation package / frame-source handoff | `OperatorPage` | bind alongside frame lineage |
| Hybrid | REQUIRED | `/api/flow/execute-flow-job`, `/api/flow/generate` | workspace generation package → F2V handoff | `OperatorPage` | preserve `HYBRID` lane identity |
| I2V | REQUIRED | `/api/flow/execute-flow-job`, `/api/flow/generate` | workspace generation package / semantic-slot handoff | `OperatorPage` | bind alongside reference slots |
| Faceless | REQUIRED | `/api/faceless/validate`, `/api/faceless/prepare` | faceless preparation package | `FacelessVideoPage` | require V2 binding before preparation |
| Montage | REQUIRED | `/api/montage/plan`, `/api/montage/execute-scenes`, `/api/montage/runs` | scene orchestrator and run service | `MontagePage` | carry one binding through every scene/run |
| Production Studio / P6 | REQUIRED | `/api/creative-production/plans`, `/plans/{id}/compile`, `/plans/{id}/start` | P6 compile → scheduler → production queue | `CreativeProductionStudioPage`, `ProductionQueuePage` | block queue/start unless the V2 receipt is READY |
| Image Gen | NOT_REQUIRED | `/api/flow/generate` with `mode=IMG` | image generation package | `IMGModule` | explicit copy-free adapter and readiness receipt |
| IMG Fastlane | NOT_REQUIRED | `/api/img-factory/fastlane-preview` | Fastlane preview/asset factory boundary | `ImgFastlanePage` | explicit copy-free adapter; no implicit bypass |
| IMG Cockpit | NOT_REQUIRED | `/api/flow/generate` with the Cockpit image lane | image generation package | `ImgCockpitPage` | explicit copy-free adapter and readiness receipt |
| Poster Builder | REQUIRED | `/api/poster/compose`, `/api/poster/prompt-draft` | poster composition and prompt-draft services | `PosterBuilderPage` | poster-aware projection; no video compiler assumption |

The executable source of truth for policy and adapter names remains
`agent/authority/copy_lane_matrix.py`. The shared UI receipt is
`dashboard/src/components/copywriting/CopyArchitectureV2LaneCard.tsx`; it
shows flag-off compatibility honestly and shows a blocked state when V2 is on
without a production binding. Poster Builder is intentionally copy-aware.

## Compiler and safety rules

The compiler receives only derived compatibility fields plus the immutable
ordered approved dialogue. A Phase 3 V2 compile compares planner and rendered
dialogue slices against that immutable text and raises
`COPY_V2_COMPILER_MUTATION` on any mutation. No consumer may silently fall back
to a legacy CopySet or approve copy automatically.

The image copy-free lanes still pass through the adapter and require explicit
readiness, provenance, and safety proof. They are not an unguarded shortcut.

## Proof set

Focused proof lives in:

- `tests/unit/test_copy_execution_resolver.py` — all eleven lanes, flag-off
  compatibility, fail-closed validation, immutable dialogue, and durable
  handoff identity;
- `tests/unit/test_copy_blueprint_v2_contract.py` and
  `tests/unit/test_copy_lane_adapters.py` — schema, evidence, binding, and
  projection contracts;
- `tests/unit/test_copy_architecture_v2_legacy_safety.py` — no provider/credit
  behavior and legacy safety;
- `tests/api/test_copy_architecture_v2_api.py` — read-only matrix/status API;
- `dashboard/src/components/copywriting/CopyArchitectureV2LaneCard.test.tsx`
  — honest flag-off, blocked flag-on, and copy-free UI receipts.

Phase 4, if separately authorized, is the rollout/selection UX and production
enablement work for all eleven lanes. This Phase 3 change does not turn the
feature flag on.
