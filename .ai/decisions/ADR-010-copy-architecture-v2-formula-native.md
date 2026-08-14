<!-- markdownlint-disable MD013 -->

# ADR-010: Copy Architecture V2 / Formula-Native Copy System

> Active-runtime cutover note (2026-08-14): ADR-011 supersedes this ADR's
> default-off and selectable-legacy rollout policy for active Copy Register and
> production consumers. The formula, evidence, approval, immutability, lineage,
> compiler, and fail-closed invariants below remain in force.

- Status: ACCEPTED ARCHITECTURE — PHASE 0 DOCUMENTATION GATE
- Date: 2026-08-13
- Owner decision: controlled additive migration
- Baseline: `origin/main` at `3de11b7087e125c6c29e6aa98449a50b32dff4ad`
- Related decisions: ADR-007, ADR-008, and the existing Product Truth and
  copy-component architecture contracts

## 1. Decision summary

BOSMAX will introduce a first-class formula-native copy contract named
`CopyBlueprintV2` through a controlled additive migration. The migration will
add a V2 domain contract, a parallel V2 execution path, explicit adapters, a
feature flag, staged consumer migration, a bounded pilot, and an operational
rollback switch.

The existing legacy Copy Set and compiler path remain intact while the V2 flag
is off. Existing rows are not reinterpreted as V2, and the legacy compiler is
not silently changed to consume V2 fields. Phase 0 creates this decision record
only; it adds no runtime code, schema, database data, provider call, approval,
or production binding.

The target flow is:

```text
Product Truth
  → Evidence Registry
  → Angle + Objective
  → Explicit Formula
  → CopyBlueprintV2
  → Formula / Claim / Bridge Validation
  → Human Approval Snapshot
  → Deterministic Compiler Binding
  → Production Binding
  → Runtime Prompt
```

The ordered formula-stage list is the V2 source of truth. Hook, body, and CTA
are derived projections for presentation or compatibility only. A flat
projection must never be used to reconstruct a V2 blueprint.

## 2. Context and authority

The repository already has several governed copy seams:

- `agent/models/copy_set.py` defines the legacy, explicitly approvable flat
  Copy Set contract.
- `agent/authority/copy_formula_registry.py` exposes the repository formula
  contracts and maps them to compiler-safe families.
- `agent/services/copy_component_service.py` and the component authoring and
  composer services provide an additive component pool and deterministic
  composition seam.
- `agent/services/copy_binding_service.py` is the controlled legacy Copy Set
  to canonical compiler binding door.
- `agent/services/copywriting_readiness_service.py` composes Product Truth,
  grounding, Copy Set, formula, claim, and validity signals into a shared
  readiness payload.
- `agent/services/canonical_prompt_compiler.py` remains the final renderer for
  engine-facing prompts and the mechanical safeguard authority.
- `agent/db/schema.py` already creates the legacy `copy_set`, additive
  `copy_component`, Product Truth snapshot, and separate poster-copy domains.

These seams are preserved. This ADR does not authorize a second ungoverned copy
store, an in-place replacement of `copy_set`, or a rewrite of the canonical
compiler.

Authority order for this decision is:

1. `AGENTS.md`, `.ai/status/CURRENT_STATE.md`, and `.ai/contracts/*`;
2. ADR-007 for the API-first generation door and its locked runtime paths;
3. this ADR for V2 copy authorship and migration boundaries;
4. ADR-008 for canonical compilation, source-mode law, WPS/timing,
   safety/leakage checks, deterministic rendering, no-overlay law, and final
   output authority;
5. repository formula authority/YAML for registered formula definitions;
6. workbook material as research/input only, never runtime authority.

If a later implementation discovers a conflict with a higher authority, it must
stop and record the conflict. It must not silently resolve the conflict in
code.

## 3. Relationship to ADR-008

This ADR explicitly supersedes only the copy-authorship portion of ADR-008
Decision 6 / Section 6: the behavior that treats structured
`angle`/`hook`/`subhook`/`USP`/`CTA`/`formula` fields as a secondary flat copy
helper for final copy authorship.

