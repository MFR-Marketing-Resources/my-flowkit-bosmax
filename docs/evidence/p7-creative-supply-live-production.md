# P7 Creative Supply Factory and Live Production Activation

Mission: `BOSMAX-P7-CREATIVE-SUPPLY-LIVE-PRODUCTION-ACTIVATION-20260730`

## Source scope freeze

Frozen before implementation at base
`eb4635b22ddd874a7b9ef3a2c6fbf43845277de6`.

Authorized source scope:

- `docs/MODULE_STATUS.yaml`
- `agent/db/schema.py`
- `agent/db/creative_supply_crud.py`
- `agent/services/creative_supply_delta_service.py`
- `agent/services/creative_supply_factory_service.py`
- `agent/api/creative_supply.py`
- `agent/main.py`
- `dashboard/src/api/creativeSupply.ts`
- `dashboard/src/components/CreativeSupplyFactoryPanel.tsx`
- `dashboard/src/components/CreativeSupplyFactoryPanel.test.tsx`
- `dashboard/src/pages/CreativeProductionStudioPage.tsx`
- `scripts/p7-creative-supply-factory.py`
- `scripts/p7-canonical-delta.py`
- `tests/unit/test_creative_supply_delta.py`
- `tests/unit/test_creative_supply_factory.py`
- `tests/unit/test_creative_supply_migration.py`
- `tests/api/test_creative_supply_api.py`
- `docs/evidence/p7-creative-supply-live-production.md`

Explicitly excluded:

- `agent/services/product_knowledge_service.py`
- `agent/services/ai_copy_provider_adapter.py`
- P5.8 authority and P6 generation-core behavior
- canonical database mutation before merged canonical deployment
- DOM-driven Google Flow generation
- P8, Postiz, publishing, and performance analysis

## Frozen authority

- P6 accepted base: `eb4635b22ddd874a7b9ef3a2c6fbf43845277de6`
- P5.8 launch cohort: 438 products
- Cohort SHA-256:
  `15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f`
- Text provider ceiling: 120 billable requests including retries
- Media ceiling: two initial hero videos, up to two image/poster attempts only
  behind a verified lane, and one replacement only after genuine QA rejection
- Stable delegated reviewer identity: `codex-p7-reviewer`

## Implementation invariants

- One provider request covers exactly one product, one approved angle, and one
  component type.
- AI candidates remain `COMPONENT_REVIEW_REQUIRED` until a content-hash-bound,
  reasoned review decision is persisted.
- No automatic retry. A single explicit retry is allowed only after a recorded
  transient transport failure.
- Fewer valid provider items create a later deficit task; they are not retried.
- Deterministic composition never calls a provider and does not persist the
  whole theoretical capacity.
- Product-only 9:16 F2V anchors embed the approved physical source at native
  dimensions. They remain pending until an actual, output-hash-bound review
  proves identity, label, scale and source-region pixel integrity.
- Anchor upload reuses the existing Flow upload helper and exact zero-credit
  confirmation. It never submits a generation request and cannot widen the
  five-attempt media ceiling.
- Isolated results move to canonical through a bounded, row-hash-guarded,
  additive/update-only transaction. The importer refuses insert collisions,
  update drift, asset hash mismatch, cohort drift and database replacement.
- Pause, resume, failures, review lineage, provider-call accounting, and the
  remaining budget are durable in the isolated/canonical database binding.
- Live media remains exclusively behind the P6 ADR-007 execution door and its
  exact confirmation, dry-run, lane, lease, retrieval, registration, and QA
  gates.

## Evidence status

This document is the tracked index. Runtime exports, candidate ledgers, DB
hashes, provider receipts, media-attempt ledgers, screenshots, and browser
readbacks are retained in the mission evidence directory outside the
repository so they cannot alter source authority.

## P7-R1 remediation scope ledger

Mission:
`BOSMAX-P7-R1-PROVIDER-REMEDIATION-READ-MODEL-RECOVERY-20260730`

Frozen at base `5f9938e6a9ee67ad0c3da1165e284b57083872fc` before
implementation. The only authorized changed files are:

- `docs/evidence/p7-creative-supply-live-production.md`
- `agent/db/schema.py`
- `agent/db/creative_production_crud.py`
- `agent/services/creative_production_plan_service.py`
- `agent/services/creative_production_scheduler_service.py`
- `agent/db/creative_supply_crud.py`
- `dashboard/src/api/creativeSupply.ts`
- `dashboard/src/components/CreativeSupplyFactoryPanel.tsx`
- `tests/unit/test_creative_production_migration.py`
- `tests/unit/test_creative_production_orchestrator.py`
- `tests/unit/test_creative_supply_migration.py`
- `tests/api/test_creative_supply_api.py`

