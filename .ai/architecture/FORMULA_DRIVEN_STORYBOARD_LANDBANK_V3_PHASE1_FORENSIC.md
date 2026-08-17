# BOSMAX Formula-Driven Storyboard Landbank V3 — Phase 1 Forensic Report

## STATUS

`PHASE1_FORENSIC_REVIEW_READY`

This is a documentation-only, read-only forensic report after the owner-approved
architecture merge. It records the current repository authorities, the reusable
V2/P6 supply, and the gaps that must be resolved before Phase 2. No V3 table,
service, API, migration, provider call, queue action, activation, media
generation, or credit-spending path was implemented or invoked.

The report deliberately stops before Phase 2. It does not promote, import,
approve, materialize, reserve, compile, queue, start, or mutate any production
record.

## BASELINE SHA

| Item | Value |
|---|---|
| Architecture PR | `#778` |
| Architecture PR head verified before merge | `8e7c3876e3eaa8c5d3d6f5902e19593689d06c94` |
| Architecture merge SHA | `ea4267702a3b7e076a697692fd3a2902f7b4a1a3` |
| Phase 1 branch base | `origin/main` at `ea4267702a3b7e076a697692fd3a2902f7b4a1a3` |
| Phase 1 branch | `feat/storyboard-landbank-v3-phase1-forensic` |

The merged architecture is `.ai/architecture/FORMULA_DRIVEN_STORYBOARD_LANDBANK_V3.md`.
Its Phase 1 exit gate is a reproducible forensic report with zero provider or
media calls.

## SCOPE AND METHOD

The inspection followed the owner-approved order:

`Product Truth → Objective → Formula/Recipe → Angle → Storyline Family → Formula Stage Plan → Stage-native Components → Master Storyboard → Duration Projection → Review/Human Receipt → Storyboard Landbank → V2 materialization → Production Copy Supply Manifest → P6`.

Read-only evidence sources included:

- `agent/authority/copy_formula_registry.py` and
  `agent/authority/copy_blueprint_v2_authority.py`;
- `agent/authority/wps_blocking_authority.json`,
  `agent/services/canonical_prompt_compiler.py`, and
  `agent/services/full_storyboard_extend_planner.py`;
- Product Truth snapshot/provenance models and services;
- V2 blueprint, evidence, angle-candidate, binding, and authority-pointer
  models/services/API contracts;
- Scene Choreography V2 and Creative Treatment authority;
- P6 plan, item, attempt, audit, content-combination, compile, and scheduler
  contracts;
- direct SQLite queries against the canonical `flow_agent.db` using a read-only
  URI (`mode=ro`) and `PRAGMA query_only=ON`.

No application service that writes to the database was called. No FastAPI route,
P6 materialization, approval, compile, dry run, scheduler, provider connector,
`make_video.start_generate`, or Extend dispatch was called. The formula matrix
was derived by importing the pure registry/authority modules only; the database
was not opened by that process.

## CLASSIFICATION LEGEND

For supply tables:

- `EXISTS_CANONICALLY` means an existing approved authority already carries the
  required fact or contract.
- `PARTIALLY_EXISTS` means existing authority can supply some fields, but not a
  V3 identity, revision, lineage, or governance contract.
- `DERIVABLE_READ_ONLY` means a deterministic read projection is possible
  without inventing facts; it is not an approved V3 record.
- `MISSING` means no repository authority was found.
- `UNSAFE_TO_DERIVE` means deriving the value would risk an unsupported claim or
  a false lineage assertion.

For proposed V3 objects, services, and APIs:

- `REQUIRED` means the V3 contract cannot be satisfied by the current authority.
- `PARTIALLY_REQUIRED` means an additive V3 identity or adapter is required,
  while a substantial existing authority remains reusable.
- `NOT_REQUIRED` means a second authority would duplicate or conflict with an
  existing canonical contract.

## FORMULA CONTRACT MATRIX

The registry contains six canonical formulas and two explicitly non-production
operator-review drafts. The registry has no independent version column. V2
derives the version as `copy-formula-registry-v1:<first-16-sha256>` from the
canonical formula payload in `copy_blueprint_v2_authority.py`.

| Formula | Compiler family | Definition status | Derived formula version | Ordered required stages | V2 production eligible |
|---|---|---|---|---|---|
| `PAS` | `PAS` | `CANONICAL` | `copy-formula-registry-v1:f9f435eec6c14ec5` | `problem → agitate → solution → cta` | Yes |
| `AIDA` | `AIDA` | `CANONICAL` | `copy-formula-registry-v1:a41f94ecd4101e73` | `attention → interest → desire → action` | Yes |
| `HSO` | `HSO` | `CANONICAL` | `copy-formula-registry-v1:c06c98a53b112523` | `hook → story → offer` | Yes |
| `BAB` | `BAB` | `CANONICAL` | `copy-formula-registry-v1:f103bafc4efbbdea` | `before → after → bridge` | Yes |
| `PASTOR` | `PASTOR` | `CANONICAL` | `copy-formula-registry-v1:c605f54a12c823a9` | `problem → amplify → story → transformation → offer → response` | Yes |
| `PESTA` | `PESTA` | `CANONICAL` | `copy-formula-registry-v1:fb80b988df18ab60` | `pain → emotion → solution → transformation → action` | Yes |
| `SavagePAS` | `PAS` | `OPERATOR_REVIEW_DRAFT` | `copy-formula-registry-v1:214df8f9b7cec460` | `problem → savage_agitate → solution → cta` | No; fail closed |
| `HPAS` | `PAS` | `OPERATOR_REVIEW_DRAFT` | `copy-formula-registry-v1:c31de296eadf8fea` | `hook → problem → agitate → solution → cta` | No; fail closed |

The registry output mapping is also load-bearing. For example, PAS maps
`problem` to angle/hook, `agitate` to subhook, `solution` to USP, and `cta` to
CTA. PASTOR and PESTA map multiple ordered stages into the derived USP display;
that is why a V3 Master must retain the full stage plan rather than reconstruct
it from Hook/Body/CTA.

Machine-readable contract summary:

```json
[
  {"formula_id":"PAS","compiler_family":"PAS","definition_status":"CANONICAL","formula_version":"copy-formula-registry-v1:f9f435eec6c14ec5","production_eligible":true,"required_stage_keys":["problem","agitate","solution","cta"],"output_mapping":{"angle":"problem","hook":"problem","subhook":"agitate","usp":["solution"],"cta":"cta"}},
  {"formula_id":"AIDA","compiler_family":"AIDA","definition_status":"CANONICAL","formula_version":"copy-formula-registry-v1:a41f94ecd4101e73","production_eligible":true,"required_stage_keys":["attention","interest","desire","action"],"output_mapping":{"angle":"desire","hook":"attention","subhook":"interest","usp":["desire"],"cta":"action"}},
  {"formula_id":"HSO","compiler_family":"HSO","definition_status":"CANONICAL","formula_version":"copy-formula-registry-v1:c06c98a53b112523","production_eligible":true,"required_stage_keys":["hook","story","offer"],"output_mapping":{"angle":"hook","hook":"hook","subhook":"story","usp":["offer"],"cta":"offer"}},
  {"formula_id":"BAB","compiler_family":"BAB","definition_status":"CANONICAL","formula_version":"copy-formula-registry-v1:f103bafc4efbbdea","production_eligible":true,"required_stage_keys":["before","after","bridge"],"output_mapping":{"angle":"after","hook":"before","subhook":"after","usp":["bridge"],"cta":"bridge"}},
  {"formula_id":"PASTOR","compiler_family":"PASTOR","definition_status":"CANONICAL","formula_version":"copy-formula-registry-v1:c605f54a12c823a9","production_eligible":true,"required_stage_keys":["problem","amplify","story","transformation","offer","response"],"output_mapping":{"angle":"transformation","hook":"problem","subhook":"amplify","usp":["story","transformation","offer"],"cta":"response"}},
  {"formula_id":"PESTA","compiler_family":"PESTA","definition_status":"CANONICAL","formula_version":"copy-formula-registry-v1:fb80b988df18ab60","production_eligible":true,"required_stage_keys":["pain","emotion","solution","transformation","action"],"output_mapping":{"angle":"emotion","hook":"pain","subhook":"emotion","usp":["solution","transformation"],"cta":"action"}},
  {"formula_id":"SavagePAS","compiler_family":"PAS","definition_status":"OPERATOR_REVIEW_DRAFT","formula_version":"copy-formula-registry-v1:214df8f9b7cec460","production_eligible":false,"required_stage_keys":["problem","savage_agitate","solution","cta"],"output_mapping":{"angle":"problem","hook":"problem","subhook":"savage_agitate","usp":["solution"],"cta":"cta"}},
  {"formula_id":"HPAS","compiler_family":"PAS","definition_status":"OPERATOR_REVIEW_DRAFT","formula_version":"copy-formula-registry-v1:c31de296eadf8fea","production_eligible":false,"required_stage_keys":["hook","problem","agitate","solution","cta"],"output_mapping":{"angle":"problem","hook":"hook","subhook":"agitate","usp":["solution"],"cta":"cta"}}
]
```

Finding: a V3 formula authority table is `NOT_REQUIRED`. V3 should reference
this registry and its derived formula version. A V3 recipe must snapshot the
formula ID/version; it must not create a parallel formula definition.

## WPS / DURATION CONTRACT MATRIX

The retained authority is `agent/authority/wps_blocking_authority.json`, with
runtime use through `agent/services/canonical_prompt_compiler.py`. Google Flow
uses these exact block plans for the requested V3 durations:

| Target duration | Google Flow block plan | Seam/CTA rule |
|---:|---|---|
| 8 seconds | `[8]` | Single block; CTA is in the final block |
| 16 seconds | `[8, 8]` | Continuation seam; CTA is in block 2 |
| 24 seconds | `[8, 8, 8]` | Continuation seams; CTA is in block 3 |

The compiler calculates each block as `max(4, round(block_seconds × WPS))` and
sums the blocks. SafeWPS is the default. SweetWPS is an explicit targeting
mode. The following values are `safe words / sweet words` for 8 / 16 / 24
seconds respectively.

| Language profile | Min WPS | Safe WPS | Sweet WPS | Max WPS | Ceiling WPS | 8s | 16s | 24s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Malay | 1.8 | 2.4 | 2.7 | 2.8 | 3.0 | 19 / 22 | 38 / 44 | 57 / 66 |
| English | 1.7 | 2.3 | 2.45 | 2.6 | 3.0 | 18 / 20 | 36 / 40 | 54 / 60 |
| Mandarin | 1.8 | 2.5 | 2.65 | 2.8 | 3.0 | 20 / 21 | 40 / 42 | 60 / 63 |
| Hindustani | 1.8 | 2.3 | 2.5 | 2.7 | 3.0 | 18 / 20 | 36 / 40 | 54 / 60 |
| Tamil | 1.7 | 2.2 | 2.4 | 2.6 | 3.0 | 18 / 19 | 36 / 38 | 54 / 57 |
| Bengali | 1.7 | 2.2 | 2.4 | 2.6 | 3.0 | 18 / 19 | 36 / 38 | 54 / 57 |
| Indonesian | 1.8 | 2.4 | 2.6 | 2.8 | 3.0 | 19 / 21 | 38 / 42 | 57 / 63 |
| Burmese | 1.5 | 2.0 | 2.2 | 2.4 | 3.0 | 16 / 18 | 32 / 36 | 48 / 54 |
| Thai | 1.6 | 2.1 | 2.3 | 2.5 | 3.0 | 17 / 18 | 34 / 36 | 51 / 54 |

`canonical_prompt_compiler._LANGUAGE_NAMES` currently exposes runtime aliases
for Malay, English, Indonesian, Mandarin, Tamil, and Thai. The retained JSON
authority has nine language profiles, but Hindustani, Bengali, and Burmese are
not currently addressable through the compiler alias map; an unknown alias
defaults to Malay. This is a real V3 input-validation gap, not a reason to
create another WPS table.

`full_storyboard_extend_planner.py` is reusable. It plans the complete dialogue
and story before rendering, enforces per-block budgets, requires the final CTA
in the final block, and checks continuation seams. Its current seam margins are
0.78 seconds before a non-final block ends speech and 0.50 seconds before a
continuation block starts new dialogue. V3 must preserve these planner rules
and record their validator/version receipt in a duration projection.

Finding: a new WPS authority or duration-calculation service is `NOT_REQUIRED`.
A persisted `duration_projection_v3` is `REQUIRED` for parent/child lineage,
exact dialogue slices, block budgets, CTA placement, continuity state, and
validation receipts.

## PRODUCT TRUTH SUPPLY MATRIX

The canonical Product Truth authority is the approved Product Intelligence
snapshot and field-provenance model, not `product.silo` or a historical flat
copy row. The representative read-only product used for capacity inspection is
`6483d624-a03d-4933-9bba-6ca2e5f7b6fd` (`Minyak Warisan Cap Burung 25ml`). Its
latest approved snapshot is version 8, `CLAIM_SAFE`, medium claim risk, and
completeness 1.0.