For V2, persuasion authorship belongs to `CopyBlueprintV2` and its ordered
formula stages. The flat legacy Copy Set remains supported for compatibility
and remains unchanged when V2 is off. It is not the source of truth for a V2
blueprint.

The following ADR-008 principles remain fully in force:

- `agent/services/canonical_prompt_compiler.py` is the only final
  engine-facing prompt renderer.
- Source-mode law remains explicit.
- WPS profiles, duration budgets, timing safeguards, and block allocation
  remain compiler-owned mechanical validation.
- Safety and leakage checks remain fail-closed.
- Rendering remains deterministic.
- NO_OVERLAY remains the default law.
- Final output authority remains with the canonical compiler.

No other part of ADR-008 is superseded.

## 4. Ownership contract

### 4.1 Product Truth

Product Truth owns factual product information and its approved provenance. It
owns facts such as product identity, features, benefits, allowed claims,
ingredients or composition where applicable, usage, warnings, limitations, and
physical state.

Product Truth does not own persuasion order, formula-stage text, component
selection, or runtime prompt rendering.

### 4.2 Evidence Registry

The Evidence Registry owns stable fact identity, fact approval state, snapshot
lineage, and claim lineage. Phase 1 may implement snapshot-scoped stable fact
IDs during Product Truth ingestion, but the model must support promotion to a
first-class registry without changing the V2 blueprint contract.

The registry must distinguish semantic identity from the exact wording of a
fact. A wording correction for the same semantic fact preserves `fact_id` and
changes `text_digest`; it does not silently create or repair lineage.

### 4.3 CopyBlueprintV2

`CopyBlueprintV2` owns:

- persuasion and the chosen objective and angle;
- explicit formula identity and formula version;
- the ordered formula-stage list;
- authored hook, body, CTA, and other stage text;
- component selection and formula-stage continuity;
- evidence references attached to claims;
- validation results required for approval;
- the immutable approved execution text;
- the source Product Truth snapshot and full provenance;
- the revision and supersession relationship.

### 4.4 Canonical compiler

The canonical compiler remains the final engine-facing renderer for all
non-copy prompt sections and mechanical safeguards. It may validate and
allocate; it is not a persuasion author.

The compiler may:

- validate requested duration and WPS;
- allocate approved stage blocks without changing their text;
- validate formula-stage placement and bridge continuity;
- scrub leakage and run claim and safety checks;
- reject invalid or non-fitting output;
- produce deterministic final prompt text from the approved binding.

The compiler must never silently:

- trim, rewrite, paraphrase, or expand approved copy;
- insert new copy or delete a formula stage;
- replace an approved component or formula;
- silently fall back to HSO;
- silently fall back from invalid V2 to legacy copy.

If approved V2 text cannot fit the requested duration budget, compilation fails
closed with `COPY_DURATION_FIT_FAILED`. A new authoring variant and a new human
approval are required.

## 5. M1–M5 locked decisions

### M1 — bounded validator/allocator compiler

The compiler is a bounded validator and allocator, not the persuasion author.
Approved copy is an immutable input artifact. Mechanical allocation may select
where an already approved stage is placed, but it may not change the stage's
words, formula, component, or stage count.

### M2 — stable evidence identity

Every claim-bearing stage uses an evidence reference with at least:

```json
{
  "snapshot_id": "product-truth-snapshot-id",
  "fact_id": "stable-fact-id",
  "text_digest": "sha256-of-approved-fact-text",
  "fact_kind": "benefit"
}
```

`hash(text)` is not a durable fact identity. A digest detects wording drift; it
does not identify the fact. A missing fact, stale snapshot, digest mismatch,
invalid product lineage, or unapproved fact blocks production validity.

### M3 — repository formula authority

The repository authority/YAML and its checked-in formula registry are the
runtime formula authority. The workbook is research/input material and cannot
register a runtime formula.

V2 requires an explicit formula and formula version. Unknown, unregistered,
unsupported, or ambiguous formulas fail closed. V2 must not use the legacy
normalization behavior that silently resolves empty or unknown input to HSO.
HSO remains available only where the legacy path already permits it, and that
legacy behavior is not changed by this ADR.