The scope is limited to:

- durable, additive provider-project/correlation/job-observation evidence for
  P6 generation attempts;
- zero-credit automatic reconciliation of already-submitted attempts;
- stable mapping of the existing ADR-007 generation door's terminal provider
  and retrieval states;
- a lightweight creative-supply run summary projection on an independent
  read-only SQLite connection;
- truthful dashboard summary typing and focused regression proof.

Explicitly excluded are generation-door rewrites, prompt or asset mutation,
new dependencies, destructive migrations, DeepSeek calls, new copy or angles,
MWCB/image/poster submissions, P8 work, and any second Bosmax retry.

Rollback is a source revert followed by the official runtime restart. The
database change is additive only; its four new attempt-observation columns may
remain inert without changing pre-existing rows or lifecycle state.

## P7-R1 local root-cause and correction evidence

### P7-B1

Original Bosmax lineage:

- plan: `p6plan_dbc569a434e64986b9f0`
- item: `p6item_90d76b55f40037d4b5eacb08`
- attempt: `p6attempt_ea10f66a030f44ae8bb1`
- local generation job: `g_efa8c554ca34`
- payload SHA-256:
  `68d75e7ea0c59ea593d3bf25f425fc171c79f6a8573ab51ac4acbd03a71f38f4`
- model/duration/mode: `Veo 3.1 Lite` / `8` / `F2V`

The `g_*` identity is generated by `make_video.start_generate` and was only a
process-local handle. P6 stored that handle immediately, but did not durably
store the bound Flow project, generation correlation anchors, credit state,
candidate observations, or terminal job snapshot. The scheduler also did not
reconcile `PROVIDER_JOB_KNOWN` attempts automatically, and its manual
reconciliation did not map `RENDER_NOT_MATERIALIZED`,
`STALE_OR_FOREIGN_CANDIDATES_ONLY`, or
`GENERATED_BUT_UNRETRIEVED`. A runtime restart therefore destroyed the only
complete evidence capable of distinguishing provider non-materialization from
retrieval/correlation failure. This is the proven local reconciliation defect;
it does not retroactively convert the original incomplete evidence into a
provider-side verdict.

The correction adds four idempotently migrated attempt columns for project,
correlation, compact provider snapshot and observation time. The zero-credit
scheduler tick now reconciles submitted attempts even when new live execution
is uncertified. Existing generated-artifact recovery remains first authority,
then live job state, then the durable snapshot. Terminal rendering,
correlation, retrieval and cancellation states now map to explicit durable P6
states without resubmitting.

Authenticated browser history places the controlled Flow tab on project
`c436897c-0305-4929-9a15-a72a6dab7351` at `2026-07-30T03:00:30.666Z`, adjacent
to the original `02:59:22Z` submission. Its current media surface contains only
the two MWCB outputs (`d79662fc-8be6-4563-aff9-844a1e8e60d6` and
`31d4e535-4afa-4d16-9795-c1efb6d86799`), not a Bosmax artifact. This proves the
late-artifact/duplicate check for the currently attributable project, but not
the original external terminal reason because the pre-fix provider snapshot
was lost.

### P7-B2

`creative_supply_crud.list_runs()` previously queued `SELECT *` on the one
global `aiosqlite` worker and hydrated roster, angle-plan and target-policy JSON
although the panel selector consumes only run identity, mission and state.
A deterministic blocker held that shared worker for 750 ms: the old list call
timed out at the 200 ms test boundary. The corrected endpoint opens a
short-lived read-only SQLite connection and selects only authoritative summary
columns. Under the same blocked-worker condition it returned the canonical one
run in 6.51 ms with the required identity, state, timestamps, budget values and
roster/cohort hashes.

### Local validation

- P7/P6/API/retrieval/classification focused set: `171 passed`
- complete dashboard Vitest set: `58 files`, `482 passed`
- production dashboard build: PASS
- `npx tsx scripts/mandor-check.ts`: PASS, domain `workspace`
- dependency-cruiser changed frontend graph: 3 modules, 2 dependencies, zero
  violations
- ADR-007 static and F2V asset-picker harness: PASS, 22 fixture cases
- `scripts/verify-gate.ps1`: build, Vitest and Mandor PASS; the backend smoke
  aggregate remains red only on the base-reproduced
  `AVATAR_REGISTRY_SELECTION_REQUIRED` legacy compiler test. The identical
  test fails at base `5f9938e6a9ee67ad0c3da1165e284b57083872fc`; no P7-R1
  file participates in that failure.

No provider, DeepSeek or media submission occurred during implementation and
local validation. Canonical deployment and the one-attempt decision gate remain
runtime evidence steps after merge.