| Required Product Truth input | Existing authority/evidence | Classification | V3 decision |
|---|---|---|---|
| Product identity, taxonomy, form factor, size | `product` plus approved `product_intelligence_snapshot`; Product Truth authority service | `EXISTS_CANONICALLY` | Reuse; no V3 product table |
| Approved snapshot ID, version, digest, status | `ProductIntelligenceSnapshot` and `ProductTruthLineage` | `EXISTS_CANONICALLY` | Carry exact lineage |
| Description, benefits, USPs | Snapshot fields `product_description`, `benefits_json`, `usp_json`; approved V2 facts | `EXISTS_CANONICALLY` | Reference current snapshot/facts |
| Audience/persona | `target_customer_text` and `buyer_persona_snapshot_json` | `EXISTS_CANONICALLY` | Reference; keep snapshot version |
| Pains, objections, triggers | Persona and `copy_strategy_summary_json`; direct `pain_points_json` is empty on the inspected latest snapshot | `PARTIALLY_EXISTS` | Add a typed V3 coverage/selector only if needed; never infer missing pain or objection copy |
| Usage and warnings | `usage_text`, `warnings_text`, approved Product Truth fields | `EXISTS_CANONICALLY` | Reuse as safety/usage lineage |
| Allowed and blocked claims | `allowed_claims_json`, `blocked_claims_json`, `claim_gate`, `claim_risk_level`, approved evidence facts | `EXISTS_CANONICALLY` | Reuse; claim-bearing stages cite facts |
| Ingredients and product mechanism | `ingredients_text` exists, but no typed mechanism contract or verified mechanism fact type was found | `UNSAFE_TO_DERIVE` | Require explicit approved evidence before using mechanism language |
| Product proof/evidence provenance | `product_intelligence_field_provenance` with source, lane, evidence kind, confidence, verification, and review fields | `EXISTS_CANONICALLY` | Reuse; do not build a second provenance authority |
| Copy strategy and recommended formula | Snapshot `copy_strategy_summary_json` and product mapping fields | `PARTIALLY_EXISTS` | Use as strategy input, not as final V3 formula/stage approval |
| Hook, subhook, CTA, and pain-angle arrays | Snapshot JSON fields exist, but the inspected approved snapshot has empty `hook_angles_json`, `subhook_json`, `cta_angles_json`, and `pain_points_json` | `PARTIALLY_EXISTS` | Do not treat empty arrays as supply; derive only through governed V3 generation/review |

The inspected product has usable target-customer, benefit, USP, usage, warning,
and claim-safe content. It does not prove a typed mechanism, objection, proof,
or pain supply for every future storyline. V3 capacity must therefore report
coverage gaps instead of counting a product as fully supplied because a general
persona or category label exists.

## EVIDENCE SUPPLY MATRIX

`copy_evidence_fact_v2` is the existing immutable, approved fact authority. It
stores stable fact IDs, canonical text, digest, Product Truth snapshot version,
status, approval, and source reference. The inspected product has 30 approved
V2 fact rows across its approved snapshot history; the observed kinds are:

| V2 fact kind | Approved rows observed | Safe use |
|---|---:|---|
| `ALLOWED_CLAIM` | 8 | Claim-bearing stage text and claim gate |
| `BENEFIT` | 10 | Benefit/solution stage grounding |
| `PRODUCT_DESCRIPTION` | 2 | Product identity/description grounding |
| `TARGET_CUSTOMER` | 2 | Audience grounding |
| `USAGE` | 2 | Usage and context grounding |
| `USP` | 6 | Differentiation/offer grounding |

| Proposed evidence capability | Current repository evidence | Classification | V3 decision |
|---|---|---|---|
| Stable approved fact IDs and digests | `copy_evidence_fact_v2` | `EXISTS_CANONICALLY` | Reuse |
| Field-level source and review lineage | `product_intelligence_field_provenance` | `EXISTS_CANONICALLY` | Reuse |
| Fact ranking/selection for an angle or formula stage | V2 evidence references and 1–5 fact input on blueprint generation | `PARTIALLY_EXISTS` | Add a V3 deterministic selector/read model; do not duplicate facts |
| Typed proof facts | No distinct `PROOF` fact kind was found | `MISSING` | New V3 workflow may classify existing approved sources, but cannot assert proof without evidence |
| Typed mechanism facts | No distinct `MECHANISM` fact kind was found | `MISSING` | Require explicit evidence; no category inference |
| Typed objection/pain facts | No distinct `OBJECTION` or `PAIN` fact kind was found | `MISSING` | Treat persona text as context, not as an approved claim fact |
| Current-truth revalidation | V2 service/resolver reloads current Product Truth and evidence before binding | `EXISTS_CANONICALLY` | Reuse at every V3/V2 boundary |

Finding: a new V3 evidence-fact authority table is `NOT_REQUIRED`. A V3
coverage/ranking receipt is `PARTIALLY_REQUIRED` because V3 needs to explain why
facts satisfy a formula stage, storyline, or proof need while retaining the V2
fact IDs as the factual source.

## ANGLE SUPPLY MATRIX

The current sources are product strategy fields and `copy_angle_candidate_v2`.
For the inspected product, the V2 angle candidate table contains 55 distinct
angle IDs, all bound to formula `PAS`, objective `conversion`, a Product Truth
snapshot lineage, evidence fact IDs, and a provider receipt. These are useful
inputs, but the table has no V3 revision/lifecycle contract, storyline-family
compatibility, stage coverage, or exact projection lineage.

| Angle requirement | Existing source | Classification | V3 decision |
|---|---|---|---|
| Product-level strategic angle | Product mapping `copywriting_angle` and Product Truth strategy | `EXISTS_CANONICALLY` | Reuse as input only |
| Candidate angle definition and evidence | `copy_angle_candidate_v2` | `PARTIALLY_EXISTS` | Adapt by read-only projection; preserve V2 IDs/digests |
| Stable angle identity/revision/lifecycle | No V3 angle object; V2 candidate has an ID but not the full V3 revision contract | `MISSING` | `angle_v3` is `PARTIALLY_REQUIRED` |
| Objective/angle/formula compatibility | V2 candidate stores objective and formula/version | `PARTIALLY_EXISTS` | Revalidate with V3 recipe and formula contract |
| Angle/storyline compatibility and novelty | No current copy authority provides storyline family or semantic route breadth | `MISSING` | Required in V3 compatibility/novelty read model |
| Approved reusable component supply per angle | Canonical `copy_set` and `copy_component` rows are both zero | `MISSING` | Do not count historical or empty pools as supply |

V3 may seed a draft/read model from approved V2 candidates in a later phase, but
Phase 1 performs no import or approval. A provider receipt on a V2 candidate is
not a human V3 approval receipt.