### M5 — default consistency

Legacy PAS/HSO behavior, public signatures, return shapes, and golden output
remain byte-stable while V2 is off. No legacy default is changed during this
migration.

V2 has no implicit formula default. A V2 caller must provide an explicit
registered formula, and the binding must carry its formula version.

## 6. CopyBlueprintV2 logical contract

The physical module and table names will be finalized in Phase 2 after the
repository schema and persistence conventions are inspected. The logical
contract below is locked and must be represented without weakening its
invariants.

### 6.1 Blueprint envelope

```text
CopyBlueprintV2
├── version: "2"
├── blueprint_id: stable identifier
├── product_id: Product Truth product identity
├── copy_set_id: V2 copy-set identity (not an implicit legacy upgrade)
├── revision: positive integer
├── status: lifecycle status
├── formula_id: explicit registered formula identity
├── formula_version: authority version/digest
├── objective: { objective_id, definition }
├── angle: { angle_id, definition }
├── stages: ordered FormulaStage[]
├── component_refs: selected component identities and versions
├── evidence_refs: all references used by claim-bearing stages
├── target_duration_seconds: requested production duration
├── wps_profile: selected governed WPS profile and version
├── estimated_word_count: authoring-time estimate
├── approval_snapshot: immutable approval artifact or null before approval
├── approved_execution_text: immutable approved stage text or null before approval
├── provenance: authoring, source, model, and review lineage
├── product_truth_snapshot: approved snapshot identity and digest
├── supersedes: prior blueprint/revision or null
├── created_at: creation timestamp
├── approved_at: approval timestamp or null
├── approved_by: human approver identity or null
└── production_binding: binding lineage/state or null
```

`copy_set_id` identifies the V2 copy-set contract. A legacy `copy_set_id` may
be stored as a separate explicit compatibility relation, but a legacy row is
never relabeled or parsed as V2 merely because it has flat fields.

### 6.2 Status model

The V2 status vocabulary is:

```text
DRAFT
→ REVIEW_REQUIRED
→ APPROVED
→ PRODUCTION_VALID
→ SUPERSEDED
```

Any state may resolve to `BLOCKED` when a required gate is missing or invalid.
`STALE` is a derived blocking condition for an approved artifact whose upstream
authority has changed. `REVIEWED` is a review result, not production approval;
implementations may expose it in the UI but must not treat it as approved.

`PRODUCTION_VALID` means the immutable approved artifact currently passes
Product Truth, evidence, formula, claim, safety, bridge, duration, WPS, and
binding checks. It does not authorize a provider call by itself.

### 6.3 FormulaStage

Each stage must preserve the following data:

```text
FormulaStage
├── stage_key: stable formula-specific key
├── order: unique zero- or one-based order, defined by the contract
├── authored_text: text submitted for review
├── semantic_role: problem, agitate, solution, hook, story, offer, etc.
├── component_ref: component identity/version or null for direct authoring
├── formula_stage_key: registered formula relationship
├── bridge: { entry, exit, continuity_requirements }
├── claim_bearing: boolean
├── fact_refs: EvidenceReference[]
└── validation: deterministic stage-level result and error codes
```

The formula registry defines required stages and order. The validator rejects
missing stages, duplicate order, duplicate stage keys, unknown stage keys,
formula mismatches, and bridge discontinuity. A body stage is not a synonym for
`SUBHOOK`; stage semantics are formula-specific.

### 6.4 EvidenceReference

The minimum reference is:

```text
EvidenceReference
├── snapshot_id
├── fact_id
├── text_digest
└── fact_kind
```

The persisted implementation must also retain enough product/source lineage
to prove that the fact belongs to the blueprint's `product_id`, approved
Product Truth snapshot, and applicable fact kind. It must not infer a reference
by hashing the copy text.

Validation rules:

1. Every claim-bearing stage has at least one valid reference.
2. A benefit, USP, product performance statement, or other claim cannot pass
   without approved evidence.
3. `snapshot_id` must be the approved, current Product Truth snapshot required
   by the binding context.
