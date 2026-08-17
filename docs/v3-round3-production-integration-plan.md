# Macro Round 3 — Production Integration Plan (execution-ready)

Status: **Phase 1 (schema foundation) landed in this branch. Phases 2–N specified below, not yet implemented.**
Branch: `feat/storyboard-landbank-v3-prod-integration` · Base: `main` (`2023870…`, includes Round 2 #788 + PR #790).

This plan is the durable output of a full architecture discovery pass. It exists so the
production spine can be implemented safely and quickly without re-deriving the integration
points. **Authority boundary (never bypass): V3 APPROVED → V2 PRODUCTION_VALID → P6.**
P6 must never execute raw V3 text; production copy authority is V2 only.

## PR #790 regression law (must hold in every phase)
Historical status alone must NEVER authorize activation/materialization. Current eligibility
is fail-closed on `current_authority_activation_allowed === true` (FE) /
`get_blueprint_current_authority_validation(...).activation_allowed` (BE:
`status=="PRODUCTION_VALID" AND ready_for_copy AND no blockers AND no lineage mismatches AND taxonomy fingerprint present`).
The materializer MUST route the V2 approval through the existing fail-closed boundary
(`approve_blueprint`) so stale truth/evidence/formula drift blocks materialization automatically.

---

## Phase 1 — Schema (DONE, tested: `tests/unit/test_storyboard_landbank_v3_migration.py`, 4 passed)
`agent/db/schema.py` `V3_ROUND3_SCHEMA`, wired into `init_db()`:
- `materialization_link_v3` — immutable/append-only; `UNIQUE(materialization_digest)` (idempotency) + partial unique `(projection_id, projection_revision, materializer_version) WHERE status='MATERIALIZED'`; FKs → product, `master_storyboard_v3(master_id,revision)`, `duration_projection_v3(projection_id,revision)`, `v3_human_approval_receipt`, `copy_blueprint_v2(blueprint_id,revision)`.
- `production_copy_supply_manifest_v3` (PK manifest_id,revision) + `manifest_item_v3` — manifest freeze-immutable when `FROZEN/ALLOCATED`; item `UNIQUE(manifest,item_index)` and `UNIQUE(manifest, v2_blueprint_id, v2_revision)` (no exact dup per revision).
- `landbank_usage_v3` — append-only usage ledger.

## Phase 2 — V3→V2 deterministic materializer (PRIMARY; Sec 1–3)
New module `agent/services/storyboard_landbank_v3_materializer.py` (provider-free, deterministic).
`MATERIALIZER_VERSION = "v3-materializer-v1"`.

`async def materialize_projection(*, master_id, projection_id, receipt_id, actor_id, materialized_by) -> MaterializationResult`:
1. **Load** APPROVED `master_storyboard_v3` rev + APPROVED `duration_projection_v3` rev + `v3_human_approval_receipt` (via `V3CopyFactoryRepository` / round2 `verify_receipt(receipt_id)` at `storyboard_landbank_v3_round2.py:1897`; receipt→master via `_approval_receipt_for_master:1410`).
2. **PRE-MAT revalidation (fail-closed on any mismatch)** — compare/verify:
   receipt_digest (recompute `approval_receipt_digest`), master `exact_content_digest`, projection `exact_projection_digest`,
   product truth CURRENT snapshot id/version/digest (via `copy_register_v2_service._product_truth_rows` + `_truth_gate` — must be empty),
   formula id/version + `is_production_formula`, evidence current ids/digests (`_facts_for_refs`), wps authority digest,
   duration budget, stage lineage (master stage keys == projection `master_stage_keys_json`), Hook/Body-Core/CTA completeness + CTA final placement,
   claim-safety (claim-bearing stages cite approved facts), approval scope, exact text identity (projected_text_digest per slice).
3. **Build V2 stages** from projection `per_block_slices_json` (`V3ProjectedStageSlice`) → ordered `FormulaStage`:
   use EXACT `projected_text` (for AI_ASSISTED/HUMAN_EDITED do NOT reconstruct from master); source `bridge.entry/exit/continuity_requirements`, `claim_bearing`, `formula_stage_key`, `semantic_role`, `fact_refs`(evidence) from the master `V3FormulaStage`/`V3ComponentStageSegment` matched by `master_stage_key`. Preserve order, digests.
4. **Construct DRAFT `CopyBlueprintV2`** with `product_truth_lineage == copy_register_v2_service._lineage(product, snapshot)` (live), evidence envelope from step 2, `formula_version` from authority, `target_duration_seconds` = projection target, provenance entry `{"key":"materialization_source","value":{"approval_source":"V3_HUMAN_APPROVAL_CARRY_FORWARD","master_id","projection_id","receipt_id"}}`.
5. **Persist DRAFT** via `copy_register_v2_service._insert_blueprint(draft)`.
6. **Approve via the fail-closed boundary** — `copy_register_v2_service.approve_blueprint(blueprint_id, approved_by=receipt.approved_by, semantic_review=<carry-forward>, readiness_proof=<carry-forward>)` → PRODUCTION_VALID. This re-runs live `_truth_gate`, `_facts_for_refs`, requires `lineage == _lineage(live)`, and `validate_copy_blueprint_v2` — so any drift fails closed (Sec 22).
7. **Write `materialization_link_v3`** idempotently (see Phase 3).
8. Do NOT globally activate (Sec 5 — activation stays interactive-only; P6 uses manifest items).

### Approval carry-forward (Sec 2) — verified propagation, not re-approval
The V3 `v3_human_approval_receipt.checklist` (7 bools, all true, `automatic_approval=0`) IS the recorded human decision. Map deterministically:
- `SemanticReviewProof(decision="APPROVED", reviewer=receipt.approved_by, rationale=receipt.rationale, reviewed_at=receipt.created_at)`.
- `ProductionReadinessProof(readiness_validated, provenance_validated, safety_validated, bridge_validated, duration_validated = the corresponding checklist bools)` — all must be true or BLOCK.
- Provenance `approval_source = V3_HUMAN_APPROVAL_CARRY_FORWARD`. If ANY digest/authority changed vs the receipt → BLOCK (require new V3 revision/review). No new human action; no fabrication.

## Phase 3 — materialization_link (Sec 3) idempotency
`materialization_digest = sha256(canonical_json({materializer_version, product_id, master_id/rev/digest, projection_id/rev/digest, receipt_id/digest, product_truth_snapshot_digest, formula_id/version, ordered projected stage text digests}))`.
Insert with `INSERT ... ON CONFLICT(materialization_digest) DO NOTHING` then SELECT → same input returns the same link + same V2 blueprint (no dup rows). If the projection revision already has a `MATERIALIZED` link (partial-unique), return it (idempotent). New projection revision → new link; old marked `SUPERSEDED` (the one allowed status transition per the link trigger).

## Phase 4 — Materialization UX (Sec 4)
`dashboard/src/pages/StoryboardLandbankV3Page.tsx` `StoryboardCard` line ~131–134 (currently prints `v2_materialization`/`p6_status` literals): replace with a `Badge` (`statusTone`) for NOT_MATERIALIZED/MATERIALIZED/STALE/BLOCKED + a **Materialize for Production** button beside "Receipt recorded". Add `materializeForProduction()` / `fetchMaterializationStatus()` to `dashboard/src/api/storyboardLandbankV3Round2.ts`. Bounded bulk over clean approved projections; never auto-materialize on page open. Backend widens the `V3LandbankItem.v2_materialization`/`p6_status` fields (round2 `_approve_with_receipt` return) to real enums computed from `materialization_link_v3` + live authority.

## Phase 5 — Production Copy Supply Manifest (Sec 6–8)
Service `agent/services/production_copy_supply_service.py`: `build_manifest(product_id, plan_scope, duration_mix, requested_count, reuse_policy, ...)` selecting ONLY items that are V3-approved + V2-materialized + PRODUCTION_VALID + current (revalidate each via `get_blueprint_current_authority_validation`). Reject DRAFT/REVIEW/stale/invalid/dup-outside-reuse. `manifest_digest` over the ordered authority digest set. Freeze → immutable (schema trigger enforces). Partial failure returns `{valid_count, blocked_count, blocked_item_ids, reason_codes}` (Sec 15).

## Phase 6 — Usage ledger + reuse/fatigue (Sec 9–11)
Append-only writes to `landbank_usage_v3` at MANIFEST_SELECT/P6_ALLOCATE/COMPILE/QUEUE_ADMIT/PROVIDER_START. Versioned reuse policy object `{policy_version, exact_reuse: bool, semantic_fatigue: {...}}` — default: no EXACT_REUSE of the same Duration Projection within one P6 plan; cross-plan reuse allowed by policy. NO legacy `REUSE_CAP=15`. Advisory fatigue signals (angle/storyline/hook/body/CTA/evidence concentration, exact reuse, near-dup) from existing V3 novelty + ledger — advisory only, never a production gate.

## Phase 7 — P6 per-item selection + revalidation (Sec 5,12–15)
Today P6 copy = product-global `copy_execution_authority_v2 (product_id, lane)` resolved at compile (`creative_production_compile_service._compile_video/_compile_poster` → `resolve_persisted_copy_execution_binding`). Round 3: bind each P6 item to an explicit `manifest_item_v3` → exact V2 blueprint revision + approval snapshot + text. Add per-item copy ref to the P6 item/package; resolve via manifest item, NOT the global pointer. Revalidate at compile + queue admission + paid-start boundary (fail-closed BEFORE provider; zero credit). One invalid item blocks only itself (Sec 15). P6 must NOT churn the product-global active pointer (Sec 25).

## Phase 8 — Capacity + Production Studio UX + fill-capacity (Sec 16–19)
Distinct layers: SEMANTIC_CAPACITY / PROJECTION_CAPACITY / EXECUTABLE_COPY_CAPACITY / PRODUCTION_CAPACITY (never collapsed; PRODUCTION bounded by copy × treatment × lane/window). Production Studio Copy Supply section after `p6-v2-copy-authority-list` (`CreativeProductionStudioPage.tsx`) reusing `CopyArchitectureV2LaneCard` readiness pattern; actions Review Supply / Open Copy Register / Fill Capacity / Materialize / Build-Refresh Manifest. FILL_CAPACITY routes to the existing V3 AI Copy Assistant `mode="FILL_CAPACITY"` (no auto-gen; new supply still flows DRAFT→Review→Human Approval→Materialize→Manifest). Lazy allocation — never pre-materialize the combination universe.

## Phase 9 — Proofs + regression (Sec 20–27)
- FAST54 idempotent materialization; ≥10k lazy scale sim (bounded mem/queries, stable seed/digest, pagination, measured timings — no 10k physical copy rows).
- Authority-invalidation fail-closed (truth/evidence/formula/projection/receipt/V2 current-authority each). Partial-failure/reconciliation (link write interrupted, manifest partial, P6 alloc then revalidation fail → deterministic retry, no orphans/dups). Concurrency/idempotency (one canonical result or deterministic conflict).
- Global-activation regression + PR #790 preservation (stale historical PRODUCTION_VALID → materialization/activation disallowed). Creator-lane resolution regression for all required lanes. No legacy `copy_set`/`copy_component`/`poster_copy_set` fallback.

## Harness (Sec 28–30)
- Backend tests: isolated pytest temp DB (conftest autouse `db_setup`), reuse `_seed_truth`/`_seed_malay_master`/`human_approve` from `tests/unit/test_storyboard_landbank_v3_round2_copy_register.py`; add Round 3 test files to `scripts/verify-gate.ps1 $SmokeTests`; register every new file in `docs/MODULE_STATUS.yaml owned_paths`.
- Disposable UAT: `FLOW_AGENT_DIR=<temp> API_PORT=8399 WS_PORT=8398 V3_ROUND2_FAKE_PROVIDER=1 GLA_RELOAD=0 python -m agent.main` (SPA from worktree `dashboard/dist`). Never touch canonical `flow_agent.db` / `:8100`. Real browser via `javascript_tool` DOM/`fetch` (in-app pane runs headless — screenshots unavailable).

## Do-not-merge
This is a review branch. Sync latest main before final handoff; wait for remote CI on the exact final head; do not merge.