## STORYLINE FAMILY GAP

No current copy object or table supplies a reusable, versioned Storyline Family
with an ordered route, formula compatibility, proof placement, transitions,
CTA closure, and cross-storyline composition gate.

The following existing authorities are adjacent but not equivalent:

- V2 `FormulaStage` and `BridgeContract` describe the continuity of one
  blueprint. They are partial route evidence, not a reusable family identity.
- `scene_strategy_id`, choreography IDs/SHA, beat sequences, and Creative
  Treatment fields describe visual/physical scene authority. They must remain
  separate from copy storyline family.
- P6 `logical_mode`, scene family, visual DNA, and treatment compatibility
  describe execution dimensions, not narrative copy route.

| Proposed capability | Current evidence | Classification | V3 decision |
|---|---|---|---|
| Reusable storyline family identity/revision | No equivalent copy record found | `MISSING` | `storyline_family_v3` is `REQUIRED` |
| Formula-compatible ordered route | Per-blueprint V2 stages/bridges only | `PARTIALLY_EXISTS` | Reuse bridge concepts; add V3 family contract |
| Proof placement and CTA closure policy | Formula mapping and planner CTA rule, but no family object | `PARTIALLY_EXISTS` | Store on family/recipe and validate |
| Cross-storyline composition block | No current V2/component contract | `MISSING` | Default reject; compatibility engine required |
| Visual scene lineage | Scene Choreography V2 and Creative Treatment | `EXISTS_CANONICALLY` for visual authority | Reuse through a separate `scene_projection_v3`; never relabel it as storyline |

This is the largest semantic supply gap. A formula and an angle do not prove a
coherent narrative route. V3 must refuse to compose across storyline families
unless an explicit compatibility contract exists.

## COMPONENT SUPPLY MATRIX

The existing `copy_component` subsystem is a legacy composition contract. Its
documented vocabulary is exactly `HOOK`, `SUBHOOK`, `USP_SET`, and `CTA`; it has
no `BODY` field. It groups components by an angle key, permits global CTAs, is
formula-independent, and composes the old CopySetResponse shape. The canonical
database currently contains zero `copy_component` rows.

V2 `FormulaStage` is the reusable evidence source for a current approved
blueprint: it has an ordered stage key, authored text, semantic role, component
reference, formula stage key, bridge contract, claim-bearing flag, fact refs,
and validation. It is blueprint-level and immutable after approval; it is not a
stage-native component landbank.

| Component requirement | Existing source | Classification | V3 decision |
|---|---|---|---|
| Approved stage text for one current blueprint | V2 `FormulaStage` | `EXISTS_CANONICALLY` | Reuse as materialization input |
| Reusable stage-native component | No V3 component table; legacy `copy_component` is flat/slot-shaped | `MISSING` | `storyboard_component_v3` is `REQUIRED` |
| Formula-stage binding | V2 `formula_stage_key`; no reusable V3 component lineage | `PARTIALLY_EXISTS` | Add explicit formula/stage lineage |
| Entry/exit continuity and bridge requirements | V2 `BridgeContract` per blueprint | `PARTIALLY_EXISTS` | Add reusable storyline/family compatibility fields |
| Evidence refs and Product Truth lineage | V2 stages/blueprints and V2 fact table | `EXISTS_CANONICALLY` | Carry exact IDs/digests |
| Objective and storyline compatibility | Not represented in legacy component rows | `MISSING` | Required V3 component gate |
| Component review versus full-storyboard review | Legacy component status and V2 semantic review are separate, but no V3 receipt | `PARTIALLY_EXISTS` | Keep component review narrower; final approval must be over the resolved storyboard/projection |

The legacy component composer is useful as a deterministic capacity idea
(angle-coherent multiplication), but its flat output must not be promoted to a
V3 Master. `copy_component` is therefore a historical/maintenance reference,
not a migration target to widen in place.

## MASTER STORYBOARD GAP

V2 already supplies a strong last-mile copy authority. `CopyBlueprintV2` stores
the explicit formula ID/version, objective, angle, ordered formula stages,
component references, evidence references, Product Truth lineage, target
duration/WPS fields, approved execution text, semantic review, readiness proof,
approval snapshot, and digest. The inspected product has three
`PRODUCTION_VALID` V2 revisions, all PAS, plus four draft revisions.

The V2 object does not satisfy the V3 Master contract because it lacks a
campaign/recipe identity, stable storyline-family lineage, resolved V3
component set, stage-level supply lineage, complete V3 validation receipts,
candidate/review envelope, and a parent for multiple duration projections.
`CopyBlueprintV2.derived_projections()` is explicitly lossy: Hook/Body/CTA are
display projections and cannot reconstruct all stages for PASTOR, PESTA, or
other multi-stage formulas.

| Master requirement | Existing source | Classification | V3 decision |
|---|---|---|---|
| Full ordered formula-stage copy | V2 blueprint/stages | `EXISTS_CANONICALLY` | Reuse as materialization/last-mile input |
| Product Truth, formula, objective, angle, evidence lineage | V2 blueprint | `EXISTS_CANONICALLY` | Carry exact lineage |
| Campaign/recipe/storyline family parent | No current V2 field/table | `MISSING` | `master_storyboard_v3` is `REQUIRED` |
| Resolved V3 component references and stage supply digest | V2 component refs are blueprint-local | `PARTIALLY_EXISTS` | Add V3 component and supply lineage |
| Parent for 8/16/24 projections | V2 has optional target duration only | `MISSING` | Add projection parent/child lineage |
| Full machine-gate receipt and human-review envelope | V2 has readiness/semantic/approval artifacts, not V3 scope | `PARTIALLY_EXISTS` | Add V3 candidate/review/receipt records |
| Lossless review display | V2 approved execution text and stages | `EXISTS_CANONICALLY` | Reuse; never review only H/B/CTA |

Finding: the V2 blueprint is not discarded or replaced. V3 Master is a durable
upstream landbank record whose selected projection is materialized through the
existing V2 approval/binding authority.

## DURATION PROJECTION GAP

The arithmetic and rendering authorities are already present. The missing
contract is durable lineage, not another duration algorithm.