4. `fact_id` must exist for the snapshot and product.
5. `text_digest` must match the approved fact text exactly under the registry's
   canonicalization rules.
6. A stale, missing, mismatched, or unapproved reference blocks production
   validity.
7. Wording correction for the same semantic fact preserves `fact_id` but
   changes `text_digest`; the changed reference requires revalidation and
   reapproval.

### 6.5 ApprovalSnapshot

An approval snapshot captures the exact artifact a human approved:

```text
ApprovalSnapshot
├── approval_snapshot_id
├── blueprint_id
├── revision
├── blueprint_digest
├── formula_id
├── formula_version
├── product_truth_snapshot_id
├── stage_text_digests
├── approved_execution_text
├── evidence_digest
├── approved_by
└── approved_at
```

After approval, the snapshot and approved execution text are immutable. Any
change to text, formula, evidence, component, bridge, objective, angle,
duration, WPS profile, or relevant provenance creates a new revision with a new
approval snapshot. An update-in-place operation on an approved artifact is
forbidden.

### 6.6 ProductionBinding

Every V2 production binding must retain:

```text
ProductionBinding
├── blueprint_id
├── revision
├── formula_id
├── approval_snapshot_id
├── evidence/provenance digest
├── compiler_version
├── feature_flag_state
├── bound_at
└── binding_status
```

The binding points to the approved snapshot and never reconstructs it from a
flat legacy projection. Binding validation rechecks staleness and evidence at
the production boundary.

## 7. Invariants and forbidden behavior

### 7.1 Source-of-truth invariants

- The ordered formula-stage list is the only V2 copy source of truth.
- Hook/body/CTA are projections and may be incomplete or lossy when presented
  to a legacy consumer; they cannot be used to recreate V2 stages.
- A formula is an executable authority relation, not a decorative label.
- Every V2 blueprint has an explicit formula and formula version.
- V2 and legacy fields may not be silently mixed in one execution path.

### 7.2 Approval and lineage invariants

- Approval is a human action and is never implied by creation, AI Assist,
  component generation, migration, or successful compilation.
- Approved V2 text is immutable.
- A changed input creates a new revision and requires validation and approval.
- Existing legacy rows remain legacy, including rows with approved status.
- No automatic legacy-to-V2 upgrade, stage reconstruction, or mass
  auto-approval is permitted.
- Product Truth and evidence lineage are explicit and revalidated at each
  production boundary.

### 7.3 Compiler invariants

- The compiler validates and allocates; it does not author persuasion.
- The compiler does not mutate the input blueprint or approval snapshot.
- A duration or WPS overflow is an error, not permission to rewrite copy.
- `COPY_DURATION_FIT_FAILED` is returned for approved-copy duration overflow.
- Invalid V2 never falls through to HSO or legacy copy.
- The canonical compiler remains the sole final engine-facing renderer.

### 7.4 Safety and diversity invariants

- Claim safety and leakage checks remain fail-closed.
- Claim-bearing stages without valid evidence are blocked.
- Formula-stage bridge continuity is validated as a first-class constraint.
- Existing dedupe, near-duplicate, uniqueness, and reuse-cap rules remain in
  force.
- AI Assist can generate drafts only; it cannot approve or bind production.
- Workbook formulas cannot enter the runtime registry without an explicit
  repository authority change in a later decision.

## 8. Explicit adapters

V2 and legacy consumers are connected only through named adapters.

### 8.1 V2 native compiler binding

`V2CompilerBinding` consumes the native ordered stages, formula authority,
approval snapshot, and evidence references. It must emit a versioned binding
record and the canonical compiler input without flattening away the V2
lineage.

### 8.2 V2-to-legacy projection

`V2ToLegacyProjection` is allowed only for a consumer that is explicitly marked
legacy. Its output must include:

```text
adapter_version
source_version = "copy-blueprint-v2"
blueprint_id
revision
lossiness = explicit description/list of discarded V2 semantics
```

The projection may expose hook/body/CTA-compatible fields for old UI or API
shapes. It must never be fed back into V2 validation or used to recreate the
ordered stage list.

