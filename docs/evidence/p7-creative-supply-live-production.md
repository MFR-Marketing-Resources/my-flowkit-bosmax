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