| Requirement | Existing evidence | Classification | V3 decision |
|---|---|---|---|
| Supported Google Flow 8/16/24 block plans | Checked-in WPS authority and canonical compiler | `EXISTS_CANONICALLY` | Reuse |
| Per-block safe/sweet budget | Canonical compiler | `EXISTS_CANONICALLY` | Reuse |
| Complete story/dialogue allocation | Full Storyboard Extend Planner | `EXISTS_CANONICALLY` | Reuse |
| Seam continuity, final CTA, exact slices | Planner validators | `EXISTS_CANONICALLY` | Reuse and record receipts |
| Projection ID/revision/digest under one Master | No persisted V3 projection record | `MISSING` | `duration_projection_v3` is `REQUIRED` |
| Language/WPS/block-plan/validator snapshot | V2 has target/WPS fields but no V3 projection receipt | `PARTIALLY_EXISTS` | Persist exact snapshot in V3 projection |
| Projection-specific exact reuse identity | P6 DNA/content-combination is downstream and visual/mode-specific | `MISSING` | Include projection digest in V3 usage/manifest lineage |

V3 must not use a second WPS profile or manually supplied block plan. A
`duration_projection_v3` row must point to the checked-in WPS/compiler and
planner versions, exact target language, block plan, per-block words, dialogue
slices, CTA placement, continuity state, and machine-gate digest.

## APPROVAL CARRY-FORWARD GAP

The current direct V2 approval path is real and must remain intact:

- `ApproveBlueprintRequest` requires `approved_by`, a typed
  `SemanticReviewProof`, and a typed `ProductionReadinessProof`.
- `approve_copy_blueprint_v2` creates an immutable V2 `ApprovalSnapshot` and
  fails closed for non-canonical formulas, missing approval, stale truth, bad
  evidence, duration, safety, or readiness.
- The V2 API reports `automatic_approval: false`.
- V2 binding resolution revalidates the persisted binding, current Product
  Truth, evidence, blueprint, formula/version, and feature flags.
- The resolver currently requires explicit `semantic_review_validated`; the
  persisted path derives that boolean from the V2 semantic review decision and
  raises `COPY_V2_SEMANTIC_REVIEW_REQUIRED` when absent or false.

The missing authority is the V3 human decision over the exact resolved Master
Storyboard and Duration Projection. A P6 plan approval is not a copy semantic
approval and cannot substitute for it.

| Approval requirement | Existing source | Classification | V3/V2 decision |
|---|---|---|---|
| Direct V2 human approval | V2 request, service, snapshot, immutable rows | `EXISTS_CANONICALLY` | Reuse unchanged |
| V3 exact resolved-text human receipt | No V3 receipt table/API | `MISSING` | `v3_human_approval_receipt` is `REQUIRED` |
| Batch confirmation bound to individual digests | No V3 batch receipt | `MISSING` | Required for explicit bulk approval only |
| Typed carry-forward mode | No V2 request field for V3 receipt source | `MISSING` | V2 API/service extension is `PARTIALLY_REQUIRED` |
| Receipt ID/digest on V2 approval snapshot/binding | No typed V3 reference in current V2 models | `MISSING` | Additive V2 lineage fields are required later |
| Exact-text/truth/evidence/formula/WPS revalidation | Current V2 validation covers most checks | `PARTIALLY_EXISTS` | Reuse validators and add V3 receipt scope checks |
| Human decision versus machine-clean status | V2 direct semantic proof exists; V3 bulk rules do not | `PARTIALLY_EXISTS` | Never fabricate a semantic-review boolean |

The future additive contract must use explicit approval modes such as
`DIRECT_V2_HUMAN` and `V3_RECEIPT_CARRY_FORWARD`, with a typed receipt ID,
receipt digest, storyboard/projection revisions, and exact text digest. The V2
validator must consume the genuine V3 receipt as semantic evidence. It must not
set `semantic_review_validated=true` merely because a V3 row exists, and it must
not write V2 tables directly from a V3 route.

## P6 PRODUCTION COPY SUPPLY MANIFEST GAP

P6 currently has durable plans, product allocations, pool snapshots, capacity
preflight, content-matrix items, creative DNA and dedupe guards, treatments,
compile snapshots, attempts, provider observations, generated-artifact
reconciliation, and audit events. It has no Production Copy Supply Manifest.

The critical current bridge is
`creative_production_plan_service._v2_copy_authority_record()`:

- it resolves the persisted V2 binding for the P6 lane;
- it projects the binding into historical P6 dimensions;
- its `copy_set_id` JSON key contains the V2 binding identity and is explicitly
  never looked up in `copy_set`;
- it exposes derived Hook/Body/CTA-compatible fields for the historical P6
  shape, while the V2 ordered stages remain authoritative.

`materialize_content_matrix()` re-runs preflight and selects bounded visual/DNA
candidate rows directly into P6 items. That is an executable matrix, not a
versioned multi-copy selection receipt with V3 projection lineage. The current
P6 API has no manifest route. The current plan-level product-global V2 binding
pointer also cannot represent a campaign-scoped set of distinct approved
copies without changing authority semantics.

| Manifest requirement | Existing source | Classification | V3/P6 decision |
|---|---|---|---|
| One bounded selection set for one P6 plan/product/scope | P6 plan and product allocations | `PARTIALLY_EXISTS` | `production_copy_supply_manifest_v3` is `REQUIRED` |
| Multiple copy items with deterministic order | P6 item ordinal/DNA, but no copy-supply item lineage | `PARTIALLY_EXISTS` | `manifest_item_v3` is `REQUIRED` |
| V3 Master/projection and V2 blueprint/binding references | V2 binding metadata in P6 dimensions; no V3 refs | `PARTIALLY_EXISTS` | Add exact IDs/digests |
| V3 human receipt and Product Truth/evidence/formula/WPS receipts | V2 approval/evidence metadata only | `PARTIALLY_EXISTS` | Manifest must carry exact lineage, not re-approve |
| Immutable manifest revision/digest | P6 plan/item snapshots and DNA digests, no manifest digest | `MISSING` | Required |
| Exact duplicate exclusion and reuse policy snapshot | `content_combination`, DNA, dedupe guards, legacy rotation | `PARTIALLY_EXISTS` | Add V3 Recipe Policy and LandbankUsage lineage |
| Capacity reservation and rollback/reconciliation | P6 capacity/preflight and attempt recovery | `PARTIALLY_EXISTS` | Add manifest reservation/usage events |
| Queue/start revalidation of every copy item | P6 payload validation and live gates | `PARTIALLY_EXISTS` | Add manifest digest/item/binding/receipt checks before compile/queue/start |
| Product-global activation pointer replacement | Existing V2 authority pointer | `NOT_REQUIRED` | Do not replace or mutate it for a manifest |
| Copy-free image policy | V2 `COPY_NOT_REQUIRED` and P6 policy | `EXISTS_CANONICALLY` | Preserve explicit policy |

The future manifest is downstream selection over bounded V2
`PRODUCTION_VALID` supply. It is not approval, V2 activation, or a second visual
authority. Existing P6 compile/scheduler/recovery paths remain reusable after
manifest validation hooks are added. No manifest was created or reserved in
Phase 1.