### 8.3 Legacy-to-V2 prohibition

There is no automatic `LegacyToV2` adapter. A legacy Copy Set can be used as a
human authoring input or compatibility display, but a V2 blueprint requires a
new explicit authoring/review path with formula stages, evidence references,
and a new approval snapshot.

## 9. Producer and consumer matrix

The following matrix is the migration contract. The named current seams remain
legacy or shared until their phase is explicitly landed.

| Producer or consumer | Current seam | V2 responsibility | Migration rule |
| --- | --- | --- | --- |
| Product Truth | Product intelligence snapshot and grounding services | Supply approved product facts and snapshot lineage | Product facts are never authored by CopyBlueprintV2 or compiler |
| Evidence Registry | New additive Phase 2 substrate over Product Truth facts | Stable fact IDs, digests, and claim lineage | Missing/stale/mismatched refs block V2 |
| Formula authority | `agent/authority/copy_formula_registry.py` and repository YAML | Define registered formula IDs, versions, stage order, and bridge semantics | V2 requires explicit registered formula; workbook is non-runtime input |
| Legacy Copy Set | `agent/models/copy_set.py`, copy-set APIs and persistence | Remains legacy authority and compatibility object | Do not remove fields or reinterpret rows as V2 |
| Formula components | `copy_component_service.py`, author service, composer service | Provide versioned component refs for V2 authoring | Components remain review-required until human approval |
| Readiness | `copywriting_readiness_service.py`, readiness APIs | Report semantic review, Product Truth, evidence, staleness, and V2 gates | Fail closed; no auto-approval or hidden fallback |
| Legacy binding | `copy_binding_service.py` | Continue explicit approved legacy binding; later add explicit V2 adapter | No consumer mixes legacy and V2 fields |
| Landbank | `copy_landbank_service.py` and workspace landbank APIs | Research/draft input only unless explicitly authored and approved into V2 | Never a silent V2 production source |
| Canonical compiler | `canonical_prompt_compiler.py` and `compile_ugc_video_prompt` | Render validated native V2 copy plus all non-copy sections | Flag off is byte-stable; flag on is fail-closed and immutable |
| Workspace package creation | `workspace_execution_package_service.py` and `workspace_generation_package_service.py` | Carry selected blueprint/revision and binding lineage | Use explicit legacy or V2 adapter; retain traceability |
| Hybrid/operator binding | `copy_binding_service.py` and package binding paths | Bind the selected approved revision | Store blueprint, formula, approval, evidence, compiler, and flag state |
| Poster copy | `poster_copy_set`, poster copy recommendation/fit services | Remains a separate poster-native domain | Must not enter video V2 compilation or be treated as video stages |
| Poster lane | `PosterAngleCopyStep` and poster UI/API surfaces | Consume only an explicit poster adapter where needed | No silent video CopyBlueprintV2 assumptions |
| Bulk/production | `bulk_generation_service.py`, `production_queue_service.py`, `creative_production_compile_service.py` | Revalidate binding at queue/compile boundaries | V2 failures remain visible and fail closed |
| Faceless/montage | faceless, montage, and scene orchestration services | Carry copy revision and native/legacy version lineage | Use explicit adapter; no flat reconstruction of V2 |
| Storyboard/planner | storyboard planner and prompt-package planners | Plan around the immutable selected revision | Planning/preview never spends provider credits |
| Copy Set Registry UI | `CopySetRegistryPage.tsx` | Show V2 revisions and lossless/legacy projections distinctly | Do not expose approve when gates are missing |
| Readiness UI | `CopywritingReadinessCard.tsx` | Show draft/reviewed/approved/production-valid/stale/superseded/blocked | Revalidation is explicit and auditable |
| AI Assist | AI Copy Assist API and UI | Generate reviewable V2 drafts only | AI Assist cannot approve or bind |
| Final prompt UI | all “Prepare final prompt” paths | Display selected blueprint/revision and validation result | No hidden fallback to legacy or HSO |

This matrix is completed and frozen before Phase 6 consumer migration begins.

## 10. Feature flags and telemetry

Phase 5 introduces the runtime controls. Until then, no V2 runtime path exists.

### 10.1 Required flags

| Flag/configuration | Default | Meaning |
| --- | --- | --- |
| `COPY_BLUEPRINT_V2_ENABLED` | `0` / OFF | Enables V2 binding for an explicit product/workspace scope |
| `COPY_BLUEPRINT_V2_SHADOW_MODE` | `0` / OFF | Runs read-only V2 validation/comparison without changing production binding |
| `COPY_BLUEPRINT_V2_PILOT_SCOPE` | empty | Explicit allowlist for the bounded pilot; empty means no pilot |

The implementation must provide product- or workspace-scoped control where the
repository configuration supports it. If scope cannot be resolved, the flag
fails closed rather than enabling V2 globally. Turning
`COPY_BLUEPRINT_V2_ENABLED` off is the operational rollback switch.

Flag-off isolation is strict: legacy callers do not read V2 fields, perform
V2 validation, or change legacy output. Flag-on isolation is also strict: an
invalid V2 blueprint returns a V2 error and is not hidden by a legacy fallback.

### 10.2 Telemetry

Every V2 validation, shadow comparison, compile attempt, binding, rejection,
and rollback records, at minimum:

- request/correlation identity;
- product/workspace scope;
- blueprint ID and revision;
- formula ID/version;
- approval snapshot ID;
- compiler version;
- feature-flag state and rollout scope;
- validation result and exact error code;
- adapter version/lossiness when an adapter is used.

Telemetry must not leak unapproved raw copy or evidence text. It must preserve
enough lineage to explain a rejection and support deterministic comparison.

## 11. Error contract

The following V2 error codes are stable machine-readable classifications. They
are fail-closed and must not be converted to a success response by fallback.

| Error code | Condition |
| --- | --- |
| `COPY_V2_FORMULA_REQUIRED` | V2 blueprint has no explicit formula |
| `COPY_V2_UNKNOWN_FORMULA` | Formula is not registered or version is unknown |
| `COPY_V2_FORMULA_VERSION_INVALID` | Registered formula version/digest does not match |
| `COPY_V2_STAGE_MISSING` | Required formula stage is absent |
| `COPY_V2_STAGE_ORDER_INVALID` | Stage order is not the registered deterministic order |
| `COPY_V2_STAGE_DUPLICATE` | Stage key or order is duplicated |
| `COPY_V2_STAGE_FORMULA_MISMATCH` | Stage relationship does not match formula authority |
| `COPY_V2_BRIDGE_INVALID` | Entry/exit continuity or bridge metadata fails |
| `COPY_V2_EVIDENCE_MISSING` | Claim-bearing stage has no required fact reference |
| `COPY_V2_EVIDENCE_NOT_FOUND` | Referenced fact does not exist |
| `COPY_V2_EVIDENCE_STALE` | Referenced Product Truth snapshot is stale |
| `COPY_V2_EVIDENCE_DIGEST_MISMATCH` | Fact text digest differs from the approved registry text |
| `COPY_V2_EVIDENCE_PRODUCT_MISMATCH` | Fact lineage belongs to another product |
| `COPY_V2_EVIDENCE_NOT_APPROVED` | Fact or snapshot lacks required approval |
| `COPY_V2_CLAIM_UNGROUNDED` | Claim, benefit, or USP lacks valid evidence |
| `COPY_V2_APPROVAL_MISSING` | Production binding has no human approval snapshot |
| `COPY_V2_APPROVAL_MUTATED` | Input no longer matches immutable approval snapshot |
| `COPY_V2_REVISION_INVALID` | Revision/supersession relationship is invalid |
| `COPY_V2_INVALID_STATUS` | Status cannot enter the requested boundary |
| `COPY_DURATION_FIT_FAILED` | Approved copy cannot fit the requested duration budget |
| `COPY_V2_WPS_FIT_FAILED` | Approved copy violates the selected WPS budget |
| `COPY_V2_LEAKAGE` | Forbidden metadata, formula, debug, or runtime leakage detected |
| `COPY_V2_SAFETY_FAILED` | Claim or content safety validation fails |
| `COPY_V2_INPUT_MUTATED` | Compiler or adapter mutated the V2 input |
| `COPY_V2_PRODUCTION_BINDING_INVALID` | Binding lineage or required metadata is incomplete |
| `COPY_V2_LEGACY_FALLBACK_FORBIDDEN` | V2 error was about to be hidden by legacy fallback |