## CURRENT CAPACITY BASELINE

The following is a read-only baseline, not a V3 capacity claim. It is anchored
to the representative product named above because that product has current V2
and P6 evidence.

| Dimension | Observed baseline |
|---|---|
| Product Truth | One latest approved snapshot, version 8; `READY_FOR_APPROVAL`, `CLAIM_SAFE`, completeness `1.0` |
| Approved V2 evidence | 30 approved fact rows across the product's approved snapshot history; 15 facts on the latest approved snapshot in the inspected baseline |
| Formula breadth | One formula in current V2 supply: `PAS` |
| V2 blueprint supply | 3 `PRODUCTION_VALID` rows across 3 blueprint IDs; 4 additional `DRAFT` revision rows |
| V2 angle candidates | 55 distinct angle IDs, all `PAS`/`conversion` in the inspected product |
| V2 execution bindings | 11 `BOUND` rows across 8 lanes; 2 rows for `PRODUCTION_STUDIO_P6` |
| Legacy CopySet pool | 0 canonical `copy_set` rows |
| Legacy component pool | 0 canonical `copy_component` rows |
| Approved Creative Treatments | 4 rows: 2 `SINGLE`/8s, 1 `EXTEND`/16s, 1 `EXTEND`/24s |
| P6 8/16/24 matrix | Scheduled plan `p6plan_253976c03e714f33956d` targets one F2V video at each of 8, 16, and 24 seconds; 3 product-scoped items were observed |
| P6 DNA/dedupe evidence | Queried product-scoped plan groups had equal distinct creative-DNA and dedupe-guard counts per group |
| Downstream content combinations | 74 rows: F2V 4, HYBRID 37, I2V 6, T2V 27 |
| P6 execution footprint | The canonical DB contains 16 plans, 31 production items, 26 generation attempts, and 124 audit events in the inspected baseline |

This baseline demonstrates current V2/P6 execution capacity, not V3 semantic
coverage. It does not establish 55 reusable, storyline-diverse, duration-
projectable Master Storyboards. In particular, one formula, empty legacy
component rows, and no storyline-family records are the limiting dimensions.

## LEGACY CLASSIFICATION

| Surface | Classification | Evidence and handling |
|---|---|---|
| Product Intelligence snapshots and field provenance | `CANONICAL_KEEP` | Approved Product Truth, source, review, claim, and readiness authority |
| V2 formula registry and derived formula versions | `CANONICAL_KEEP` | Current formula contract and fail-closed production eligibility |
| WPS JSON, canonical compiler, and full storyboard planner | `CANONICAL_KEEP` | Current duration/block/WPS/CTA/seam authority |
| `copy_evidence_fact_v2` | `CANONICAL_KEEP` | Immutable approved fact authority; V3 references fact IDs |
| `copy_angle_candidate_v2` | `V2_INPUT_ADAPTER` | Useful truth/formula/objective/evidence-bound candidate source; not a V3 revision/lifecycle object |
| `copy_blueprint_v2` and `copy_execution_binding_v2` | `CANONICAL_PRODUCTION_KEEP` | Current V2 last-mile approval/binding authority; V3 materializes selected supply here |
| Scene Choreography V2 and Creative Treatment | `CANONICAL_VISUAL_KEEP` | Visual strategy/choreography/treatment authority; not copy storyline authority |
| P6 plan/item/attempt/audit/artifact ledgers | `CANONICAL_EXECUTION_KEEP` | Downstream execution, capacity, recovery, and audit authority |
| `content_combination` | `CANONICAL_DOWNSTREAM_LEDGER` | Exact script/visual/mode combination defense; V3 LandbankUsage must link to it, not replace it |
| `copy_set` | `LEGACY_REFERENCE_ONLY` | Monolithic angle/hook/subhook/USP/CTA bundle; zero canonical rows; never auto-import into approved V3 |
| `copy_component` | `LEGACY_REFERENCE_ONLY` | Old four-slot, formula-independent pool; zero canonical rows; do not widen in place |
| CopySet rotation/usage services | `MAINTENANCE_ONLY` | They query/update legacy `copy_set` usage and cannot supply V3 stage/storyline lineage |
| Workbook-derived flat copy samples or raw historical rows | `DO_NOT_IMPORT` | Retained documents may inform authority mapping, but flat Hook/Body/CTA rows, `NEEDS_VERIFICATION`, or unreviewed claims cannot become V3 approval |
| Historical `copy_set_id` fields inside P6 JSON | `REFERENCE_KEY_ONLY` | In current V2 mode the value is a binding ID; never resolve it through the legacy CopySet pool |

Migration rule: preserve historical rows and receipts for audit. No legacy row is
automatically converted into an approved angle, component, Master, projection,
receipt, or manifest. Any future import must enter DRAFT, retain source lineage,
and pass current Product Truth/evidence/formula/storyline validation.

## REUSABLE EXISTING SERVICES

| Existing service/authority | Reusable responsibility | Classification |
|---|---|---|
| Product Intelligence snapshot/provenance service | Read approved Product Truth, current version, field sources, claim gate, and readiness | `NOT_REQUIRED` to replace; reuse |
| Formula registry and `copy_blueprint_v2_authority` | Strict formula IDs, derived versions, stage keys, canonical eligibility | `NOT_REQUIRED` to replace; reuse |
| Canonical prompt compiler | WPS profiles, block plans, word budgets, source modes, CTA placement | `NOT_REQUIRED` to replace; reuse |
| Full Storyboard Extend Planner | Full dialogue/story allocation, seams, continuity, final CTA, per-block validation | `NOT_REQUIRED` to replace; reuse |
| V2 blueprint service | Ordered stages, evidence/truth validation, direct human approval, readiness, immutable snapshot | `PARTIALLY_REQUIRED` for additive carry-forward only |
| V2 execution resolver | Current-truth revalidation and immutable binding equivalence | `PARTIALLY_REQUIRED` for typed V3 receipt evidence; direct path remains |
| Copy Register V2 API | Existing truth/formula/blueprint/approval/binding read and direct approval routes | `PARTIALLY_REQUIRED` for future `V3_RECEIPT_CARRY_FORWARD` input |
| Scene Choreography V2 and Creative Treatment services | Visual strategy, choreography lineage, treatment receipts, stale dependency checks | `NOT_REQUIRED` to replace; `PARTIALLY_REQUIRED` for a V3 scene projection adapter |
| P6 plan/preflight/content matrix services | Current plan scope, capacity, candidate selection, DNA, product allocation | `PARTIALLY_REQUIRED` for downstream manifest validation hooks |
| P6 compile service | Credit-free package compilation and V2 binding context | `NOT_REQUIRED` to replace; manifest lineage check is additive |
| P6 scheduler/recovery service | Explicit live authorization, credit confirmation, durable attempts, provider reconciliation | `NOT_REQUIRED` to replace; manifest revalidation is additive |
| Legacy component capacity/composer | Deterministic angle-coherent multiplication idea | `NOT_REQUIRED` as V3 authority; reuse concepts only |
| Legacy CopySet rotation/usage | Historical maintenance and reuse accounting | `NOT_REQUIRED` as V3 authority |

No new Phase 1 runtime adapter was actually required: the existing read models,
source contracts, and direct read-only DB inspection were sufficient to produce
this report. This avoids creating an untested code path solely for forensics.

## NEW V3 RECORDS ACTUALLY REQUIRED

These are schema decisions for a later phase, not records created by this
branch. All future records should be additive in the same canonical database;
Phase 1 performs no migration or table creation.

| Proposed record | Classification | Why |
|---|---|---|
| `angle_v3` | `PARTIALLY_REQUIRED` | V2 candidates provide seed facts, but V3 needs stable revision, lifecycle, objective, compatibility, digest, and review lineage |
| `storyline_family_v3` | `REQUIRED` | No current copy authority provides reusable narrative route identity/revision and cross-storyline compatibility |
| `storyboard_component_v3` | `REQUIRED` | V2 stages are blueprint-local and legacy components are flat; V3 needs formula/stage/storyline/bridge/evidence lineage |
| `master_storyboard_v3` | `REQUIRED` | V2 contains core text but not campaign/recipe/storyline parent, V3 supply lineage, projection parent, or complete receipts |
| `duration_projection_v3` | `REQUIRED` | Durable 8/16/24 projection identity, exact slices, block/WPS/CTA/seam receipts are missing |
| `scene_projection_v3` | `PARTIALLY_REQUIRED` | Treatment/choreography already exists; V3 needs a parent/intent projection link without duplicating visual authority |
| `copy_recipe_v3` | `REQUIRED` | No current object versions target dimensions, formula/angle/storyline policy, counts, duration, novelty, reuse, review, and capacity policy together |
| `storyboard_candidate_v3` or equivalent review envelope | `PARTIALLY_REQUIRED` | V2/P6 have pieces of candidate and audit state; an initial read model may sit over Master/projection records, but review scope/digest must be durable |
| `v3_human_approval_receipt` | `REQUIRED` | No immutable V3 human semantic decision exists over exact full storyboard/projection text |
| `production_copy_supply_manifest_v3` | `REQUIRED` | P6 has plans/items but no bounded multi-copy V3-backed selection/reservation revision |
| `manifest_item_v3` | `REQUIRED` | Each selected copy needs deterministic order and V3/V2/truth/evidence/formula/WPS/compile lineage |
| `landbank_usage_v3` | `REQUIRED` | Existing usage/combination ledgers do not cover V3 component, Master, projection, materialization, manifest, reservation, and reversal events |
| `review_event_v3` | `REQUIRED` | Existing V2/P6 audit is not a V3 review/approval/rejection/archive event stream |
| `materialization_link_v3` | `REQUIRED` | The explicit V3 approved projection to V2 blueprint/revision/binding mapping is missing |
| New V3 Product Truth/evidence fact authority | `NOT_REQUIRED` | Existing approved snapshot, provenance, and `copy_evidence_fact_v2` are canonical |
| New V3 formula or WPS authority | `NOT_REQUIRED` | Checked-in registry/compiler/WPS JSON are canonical |
| New product-global activation pointer | `NOT_REQUIRED` | Existing V2 pointer remains the default interactive authority; manifest selection is bounded and plan-scoped |

The `PARTIALLY_REQUIRED` classifications are intentionally conservative: they
identify where a read projection can reuse existing rows without claiming that
the V3 contract already exists.

## NEW SERVICES ACTUALLY REQUIRED

| Future service | Classification | Required responsibility |
|---|---|---|
| V3 forensic/read-model adapters | `PARTIALLY_REQUIRED` | Read-only views over Product Truth, evidence, formulas, V2, scene/treatment, and P6; this Phase 1 report used direct existing reads instead of adding code |
| V3 recipe service | `REQUIRED` | Version recipe dimensions, formula/angle/storyline policies, target counts, duration/WPS, novelty/reuse, and review policy |
| Angle/storyline compatibility service | `REQUIRED` | Deterministic objective, formula, evidence, bridge, and storyline-family compatibility; reject cross-storyline composition by default |
| Stage-native component supply/capacity service | `REQUIRED` | Count approved components by product/truth/objective/angle/storyline/formula/stage and report the missing next slot |
| Master Storyboard compiler | `REQUIRED` | Resolve components into a complete ordered stage plan with evidence, bridges, digests, and machine gates |
| Duration projection compiler | `PARTIALLY_REQUIRED` | Orchestrate existing canonical compiler/planner and persist V3 projection receipts; do not implement a second WPS algorithm |
| V3 review/approval receipt service | `REQUIRED` | Resolve exact storyboard/projection text, collect human semantic approval, persist immutable receipt, and bind batch/exception scope |
| V2 materialization/carry-forward service | `REQUIRED` | Create V2 DRAFT through the existing V2 service, then perform typed receipt-aware deterministic revalidation |
| Production Supply Manifest service | `REQUIRED` | Select bounded V2 `PRODUCTION_VALID` supply, validate, reserve, rollback, and reconcile without changing V2 activation |
| LandbankUsage/reuse service | `REQUIRED` | Append exact selection/materialization/reservation/queue/start/reversal events and expose reservation/semantic-fatigue signals |
| P6 manifest guard | `PARTIALLY_REQUIRED` | Add manifest digest/item/binding/receipt checks to existing compile/queue/start/recovery boundaries; preserve P6 state machine |
| Evidence selector/ranker | `PARTIALLY_REQUIRED` | Rank existing approved V2 facts against stage/proof needs; never create a parallel fact authority |
| Existing V2/P6 formula, WPS, Product Truth, compile, and scheduler services | `NOT_REQUIRED` | Reuse as current authorities; no replacement or parallel production lane |

## NEW API CONTRACTS ACTUALLY REQUIRED

No V3 API was created in Phase 1. The following classifications apply to the
future contract sketches already approved in the merged architecture.