Legacy error codes and legacy fallback behavior remain unchanged when the V2
flag is off.

## 12. Controlled migration and PR boundaries

The phases are sequential and each phase is a separate logical commit and PR.
No phase may combine schema, compiler, UI, migration, and production cutover.

### Phase 0 — ADR-010

This documentation-only PR establishes the final architecture, ownership,
invariants, matrices, flags, error contract, migration, rollback, and
acceptance gates. It must land remotely before production code is changed.

**Exit gate:** required-file, diff, markdown, branch, commit, push, PR, CI,
and remote-head proof.

### Phase 1 — Task A readiness remediation

Repair the intended UI/API revalidation path for stale approved copy. Enforce
semantic review and Product Truth lineage, keep stale copy blocked, calculate
production-valid status from actual gates, and preserve visible blockers.

**Exit gate:** stale, missing-review, missing-lineage, success/failure
revalidation, no-auto-approval, transition, and route-regression tests.

### Phase 2 — V2 schema and evidence substrate

Add V2 persistence and stable evidence references additively. Do not remove or
reinterpret legacy fields. Existing legacy rows remain legacy/needs-review when
stage data is unavailable.

**Exit gate:** schema, serialization, round trip, revisions, immutable approval
snapshot, evidence identity/digest/lineage, no automatic upgrade, and legacy
API compatibility tests.

### Phase 3 — shared V2 engine, validator, and adapters

Add native V2 validation, evidence and formula checks, bridge continuity,
duration/WPS checks, claim/safety checks, deterministic ordering, approval
snapshot checks, production binding checks, and explicit adapters.

**Exit gate:** invalid formula, missing/duplicate stages, order, bridge,
evidence, duration, WPS, mutation, adapter round trip, and V2-to-legacy
projection tests.

### Phase 4 — formula-native component and authoring path

Add formula-stage authoring, component selection, evidence binding, bridge
continuity, and duration-aware draft variants. AI Assist remains draft-only.

**Exit gate:** supported-formula coverage, continuity, ordering, genericness,
dedupe, evidence-bound claims, approval gate, and deterministic-selection tests.

### Phase 5 — compiler binding behind the flag

Add V2 native compiler binding with default-off, scoped rollout, telemetry, and
rollback. Preserve all legacy public signatures, return shapes, and byte-stable
golden output with the flag off.

**Exit gate:** legacy flag-off golden test; deterministic V2 compile; input
immutability; approved-text preservation; duration/WPS/leakage/safety failures;
unknown formula; no silent fallback; and flag isolation.

### Phase 6 — consumer and UI migration

Migrate the frozen producer/consumer matrix using explicit adapters. Store
selected revision and binding lineage. Update UI state and revalidation without
removing legacy compatibility.

**Exit gate:** API, UI, Playwright/UAT where already used, workspace package,
Hybrid, poster, bulk/production, faceless/montage, AI Assist, blocked-state,
and approval/revalidation transition tests.

### Phase 7 — shadow, pilot, and cutover

Run read-only shadow validation, compare deterministic results, select a bounded
pilot, keep default OFF, validate rollback, and propose wider rollout only
after the acceptance matrix passes. Shadow mode must not mutate production copy
or spend provider credits.

**Exit gate:** deterministic shadow comparison, bounded pilot acceptance,
flag-off rollback, legacy-path regression, visible fail-closed V2 errors, and
remote proof for every preceding phase.

## 13. Rollback and recovery

Rollback is a configuration operation, not a destructive data operation.

1. Set `COPY_BLUEPRINT_V2_ENABLED=0` for the affected product/workspace or the
   pilot scope.
2. Stop new V2 bindings and leave existing V2 artifacts and telemetry intact
   for audit.