| API contract(s) | Classification | Evidence/decision |
|---|---|---|
| Existing V2 reads: `GET /api/copy-register/v2/formulas`, `GET /api/copy-register/v2/product/{product_id}/truth`, blueprint/binding reads and resolution | `NOT_REQUIRED` to replace | Current V2 authority is reusable; V3 may call/project it read-only |
| `GET /api/storyboard-landbank/v3/authority/formulas` | `PARTIALLY_REQUIRED` | A V3 read surface may delegate to the canonical registry; no new formula authority |
| `GET /api/storyboard-landbank/v3/recipes`, `GET /api/storyboard-landbank/v3/products/{product_id}/truth`, `GET /api/storyboard-landbank/v3/products/{product_id}/supply` | `REQUIRED` | V3 needs recipe/supply read models with explicit gap and lineage fields |
| `GET /api/storyboard-landbank/v3/review-queue`, `GET /api/storyboard-landbank/v3/landbank`, `GET /api/storyboard-landbank/v3/storyboards/{id}`, `GET /api/storyboard-landbank/v3/storyboards/{id}/projections`, `GET /api/storyboard-landbank/v3/capacity/{run_id}`, `GET /api/storyboard-landbank/v3/approval-receipts/{id}`, `GET /api/storyboard-landbank/v3/production-supply-manifests/{id}` | `REQUIRED` | No current V2/P6 endpoint exposes the complete V3 review/landbank/projection/manifest read contract |
| `POST /api/storyboard-landbank/v3/recipes/preview`, `/components/draft`, `/storyboards/compile`, `/assistant/create`, `/assistant/expand`, `/assistant/fill-capacity` | `REQUIRED` later; not Phase 1 | These are authoring/compile/provider-facing contracts; all output must remain DRAFT or REVIEW_REQUIRED and no route is implemented here |
| `PATCH /api/storyboard-landbank/v3/drafts/{id}`, review approve/reject/archive/delete, `/review/bulk-validate`, `/review/{id}/human-semantic-approve`, `/review/bulk-confirm-machine-clean` | `REQUIRED` later; not Phase 1 | V3 needs explicit review and immutable receipt semantics; machine-clean is not human approval |
| `POST /api/storyboard-landbank/v3/projections/{id}/materialize-v2`, `GET /api/storyboard-landbank/v3/materializations/{id}` | `REQUIRED` later | Typed receipt-aware V2 materialization is missing; route must call V2 service and not write V2 tables directly |
| `POST /api/storyboard-landbank/v3/production-selections`, `/production-supply-manifests`, `/production-supply-manifests/{id}/validate`, `/reserve`, `/rollback`, `/capacity/refresh` | `REQUIRED` later | P6 needs bounded selection/reservation/reconciliation; no current manifest route exists |
| New direct provider/generation endpoint from V3 | `NOT_REQUIRED` and forbidden | ADR-007/V2/P6 remain the only production lane; V3 cannot call a media provider or spend credits |

All future mutating V3 contracts require request ID/idempotency key, actor,
explicit scope/revision, input digest, validation receipt, and fail-closed
lineage checks. Phase 1 intentionally implements none of them.

## RISKS

1. The formula registry's version is derived from a payload hash rather than
   stored as an explicit registry field; any payload change changes the V2
   formula version and invalidates lineage.
2. Three retained WPS profiles are not addressable through the current compiler
   language alias map; silent fallback to Malay would corrupt a V3 projection
   unless the alias gap is closed or rejected.
3. Product Truth has rich JSON/persona material, but empty typed hook,
   subhook, CTA, and pain arrays can be mistaken for supply. Mechanism, proof,
   objection, and pain facts are not separately typed in V2 evidence.
4. The current product's 55 angle candidates are all one formula/objective
   combination and do not establish storyline or duration breadth.
5. No Storyline Family authority exists. Reusing scene strategy or choreography
   IDs as copy storyline would mix visual and semantic authority.
6. V2 approval currently exposes a semantic-review boolean in the resolver
   envelope. V3 carry-forward must preserve the genuine receipt and not invent
   a second boolean or bypass current V2 validation.
7. V2 activation is product-global while V3 recipes/manifests are campaign and
   plan scoped. A manifest must remain a bounded selection record and must not
   mutate the global pointer.
8. P6 historical `copy_set_id` dimensions are easy to misread as legacy
   CopySet references even though current V2 mode stores a binding identity.
9. P6 capacity/DNA/content-combination ledgers are downstream execution
   capacity, not semantic V3 supply. Treating them as storyboard breadth would
   overstate available copies.
10. Legacy CopySet/component imports can reintroduce unreviewed claims,
    missing stage lineage, and flat H/B/CTA assumptions. Any future import must
    be DRAFT and revalidated.
11. Direct read-only DB inspection is safe for this phase, but application
    service reads often sit next to write-capable operations. Future adapters
    need an explicit no-write contract and tests before they are used.
12. The canonical DB is large (`819,294,208` bytes in this baseline); capacity
    reads must remain bounded and indexed when implemented.

## PHASE 2 IMPLEMENTATION INPUTS

Phase 2 may begin only after this report is reviewed and the owner confirms the
schema decision. Its concrete inputs are:

- the exact formula contract matrix and derived versions above;
- the checked-in WPS/block-plan matrix and compiler/planner seam rules above;
- Product Truth and evidence field classifications, including explicit
  `UNSAFE_TO_DERIVE` gaps;
- V2 angle-candidate, blueprint, approval, binding, and current-truth
  revalidation mappings;
- the Storyline Family contract, cross-storyline rejection rule, and bridge
  requirements;
- stage-native component identity, formula/stage/storyline lineage, evidence
  refs, dedupe, and review separation;
- Master Storyboard, Duration Projection, Scene Projection, Recipe, candidate,
  receipt, materialization-link, manifest, and LandbankUsage logical schemas;
- typed approval carry-forward input and exact V2 receipt persistence changes;
- P6 manifest item, reservation, duplicate exclusion, queue/start revalidation,
  rollback, and reconciliation fields;
- the representative capacity baseline and a test fixture that proves the
  difference between V2 executable capacity and V3 semantic/storyline breadth.

The Phase 2 exit gate must be additive same-database schema/validator proof,
rollback-safe, no legacy auto-import, no provider call, no media generation,
no credit spend, no V2 activation, and no P6 queue/start behavior. Phase 2
must not begin in this task.

## READ-ONLY PROOF SUMMARY

| Control | Result |
|---|---|
| Database writes | None; inspection used SQLite `mode=ro` and `PRAGMA query_only=ON` |
| Application mutations | None; no write-capable service or API route was invoked |
| Provider calls | None; no Flow, video, image, or scheduler dispatch was invoked |
| Media credit spend | None; no generation attempt was created by this review |
| V2 activation/materialization | None |
| P6 plan/item/manifest mutation | None; no manifest exists or was reserved |
| Phase 2 implementation | Not started |