3. Keep V2-invalid attempts blocked and visible; do not convert the failure to
   a silent legacy success.
4. For a new legacy production action, the operator explicitly selects the
   legacy path and receives a legacy binding with its own lineage. It is not an
   automatic fallback from a V2 error.
5. Revalidate the legacy path using its existing tests and readiness gates.
6. Re-enable V2 only after the defect is fixed in a new revision, revalidated,
   reapproved, and accepted in the bounded scope.

Additive schema and audit records are retained during rollback. No destructive
down migration, production data rewrite, mass reclassification, or approval
deletion is permitted as rollback.

## 14. Test and acceptance gates

### 14.1 Phase 0 documentation gate

The Phase 0 PR must prove:

- exact baseline and clean isolated worktree;
- required ADR file exists;
- `git status --short` and `git diff --stat` are understood;
- the diff contains only this ADR;
- `markdownlint` passes when available;
- no production code, schema, data, provider, or credit mutation occurred;
- commit, push, PR, CI, and remote-head proof are exact and full-length.

### 14.2 Required V2 acceptance matrix

Before any V2 phase is reported as complete, tests must cover:

1. formula-stage coverage for every supported registered formula;
2. ordered formula stages;
3. hook/body/CTA bridge continuity projections;
4. evidence reference integrity;
5. stable fact identity;
6. evidence digest mismatch;
7. missing evidence fact;
8. stale Product Truth snapshot;
9. invalid product evidence lineage;
10. claim-bearing stage without a fact reference;
11. wording correction preserving `fact_id` while changing `text_digest`;
12. Product Truth lineage;
13. semantic review gate;
14. immutable approval artifact;
15. no silent stage deletion;
16. no compiler mutation;
17. `COPY_DURATION_FIT_FAILED`;
18. deterministic compilation;
19. legacy flag-off byte stability;
20. adapter behavior and explicit lossiness;
21. no automatic legacy-to-V2 migration;
22. no auto-approval;
23. unknown-formula fail-closed behavior;
24. no HSO silent fallback in V2;
25. all identified producer/consumer paths;
26. genericness and near-duplicate detection;
27. deterministic component selection where promised;
28. existing backend regression tests;
29. existing frontend tests;
30. existing API tests;
31. existing browser/UAT tests where available;
32. existing syntax checks where applicable.

Any pre-existing failure must be recorded with the exact command, exact
failure, clean-baseline reproduction status, whether the current phase caused
it, and mitigation or blocker status. Tests must not be weakened, deleted, or
skipped to obtain a green result.

### 14.3 Runtime and credit boundary

Planning, validation, shadow mode, compilation, and tests must not call the
provider or spend credits. Live generation requires separate explicit
authorization and remains governed by ADR-007 and the repository credit-safety
contracts. Phase 0 performs no runtime validation beyond static/documentation
checks.

## 15. Consequences

### Positive

- Formula structure becomes durable and reviewable instead of being a
  decorative or lossy label.
- Product facts and claim lineage remain separate from persuasion authorship.
- Approved copy can be audited and reproduced exactly.
- Compiler safeguards remain centralized and deterministic.
- Legacy behavior can be rolled back without deleting V2 artifacts.
- Consumer migration is visible through explicit adapter/version lineage.

### Costs and risks

- The migration temporarily carries legacy and V2 contracts in parallel.
- Evidence identity and wording-drift handling require an explicit registry
  substrate rather than text hashing.
- Every consumer must declare whether it is legacy or V2.
- Duration/WPS fit failures may require a new authoring revision instead of a
  convenient compiler rewrite.
- A V2 rollout must remain narrow until shadow and pilot evidence are accepted.

These costs are intentional governance controls, not reasons to weaken the
contract.

## 16. Phase 0 acceptance statement

This ADR authorizes the architecture and the sequential implementation plan. It
does not authorize production code, database migration, consumer migration,
feature-flag activation, approval, provider access, or live generation.

The next decision after a remotely proven Phase 0 merge is whether the owner
authorizes Phase 1 Task A readiness remediation. Until that decision and the
Phase 0 remote proof exist, all later phases are blocked by process.
