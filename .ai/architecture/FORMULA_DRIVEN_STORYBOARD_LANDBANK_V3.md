# BOSMAX Formula-Driven Storyboard Landbank V3

## STATUS

This is an architecture and implementation blueprint only. It does not implement
database migrations, runtime code, APIs, UI changes, provider calls, Google Flow
generation, or production credit spend.

The operative request was extracted from the pasted mission text supplied with
this task. The attached FAST54 workbook is treated as research/reference input,
not as runtime authority. Repository instructions in AGENTS.md, the AI
contracts, ADR-007, ADR-010, ADR-011, and the engineering lockdown govern the
delivery boundary.

Forensic basis inspected at the current repository head:

- Current head: c58606c67f4d090ca8dd8ec83ff89b8aac064c50.
- Reference workbook: C:\Users\USER\Downloads\FAST54_Modular_Video_Factory_Mini_System.xlsx.
- Product Truth and evidence: agent/services/copy_register_v2_service.py,
  agent/services/copy_eligibility_service.py,
  agent/models/product_intelligence_snapshot.py, and the V2 evidence tables
  in agent/db/schema.py.
- Formula authority: agent/authority/copy_formula_registry.py and
  agent/authority/copy_blueprint_v2_authority.py.
- V2 authority and binding: agent/models/copy_blueprint_v2.py,
  agent/services/copy_blueprint_v2_service.py,
  agent/services/copy_execution_resolver.py, and
  agent/services/copy_register_v2_service.py.
- Canonical WPS/compiler authority:
  agent/authority/wps_blocking_authority.json and
  agent/services/canonical_prompt_compiler.py.
- Storyboard/scene execution authority:
  agent/services/full_storyboard_extend_planner.py,
  agent/models/scene_choreography_v2.py,
  agent/services/scene_choreography_validator.py,
  agent/services/scene_choreography_catalog.py, and the P6 Creative Treatment
  services.
- Production and capacity: agent/services/creative_production_plan_service.py,
  agent/services/creative_production_compile_service.py,
  agent/services/creative_production_scheduler_service.py, and
  agent/models/creative_production.py.
- Current UI: dashboard/src/pages/CopySetRegistryPage.tsx,
  dashboard/src/components/copywriting/CopywritingSourceSelector.tsx,
  dashboard/src/pages/CopyIntelligencePage.tsx, and
  dashboard/src/pages/CreativeProductionStudioPage.tsx.

Current implementation truth:

- The workbook proves the intended modular pattern, including 6 × 3 × 3 =
  54 combinations and 6 + 3 + 3 = 12 source clips. Its sample product also
  carries NEEDS_VERIFICATION truth state, so the workbook cannot promote its
  sample claims into a production landbank.
- ADR-011 makes CopyBlueprintV2 and CopyExecutionBindingV2 the active
  production copy path. Legacy CopySet rows are not a V3 production authority.
- V2 is already formula-native, ordered-stage, evidence-bound, immutable after
  approval, and fail-closed. V3 must supply coherent candidates to V2; it must
  not create a competing last-mile authority.
- Existing atomic copy_component and copy_composer logic is useful forensic
  evidence for deterministic, angle-coherent composition, but its vocabulary
  is HOOK/SUBHOOK/USP_SET/CTA and it has no stage-native BODY contract. It
  cannot be silently reinterpreted as the V3 component source of truth.
- P6 currently projects an approved V2 binding into historical H/B/C-shaped
  DNA fields for compatibility. That projection is an adapter, not permission
  for V3 to author flat H/B/C copy.

Status: architecture review ready. Implementation is intentionally blocked
until the owner decisions in this document are resolved.

## EXECUTIVE ARCHITECTURE DECISION

Build V3 as a formula-first, storyboard-first supply plane above Product Truth
and below the existing V2 production authority:

Product Truth and Evidence
→ Objective
→ Angle
→ Storyline Family
→ Formula Definition
→ Formula Stage Plan
→ stage-native components
→ one coherent Master Storyboard
→ validated Duration Projections
→ optional Scene Projections
→ review and approval
→ V3 Storyboard Landbank
→ explicit V2 materialization
→ V2 approval and execution binding
→ canonical compiler and Production Studio
→ production.

The Master Storyboard is the primary quality unit. A candidate is not a valid
production asset merely because a hook, body, and CTA can be concatenated. The
candidate must represent one ordered formula narrative with explicit
transitions, evidence lineage, claim safety, objective and angle alignment,
duration fit, and novelty.

The duration family is derived, not independently authored:

- The Master Storyboard contains the complete semantic narrative and ordered
  formula stages.
- An 8-second, 16-second, or 24-second Duration Projection allocates that same
  narrative to the canonical WPS and block plan.
- A projection may compress or omit only what its formula contract explicitly
  permits. It may not invent a new hook, body route, claim, or CTA.
- 16 seconds is normally compiled through the retained two-block 8 + 8 plan;
  24 seconds through three 8-second blocks. The authority is
  wps_blocking_authority.json, not an invented V3 duration table.

V2 remains the last-mile authority:

- V3 approval means the supply artifact is coherent and eligible for
  materialization.
- V2 materialization creates a formula-native V2 draft with ordered stages and
  V3 lineage.
- V2 semantic review, readiness proof, Product Truth revalidation, approval,
  and execution binding remain mandatory.
- No V3 artifact bypasses V2 or activates itself in creator or production
  lanes.

The architecture uses one canonical database when implemented. It does not
introduce a second database or a shadow production authority. New V3 storage,
if approved, is additive and versioned in the same database; current V2 and
legacy tables are preserved according to ADR-011 and migration receipts.

## CURRENT STATE FORENSIC MAP

| Surface | What exists now | Authority and constraint | V3 implication |
|---|---|---|---|
| FAST54 workbook | Product DB, angle library, Hook/Body/CTA libraries, Generator, 54 combinations, 12-clip shoot plan, scale calculator, production sheets | Research/input only. Workbook formulas and sample claims are not runtime authority. | Preserve FAST54 as a recipe and capacity target, not a blind Cartesian or claim source. |
| Product Truth | Approved Product Intelligence snapshots, claim gate, allowed/blocked claims, buyer persona, copy strategy, source/evidence lineage | Current approved snapshot is required. Missing/stale/unsafe truth fails closed. | Every angle, component, master, projection, and V2 materialization carries snapshot identity and digest. |
| Evidence | copy_evidence_fact_v2 uses stable fact IDs, canonical text, digest, snapshot lineage, approval state | Claim-bearing stages must cite current approved facts. Wording drift changes digest and requires revalidation. | V3 ranks and selects facts; it never creates a new factual authority. |
| Formula registry | PAS, AIDA, HSO, BAB, PASTOR, PESTA are canonical in the checked-in registry. SavagePAS and HPAS are operator-review drafts. | Formula ID and version are explicit. V2 rejects unknown or missing formula authority. | FormulaDefinition is a contract projection of this registry, not a second formula truth. |
| Product angles | Product Intelligence snapshots carry angle signals; V2 AI angle candidates are immutable, formula/objective/truth-bound rows. | Current V2 Angle is embedded in a blueprint and angle candidates require current truth. | V3 gives angle identity a reusable supply-plane role without changing Product Truth ownership. |
| Legacy CopySet | Monolithic angle, hook, subhook, USP set, CTA, formula family, approval, reuse, similarity, and Product Truth lineage | Historical/maintenance path under ADR-011. It cannot be used as active V3 or production authority. | Preserve for audit. Do not auto-convert a legacy row into an approved Master Storyboard. |
| Atomic copy_component | Deterministic pool keyed by product, angle, type, dedupe key, usage and approval; types are HOOK, SUBHOOK, USP_SET, CTA | Designed for the old CopySetResponse shape. Formula is not a text dimension, and there is no BODY field. | Treat as a legacy composition subsystem. Introduce explicit stage lineage before any V3 reuse. |
| Component composer | Angle-coherent, LRU-first, round-robin, formula-independent combinations; emits COPY_REVIEW_REQUIRED CopySets | It assembles slots but does not compile a formula stage graph or approve output. | Reuse its deterministic ideas, not its flat output contract. |
| Copy Register V2 | Product selection, explicit formula, grounded angle options, 1–5 evidence facts, complete ordered blueprint generation, stage regeneration, approval, activation | V2 blueprint is immutable after approval. Activation binds one approved blueprint to all required copy lanes. | V3 should add landbank workflows upstream and materialize selected candidates into this path. |
| V2 blueprint | Frozen formula stages, evidence references, Product Truth lineage, approval snapshot, approved execution text, duration/WPS fields, derived H/B/CTA projections | Stages are source of truth; H/B/CTA are projections. No legacy fallback in normal mode. | V3 Master Storyboard must preserve stage order and use V2 as materialization/last-mile gate. |
| V2 execution binding | Immutable binding receipt plus mutable per-product/per-lane authority pointer | Consumers revalidate binding, blueprint, Product Truth, evidence, compiler version and flags. | V3 must reference the binding only after explicit V2 materialization and approval. |
| WPS and duration | Canonical compiler reads wps_blocking_authority.json. Safe/Sweet rates and engine block plans are retained authority. | No second WPS table. Unsupported durations or ambiguous lanes fail closed. | DurationProjection delegates budget and block planning to this authority. |
| Full storyboard planner | Builds one complete visual story and dialogue plan before rendering blocks; validates allocation, continuity, CTA placement, dialogue budget and seams. | It is an execution planner for video blocks, especially EXTEND. It is not the V3 copy landbank. | V3 hands approved copy/dialogue and semantic beats into it; it remains downstream execution planning. |
| Scene Choreography V2 | Versioned physical interaction variants, state chains, final locks, character-presence compatibility and SHA lineage | Generic fallback, placeholders, state breaks, incompatible presence, and stale hashes fail closed. | SceneProjection references this authority; it does not duplicate or weaken choreography. |
| Creative Treatment/P6 | Immutable treatment and P6 plan/item/attempt control plane; product, treatment, visual, scene, model, duration, DNA, queue and QA are governed | Treatment is not copy or provider permission. P6 compile and queue revalidate V2 binding and treatment lineage. | Production Studio consumes approved V3-selected/V2-bound supply only. |
| P6 capacity | Product dimension rows currently combine approved copy authority, visual rows, scene variants, layouts, model keys and durations; exact DNA history is excluded; video uses approved treatments and no controlled video reuse. | Capacity is objective evidence, not a provider SLA. Enumeration is capped at MAX_ENUMERATED_COMBINATIONS = 250,000. | V3 must calculate storyboard/projection capacity before P6 and pass bounded selections downstream. |
| Copy usage/reuse | Legacy copy rotation is deterministic, LRU-first and uses owner decision REUSE_CAP = 15. Copy usage increment exists but is not fully wired into the compiler path. | The 15 cap is not a universal V3 law. Content combination is script × visual identity × scene. | V3 needs a separate usage/novelty policy with explicit owner approval and durable event lineage. |
| CopywritingSourceSelector | Reads V2 blueprints, derives a display Hook/Body/CTA summary, blocks drafts, and activates a production-valid blueprint | It is a last-mile selector, not a multi-candidate storyboard queue. | Replace/extend the UX later with recipe, landbank, projection and review-queue concepts without changing V2 authority. |
| CopyIntelligencePage | Workbook upload/dry-run and seed ledger review; explicitly does not seed or send material to generation | Review-only intelligence ingest; not the V3 landbank. | Workbook data can enter a future governed ingestion path only through Product Truth and review gates. |

The forensic conclusion is that the repository already has the strict
last-mile laws V3 needs, but it does not yet have a canonical reusable
storyboard supply object. The current gap is orchestration and storage of
coherent, formula-addressed supply—not a missing provider or a reason to
repair the legacy DOM generation lane.

## ROOT PROBLEMS

1. The workbook's useful modular idea is represented as flat H/B/C
   multiplication. That is a planning shorthand, not a narrative compiler.
   It does not prove that every combination covers every required formula stage.
2. Existing atomic components are shaped around legacy CopySetResponse slots:
   HOOK, SUBHOOK, USP_SET, CTA. A BODY component would currently map to
   nothing. Reusing that table without a versioned contract would create a
   false sense of formula coverage.
3. The same product, angle, and objective can contain multiple narrative routes,
   but the current angle identity has no first-class Storyline Family boundary.
   Without that boundary, a valid-looking component can be combined with the
   wrong reasoning route.
4. A unique text fingerprint is not diversity. The existing coverage service
   correctly distinguishes concentration from breadth, but the coverage
   measurement currently operates on assembled angle-keyed items rather than a
   full formula storyboard landbank.
5. H/B/CTA projections are useful for display and compatibility, but they are
   not sufficient to reconstruct a formula-native V2 blueprint. Treating them as
   the source would flatten PASTOR/PESTA and other multi-stage formulas.
6. The current Copy Register V2 flow is product-at-a-time and blueprint-at-a-time.
   It has explicit generation, review, approval and activation, but no recipe
   capacity job, candidate review queue, bulk exception workflow, or approved
   storyboard landbank.
7. The current P6 capacity service is already stricter than a naïve multiplication
   for visual production, but its copy dimension is an approved V2 authority
   projected into compatibility fields. V3 must not push a raw component matrix
   into P6.
8. Duration and WPS correctness is downstream-critical. Authoring independent
   8/16/24 scripts would create three sources of truth and allow a longer
   projection to drift from the shorter narrative.
9. Scene choreography and copy continuity are related but different. A copy
   storyboard can be semantically coherent while a physical action plan is
   stale or incompatible, and a valid choreography cannot rescue unsupported
   product claims.
10. AI assistance currently has safe V2 primitives, but an assistant that returns
    a loose H+B+C bundle would bypass the strongest repository contracts.
11. Approval and activation have different semantics. Approval freezes an
    artifact; activation changes a mutable authority pointer. V3 must retain
    that distinction and must not make an approved landbank row globally active
    by default.
12. At 10,000 outputs, eager storage of every component Cartesian product or one
    V2 blueprint per theoretical output would create database and review debt
    without adding production diversity.

## FORMULA-FIRST PRINCIPLE

Every candidate begins with a versioned FormulaDefinition. The formula is not a
label attached after generation. It is the compiler contract that determines:

- the ordered persuasion stages;
- the purpose of every stage;
- required versus optional stages;
- which component class may fulfil each stage;
- how Hook, Body, Core and CTA display projections are derived;
- stage entry and exit bridge contracts;
- allowed stage-to-stage continuity;
- claim-bearing and evidence requirements;
- word allocation and duration fit policy;
- CTA closure and final-block rules;
- the formula validator and version that produced the result.

The canonical assembly order is mandatory:

Product Truth → Product Knowledge/Intelligence → Objective → Angle →
Formula → Storyline Family → Formula Stage Plan → stage-native components →
Compatibility → Full Master Storyboard → formula validation → narrative
continuity → evidence/claim validation → duplicate/novelty → duration/WPS
compiler → 8/16/24 projections → scenes/beats → review/approval →
Storyboard Landbank → V2 materialization → production.

The following are invalid:

- a candidate with no formula ID and version;
- a candidate generated as free-floating H+B+C text;
- a candidate whose component formula affinity is only a tag and does not
  explain stage coverage;
- a candidate whose body contains an unannounced claim-bearing stage;
- a candidate whose CTA belongs to a different objective or product truth;
- a candidate whose projection is independently authored instead of derived from
  an approved or reviewable Master Storyboard;
- a candidate that uses the workbook as factual authority;
- a candidate that is unique only because punctuation or component order changed.

The formula registry remains the single formula authority. V3 may add a
read-optimized FormulaDefinition projection, but it must retain the registry's
formula ID, version, stage keys, status and compiler family. Unknown, missing,
stale, or operator-review-only formulas fail closed for production-bound
materialization.

## FORMULA DEFINITION MODEL

FormulaDefinition is a versioned immutable contract read from the canonical
formula registry and materialized into a V3 validation snapshot when a
storyboard is compiled.

Recommended logical fields:

| Field | Meaning |
|---|---|
| formula_id | Stable registry identity such as PAS or PASTOR. |
| formula_version | Registry/contract version hash. |
| display_name | Human-readable name. |
| status | CANONICAL, OPERATOR_REVIEW, DEPRECATED, or BLOCKED. Only CANONICAL can materialize for production. |
| compiler_family | Canonical renderer family and validator version. |
| ordered_stages | Ordered list of FormulaStageDefinition records. |
| projection_mapping | Explicit mapping from formula stages to derived Hook, Body/Core, and CTA displays. |
| stage_requirements | Required/optional, claim-bearing, evidence, bridge and continuity rules for each stage. |
| allocation_policy | Relative word/semantic allocation weights and permitted compression behavior. |
| duration_policy | Supported duration behavior and canonical compiler authority. |
| cta_policy | Final-stage and final-block requirements. |
| definition_digest | Stable digest of the complete definition. |

FormulaStageDefinition contains:

- stage_key and order;
- purpose and semantic role;
- required flag;
- allowed component classes;
- claim-bearing policy;
- evidence minimum and permitted fact kinds;
- entry key and exit key;
- bridge requirement and allowed bridge modes;
- continuity/antecedent requirements;
- minimum semantic payload;
- projection role: HOOK, BODY, CORE, CTA, or NONE;
- word allocation weight;
- compression policy for child Duration Projections.

The current checked-in registry supplies the known canonical stage contracts.
Examples include PAS = problem → agitate → solution → cta and PASTOR =
problem → amplify → story → transformation → offer → response. The exact
stage keys and output mapping must be read from the registry at implementation
time; V3 must not infer them from the workbook's PAS labels.

FormulaDefinition is not a prompt template. It does not author copy, rewrite
approved text, trim text silently, or fall back to another formula. A failed
definition or unsupported version returns a stable blocker such as
FORMULA_DEFINITION_REQUIRED, FORMULA_VERSION_MISMATCH, or
FORMULA_STAGE_CONTRACT_INVALID.

## ANGLE MODEL

An Angle is the strategic promise and audience/objective lens for a product.
It is not a hook sentence, not a formula, and not a Storyline Family.

Recommended logical fields:

- angle_id and angle_revision;
- product_id;
- product truth snapshot ID/version/digest;
- objective_id and objective definition;
- angle definition/core promise;
- intended audience or buyer-persona reference;
- problem/pain context;
- mechanism or reason-to-believe;
- proof/evidence references;
- allowed and blocked claim references;
- compatible formula IDs or formula-neutral flag;
- compatible storyline family IDs;
- source: Product Intelligence, operator, or AI suggestion;
- provider receipt if AI-assisted;
- definition digest and normalized identity key;
- lifecycle status and supersession reference.

Angle identity should be stable across component and storyboard revisions. A
wording revision that changes the promise is a new angle revision or new angle
ID, not a mutation of an approved angle.

The current Product Intelligence snapshot remains the source for acquired facts,
buyer persona, allowed claims, blocked claims and angle signals. V3 may rank
those signals and ask an operator to choose or refine an angle, but it may not
promote an unverified workbook line into Product Truth.

The default compatibility boundary is one product + one current Product Truth
snapshot + one objective + one angle. A component can be reusable across
storyboards only when its angle identity and evidence lineage remain valid.
Cross-angle use is blocked by default, including when the text sounds generic.

## STORYLINE FAMILY MODEL

Storyline Family is the narrative route within one Angle. It answers “how does
this promise unfold?” rather than “what promise is made?”

A family is a versioned contract containing:

- storyline_family_id and revision;
- product, Product Truth, objective and angle lineage;
- family definition and route summary;
- ordered semantic beats;
- permitted formula stage coverage;
- required transitions and bridge keys;
- emotional/argument progression;
- proof placement;
- CTA handoff rule;
- compatible scene/visual intent labels;
- source and review receipt;
- digest and lifecycle state.

Examples such as problem-led, proof-led, routine-led, demo-led, or
comparison-led are conceptual labels only. The repository does not yet provide
a canonical V3 family taxonomy, so implementation must register and review the
taxonomy rather than silently hardcode these names.

Default rule:

- same product;
- same Product Truth snapshot;
- same objective;
- same angle;
- same formula;
- same storyline family.

Cross-storyline composition is rejected unless a declared compatibility contract
proves that the two families share the same promise, stage order, evidence
burden, and closure. “Same product” alone is not sufficient.

Storyline Family is also the unit for diversity reporting. Two candidates with
different hooks but the same angle and storyline may still be one narrative
route. Capacity and novelty must report both component breadth and storyline
breadth.

## COPY COMPONENT MODEL

CopyComponent is a reusable, evidence-bound, stage-addressed supply unit. It is
not production copy by itself and it is not a valid candidate until it is
compiled into a Master Storyboard.

The user-facing component classes are:

- HOOK: opening attention/problem/contrast/curiosity payload;
- BODY: a coherent contiguous middle route that may cover one or more formula
  stages;
- CORE: an internal evidence, mechanism, proof, transformation, or solution
  payload used inside a Body route or explicitly addressed by the Formula Stage
  Plan;
- CTA: final action/response/offer payload.

The storage contract must remain stage-native. Each component carries a
formula_stage_bindings list so that a Body or Core cannot hide the stages it
fulfils. A component may cover multiple contiguous stages only when the
FormulaDefinition allows that grouping and the component supplies each
stage's required semantic and evidence metadata.

Recommended fields:

| Field | Requirement |
|---|---|
| component_id/revision | Immutable identity and revision. |
| product_id | Exact product scope. |
| product_truth_lineage | Snapshot ID/version/digest and canonical product identity. |
| objective_id | Objective compatibility. |
| angle_id/revision | Strategic promise compatibility. |
| storyline_family_id/revision | Narrative-route compatibility. |
| formula_id/version | Formula contract compatibility; never a decorative tag. |
| component_class | HOOK, BODY, CORE, or CTA. |
| formula_stage_bindings | Ordered stage keys, coverage, and semantic role. |
| authored_text | Candidate text, immutable after approval. |
| entry_key/exit_key | Bridge graph endpoints. |
| bridge_contract | Required/optional bridge, antecedent and handoff rules. |
| claim_bearing | Whether the component makes a factual or outcome claim. |
| evidence_refs | Stable approved fact IDs and digests for every claim-bearing clause. |
| word_count/language | Compiler input metadata. |
| source/provenance | Human, AI, workbook-derived draft, or imported source with receipt. |
| exact_text_digest/semantic_fingerprint | Dedupe and novelty identity. |
| status | DRAFT, REVIEW_REQUIRED, APPROVED, REJECTED, ARCHIVED, SUPERSEDED, or BLOCKED. |
| reviewer/approval snapshot | Human decision and input lineage. |
| usage ledger reference | Usage/fatigue events, not a mutable counter only. |

The current copy_component table is not this contract. It lacks Body and
stage-native formula coverage, and its existing composer intentionally treats
formula as a non-text dimension. V3 implementation must either introduce
explicit versioned stage semantics in the same canonical database or create
new V3 tables in that same database. It must not reinterpret existing rows
without a migration receipt and revalidation.

Component approval is narrower than storyboard approval. A component can be
approved as a reusable supply input while a specific combination remains
blocked by continuity, formula, evidence, duration, or novelty gates.

## MASTER STORYBOARD MODEL

MasterStoryboard is the primary quality unit and the canonical V3 narrative
artifact. It contains one complete coherent story before duration projection or
scene rendering.

Recommended fields:

- master_storyboard_id and revision;
- campaign or recipe scope;
- product and current Product Truth lineage;
- objective;
- angle and storyline family lineage;
- formula ID/version and full FormulaDefinition digest;
- ordered FormulaStagePlan;
- ordered stage nodes with component references and resolved text;
- stage-to-stage bridge contracts;
- evidence map by stage and clause;
- narrative summary and semantic arc;
- hook, body/core, and CTA display projections;
- semantic word count before duration allocation;
- master digest and input fingerprint;
- compatibility, evidence, safety, novelty and formula validation receipts;
- lifecycle state;
- source/provenance and supersession lineage.

FormulaStagePlan is explicit, not inferred from text. Each stage node records:

- stage key and order;
- resolved component IDs/revisions;
- resolved authored text;
- semantic purpose;
- entry and exit bridge;
- claim-bearing clauses;
- evidence refs;
- continuity anchors;
- permitted projection/compression behavior.

The Master Storyboard must validate as a whole:

1. exact formula ID/version and ordered required stages;
2. one product and current Product Truth lineage;
3. one objective, angle and storyline family;
4. complete stage coverage;
5. valid H→Body/Core and Body/Core→CTA bridges;
6. no ungrounded claim or product identity drift;
7. narrative antecedents and closure;
8. no exact or near duplicate candidate under the selected novelty policy;
9. a valid projection path for the requested duration family;
10. a human-reviewable provenance record.

The Master Storyboard is not the same object as the existing
FullStoryPlan/FullDialoguePlan used by the execution planner. The V3 Master
Storyboard is copy supply and persuasion logic. The existing planner is
downstream visual/dialogue allocation and continuity execution. V3 should
export the semantic inputs that the existing planner needs rather than create a
second video execution planner.

## WPS PROFILE MODEL

WPSProfile is a read-only, versioned view of the canonical authority used for
duration validation. It is not a place to hand-enter arbitrary words-per-second
values.

The implementation must read the retained values from
agent/authority/wps_blocking_authority.json through the canonical prompt
compiler. Current retained language profiles include Malay, English, Mandarin,
Hindustani, Tamil, Bengali, Indonesian, Burmese and Thai, with safe, sweet,
minimum, maximum and ceiling fields. The exact values remain owned by that
authority file.

Recommended logical fields:

- wps_profile_id and authority_version;
- engine/provider family;
- target language;
- mode: SAFE or SWEET;
- min/safe/max/sweet/ceiling values from the authority;
- source digest;
- block-plan authority reference;
- continuation/seam notes;
- calibration status and effective dates.

Rules:

- No invented WPS profile is valid.
- No V3 table may diverge from the canonical authority.
- A language or provider profile not present in the authority returns
  WPS_PROFILE_UNAVAILABLE or CALIBRATION_REQUIRED.
- WPS budget is a validation/compiler input, not a license to trim approved
  copy silently.
- The final CTA must fit the final block; if it cannot, the projection fails
  closed with a duration/CTA fit error.

The workbook's modular shoot durations (approximately 2.5 seconds for hooks
and CTAs and 6 seconds for bodies) are useful production research, but they do
not replace the retained language WPS or Google Flow block-plan authority.

## DURATION PROJECTION MODEL

DurationProjection is a child of one MasterStoryboard revision. It is derived
by a deterministic projection compiler and never authored as an unrelated
script.

Required fields:

- projection_id and revision;
- master_storyboard_id/revision;
- target duration, target language and WPS profile/version;
- engine and preferred lane when the authority requires one;
- resolved block plan, for example 8, 8 + 8, or 8 + 8 + 8;
- stage allocation and beat allocation per block;
- per-block and total word budgets;
- actual word count and speaking-window metadata;
- compression/omission receipt;
- exact dialogue slices;
- final CTA block and end-frame intent;
- continuity in/out state references;
- validation receipts and digest;
- status and supersession lineage.

Projection rules:

1. Start with the full Master Storyboard.
2. Resolve the canonical block plan using the existing authority.
3. Allocate formula stages and semantic beats without changing order.
4. Allocate dialogue against canonical WPS.
5. Preserve Hook, Body/Core, and CTA intent in every supported projection.
6. Keep the CTA in the final block under the canonical compiler law.
7. Preserve cross-block continuity and seam constraints.
8. Fail closed when the formula, CTA, evidence, or narrative cannot fit.

An 8-second projection may use a compact representation of the Master
Storyboard; it may not replace the story with a newly generated 8-second hook.
A 16-second projection may expose two 8-second execution blocks; a 24-second
projection may expose three. These blocks are delivery allocations, not three
independent authored stories.

A projection is not automatically a V2 blueprint. It is a validated V3 child
that becomes a V2 draft only through explicit materialization.

## SCENE PROJECTION MODEL

SceneProjection maps copy beats and duration blocks to visual execution
references. It is a bridge object, not a replacement for Scene Choreography V2
or Creative Treatment.

Recommended fields:

- scene_projection_id and revision;
- master/projection IDs and beat mapping;
- scene strategy ID and selected choreography ID;
- choreography SHA and catalog/library SHA;
- scene context, camera route and character-presence compatibility;
- ordered visual beat references;
- product state and copy-intent mapping;
- treatment/segment plan reference when already materialized;
- visual fingerprint and dependency hashes;
- validation receipt and status.

SceneProjection must reference the current production choreography catalog and
validate:

- strategy is non-fallback and production eligible;
- choreography schema version matches;
- action/entity states form a continuous chain;
- final state lock closes the scene;
- selected character presence is allowed;
- stored choreography SHA is current;
- no placeholder state or positive physical branch is present.

SceneProjection must not copy the full choreography payload into every
storyboard candidate. It stores stable IDs, hashes and the minimal beat map
needed for review. Creative Treatment remains the immutable P6 visual contract.
The copy landbank can say “show the approved proof beat” but cannot rewrite a
physical action or authorize generation.

## COPY RECIPE MODEL

CopyRecipe is the operator-facing supply plan. It controls dimensions and
acceptance criteria; it does not bypass any candidate gate.

Common recipes:

- QUICK TEST;
- FAST54;
- MULTI-ANGLE;
- SCALE;
- CUSTOM.

Recommended fields:

- recipe_id/version and name;
- product or campaign scope;
- objective;
- allowed formula IDs/versions;
- angle selection policy;
- storyline family selection policy;
- component counts by class and stage;
- target master/storyboard count;
- target duration projections;
- coverage requirements;
- novelty/reuse policy;
- scene/treatment policy;
- review policy;
- capacity objective and shortfall behavior;
- recipe digest and owner.

Recipes must distinguish:

- requested capacity: what the operator wants;
- theoretical capacity: what the dimensions could produce before gates;
- valid candidate capacity: what passes formula, truth, continuity and novelty;
- approved landbank capacity: what a human approved;
- executable capacity: what can materialize to V2 and satisfy downstream
  treatment/P6 gates.

The recipe is a policy input, not an output authority. Changing a recipe
creates a new recipe revision and does not mutate an approved storyboard.

## FAST54 MAPPING

The workbook's FAST54 model maps into V3 as follows:

| Workbook concept | V3 interpretation |
|---|---|
| Product DB | Product Truth and Evidence Registry snapshot. |
| Set Manager | CopyRecipe with one product, one objective, one angle, one formula and one storyline family. |
| Angle Library | Angle identities and revisions, grounded in Product Intelligence and approved facts. |
| Hook Library | Approved HOOK components mapped to formula opening stages. |
| Body Library | Approved BODY/CORE routes with explicit stage coverage and bridges. |
| CTA Library | Approved CTA components mapped to final formula action/response stage. |
| Generator | Candidate compiler that produces Master Storyboards, not loose H/B/C rows. |
| 54 Combinations | At most 6 × 3 × 3 candidate attempts under one recipe; valid unique storyboards may be fewer. |
| Shoot Plan | Optional source-clip planning input, downstream of approved semantic/scene projections. |
| 54 Combination sheet | Reviewable Storyboard Candidate/Projection rows with gate receipts. |
| Scale Calculator | Recipe capacity service with valid-storyboard and projection counts, not raw multiplication. |
| Production Queue | P6 plan, treatment, compile, queue and scheduler authorities. |

FAST54 candidate construction:

1. Resolve current Product Truth.
2. Select one explicit objective.
3. Select one angle and one storyline family.
4. Select one canonical formula/version.
5. Select one of six Hook variants.
6. Select one of three Body/Core routes.
7. Select one of three CTA variants.
8. Expand the selections into the formula's ordered stage plan.
9. Compile one Master Storyboard.
10. Run compatibility, bridge, evidence, safety, continuity, novelty and
    duration checks.
11. Persist only a reviewable candidate/landbank artifact; never auto-approve.

The number 54 is a recipe target, not a guarantee. A candidate is removed from
valid capacity if any required formula stage is missing, if the bridge fails,
if evidence is unavailable, if the Product Truth snapshot is stale, if a
duplicate/novelty policy blocks it, or if no requested projection fits WPS.
The formula count is not blindly multiplied into 54. A different formula is a
new semantic contract; it produces additional capacity only when its stage
plan and resolved text are materially distinct and valid.

Workbook sample statuses remain meaningful forensic warnings: the sample
product's NEEDS_VERIFICATION truth gate means its apparent 54 outputs are
blocked, not ready. The workbook's unverified FAST acronym explanation is not
treated as a repository authority.

## COMPATIBILITY ENGINE

Compatibility is a deterministic multi-gate evaluator. It returns hard
blockers, warnings, scores and evidence, not one opaque percentage.

Hard gates:

1. Product identity and current Product Truth snapshot match.
2. Product is active and copy-eligible.
3. Objective matches all selected components and storyline family.
4. Angle identity and revision match.
5. Formula ID/version is canonical and its ordered stages are complete.
6. Every selected component is bound to an allowed formula stage.
7. Stage order and bridge entry/exit keys are contiguous.
8. Claim-bearing text has current approved evidence.
9. Product, audience, offer and claim safety are compatible.
10. Language/WPS/duration projection is supported.
11. Requested scene/treatment compatibility is valid where required.
12. Exact duplicate, stale lineage and hard novelty blockers are absent.

Soft signals:

- angle breadth and storyline breadth;
- semantic novelty;
- component usage/fatigue;
- proof diversity;
- hook mechanism diversity;
- scene and visual variation;
- estimated reviewer effort.

Compatibility defaults to same product + objective + angle + formula +
storyline. An empty/global CTA is not automatically compatible; it must still
match the objective, offer and claim safety. Cross-angle or cross-storyline
reuse requires an explicit compatibility proof and owner-approved policy.

Suggested reason codes include:

- PRODUCT_TRUTH_STALE;
- PRODUCT_IDENTITY_MISMATCH;
- OBJECTIVE_MISMATCH;
- ANGLE_MISMATCH;
- STORYLINE_FAMILY_MISMATCH;
- FORMULA_UNKNOWN;
- FORMULA_VERSION_MISMATCH;
- FORMULA_STAGE_MISSING;
- FORMULA_STAGE_ORDER_INVALID;
- COMPONENT_STAGE_UNBOUND;
- BRIDGE_ENTRY_MISMATCH;
- BRIDGE_EXIT_MISMATCH;
- EVIDENCE_MISSING;
- EVIDENCE_STALE;
- CLAIM_GATE_BLOCKED;
- WPS_PROFILE_UNAVAILABLE;
- DURATION_FIT_FAILED;
- CTA_FINAL_BLOCK_FAILED;
- STORYBOARD_DUPLICATE;
- NOVELTY_SHORTFALL;
- SCENE_CHOREOGRAPHY_STALE.

The engine must be pure and reproducible for the same input snapshot. A
compatibility score cannot override a hard gate.

## NARRATIVE CONTINUITY ENGINE

The continuity engine validates the entire Master Storyboard as a directed
stage graph:

Hook/stage 1
→ contiguous stage bridge
→ Body/Core stage sequence
→ evidence/proof/solution transition
→ final CTA/response stage
→ closure.

Every stage node supplies:

- entry key and required antecedent;
- authored text;
- exit key;
- semantic role;
- continuity anchors;
- evidence clauses;
- permitted next-stage keys.

Validation includes:

- ordered formula stage equality;
- no missing or duplicate stage;
- entry of stage N matches exit of stage N-1;
- no sentence that depends on absent previous context;
- no unexplained pronoun, “as mentioned”, “this”, or “that” without an
  available antecedent;
- no angle or objective switch inside the story;
- product identity remains stable;
- bridge wording does not introduce an unsupported claim;
- Body/Core is not merely a sentence fragment that requires the Hook;
- CTA is grammatically and semantically closed;
- final CTA remains in the final Duration Projection block.

The existing full_storyboard_extend_planner already enforces one complete story
before block allocation, continuous visual state, dialogue allocation,
duration sum, CTA placement and seam laws. V3 should feed it an approved
dialogue/story semantic payload and use its validation receipts. V3 should not
reimplement those execution seam rules in a second planner.

## EVIDENCE RANKING ENGINE

The evidence engine selects and ranks approved facts from the current Product
Truth snapshot. It is a relevance service, not a fact generator.

Inputs:

- product and variant identity;
- objective;
- angle promise;
- storyline family proof need;
- formula stage purpose;
- claim risk and blocked claims;
- target language;
- available approved EvidenceFact IDs and digests.

Ranking dimensions:

1. exact product/variant match;
2. current snapshot and approved state;
3. direct relevance to the formula stage purpose;
4. direct support for the selected angle and objective;
5. proof strength/source quality;
6. claim-risk fit;
7. reuse/fatigue balance where multiple facts support the same stage;
8. text specificity and identity safety.

Claim-bearing stages must reference precise fact IDs. A stage may use several
facts, but every fact must belong to the current snapshot and pass digest
validation. If no fact can support a required claim, the candidate is blocked.

Manual override is an advanced review action. It can choose among approved
facts or mark a stage as non-claim-bearing when the text is corrected, but it
cannot add an unapproved fact or suppress a required evidence failure. The
override, actor, reason and input digest are part of the review receipt.

The existing V2 service's stable fact identity convention and
copy_evidence_fact_v2 persistence are the starting point. V3 should consume
those facts rather than create a competing Product Truth or evidence table.

## DUPLICATE / NOVELTY ENGINE

Novelty has several layers. No single score is authoritative.

1. Exact component text: normalized text digest within product/stage/class.
2. Exact storyboard: product, truth snapshot, objective, angle, storyline,
   formula/version, ordered stage text and evidence map.
3. Exact duration projection: master revision, duration, language, WPS,
   exact dialogue and block plan.
4. Near-duplicate copy: existing deterministic token/Levenshtein/Jaccard
   baseline, with the current 0.80 threshold as a review signal rather than a
   universal V3 blocker.
5. Semantic route novelty: angle and storyline distribution.
6. Component concentration: usage/fatigue and repeated hook/body/core/CTA
   mechanisms.
7. On-platform combination: script/dialogue identity × visual identity × scene,
   using the existing content-combination ledger downstream.
8. Visual/choreography novelty: treatment and visual/choreography fingerprints.

Hard blockers:

- same approved storyboard digest;
- same projection digest in the same requested production scope;
- stale or superseded source lineage;
- duplicate candidate explicitly excluded by a recipe;
- claim/evidence or formula failure.

Warnings:

- near duplicate above review threshold;
- angle monoculture;
- storyline monoculture;
- component fatigue;
- proof repetition;
- visual reuse pressure.

The current copy coverage service correctly reports concentration and breadth
relative to available angles. V3 extends the same principle to storyline family
and formula-stage route. “Unique” must never be displayed as “diverse.”

The existing REUSE_CAP = 15 is a legacy owner decision for CopySet rotation and
must not silently become V3 policy. V3 usage is recorded by artifact and
projection, with a recipe/production policy deciding whether reuse is allowed.

## COMPONENT LANDBANK

Component Landbank is the approved supply pool of stage-addressed components.
It is distinct from the Storyboard Landbank:

| Component Landbank | Storyboard Landbank |
|---|---|
| Reusable HOOK/BODY/CORE/CTA or stage units | Complete ordered formula narrative |
| Capacity input | Production candidate/output |
| Can be approved independently | Must pass whole-story validation |
| May be reused inside compatible families | Must be novel under selected scope |
| No direct Production Studio consumption | Only approved projections may feed materialization |

Component lifecycle:

DRAFT → REVIEW_REQUIRED → APPROVED → ARCHIVED/SUPERSEDED

REJECTED and BLOCKED are terminal for that revision. Approved component text,
truth lineage, formula bindings, stage bindings and evidence refs are immutable.
A correction creates a new revision.

Component Landbank views:

- supply by product, angle, storyline family, formula and stage;
- missing stage/bridge types;
- evidence coverage;
- component novelty and usage;
- rejected/stale/blocked reasons;
- marginal capacity unlocked by the next component;
- provenance and human-review receipts.

The landbank must never report raw component count as production capacity. A
component is useful only when it participates in at least one valid Master
Storyboard and requested projection.

## STORYBOARD LANDBANK

Storyboard Landbank is the approved supply of complete Master Storyboards and
their validated Duration Projections. It is the only V3 source from which the
Production Studio integration may select a copy candidate.

Artifact relationship:

Campaign/Recipe
→ Master Storyboard revision
→ Duration Projection revision(s)
→ optional Scene Projection
→ V2 materialization link.

Landbank statuses:

- DRAFT: generated or edited but not reviewable as final;
- REVIEW_REQUIRED: all machine gates pass, human review required;
- APPROVED: human approved supply artifact;
- READY_FOR_MATERIALIZATION: approved and current, with selected projection;
- MATERIALIZED: V2 draft exists, not yet V2 approved;
- ACTIVE_IN_V2: V2 approval and binding exist for the selected lane scope;
- REJECTED: reviewed and not accepted;
- ARCHIVED: intentionally withdrawn, never deleted if referenced;
- SUPERSEDED: replaced by a new revision;
- BLOCKED: a hard gate or stale lineage prevents use.

Approved Master Storyboards and projections are immutable. Landbank activation
is a selection pointer, not a mutation of the approved artifact. A current
Product Truth change may derive BLOCKED/STALE status, but does not rewrite the
approved row.

The landbank should store canonical stage text and references, not duplicate
the same text for every visual output. An output-specific combination belongs
to P6/content-combination planning after the copy projection is selected.

## REVIEW QUEUE / CRUD

The Copy Register V3 target has four jobs:

1. Setup campaign.
2. Build Storyboard Landbank.
3. Review Queue.
4. Storyboard Landbank.

Review Queue operations:

- create a campaign, recipe, angle set, storyline family set and target;
- generate candidates in deterministic batches;
- inspect full Master Storyboard with formula stage graph;
- inspect each Duration Projection and its WPS/CTA receipt;
- inspect scene mapping separately from copy;
- edit/save DRAFT text or metadata;
- regenerate a stage as a new revision;
- approve an individual component, master, or selected projection;
- reject with reason;
- archive an approved artifact;
- delete an unused, unreferenced DRAFT only;
- bulk review all candidates and surface exceptions;
- bulk approval may approve only after a human confirms the validated batch;
- materialize a selected approved projection to a V2 DRAFT;
- open the V2 review/approval path;
- activate only through the existing V2 activation contract.

CRUD rules:

- No edit in place after APPROVED.
- No hard delete after an artifact is approved or referenced.
- Deletion of a draft is a soft/deletion event with actor and reason.
- Rejection does not delete content.
- Regeneration creates a revision and preserves the parent.
- Bulk actions are idempotent and record request ID, actor, batch digest and
  exception set.
- An approved master does not silently approve a projection if the chosen
  projection has a different duration, language, WPS, or resolved text.
- Bulk approval never activates V2 or starts production.

The current Copy Register V2 UI covers formula selection, Product Truth,
grounded angles, evidence facts, complete blueprint generation, stage
regeneration, human approval and activation. It does not yet expose these V3
queue/recipe/landbank objects. The current CopywritingSourceSelector is
appropriate as a downstream V2 selector but must not be treated as the V3
review queue.

## AI COPY ASSISTANT

AI Copy Assistant is an orchestrator over the same Product Truth, Formula
Definition, Component Landbank and Storyboard Landbank. It is not a separate
source of truth and it does not have a prompt-to-production path.

Modes:

### CREATE

Given product, objective, angle, storyline family and formula, create missing
stage-native component drafts and compile one or more Master Storyboard
candidates. Validate the full graph before submitting REVIEW_REQUIRED.

### EXPAND

Inspect current approved supply, identify missing stages, bridge types,
storyline routes, evidence coverage or novelty breadth, and generate only the
missing component/candidate families. Do not repeatedly generate more of a
dominant angle when another available angle is uncovered.

### FILL_CAPACITY

Consume a Copy Capacity Service shortfall report. Generate toward the named
deficit dimensions, for example missing CTA variants for a formula-stage route
or missing 16-second projection fit. Every result is still compiled as a full
Master Storyboard and validated.

Assistant contract:

- reads current Product Truth and approved facts;
- uses explicit formula/version;
- uses an approved or reviewable angle and storyline family;
- cites evidence per claim-bearing stage;
- generates DRAFT or REVIEW_REQUIRED only;
- stores provider receipt and prompt/version provenance if a future text-assist
  implementation is authorized;
- runs deterministic local formula, bridge, safety, continuity, WPS and novelty
  validation;
- never auto-approves, activates, binds, queues, clicks Generate, or spends
  Google Flow credits;
- never falls back to an old CopySet or an unknown formula;
- never returns a loose H+B+C bundle as production-ready output.

The current V2 text-assist lane is explicit and reports zero media credit
spend. That does not authorize calling it during this architecture task or
authorize provider token use in a future implementation without the owner's
separate policy.

## COPY CAPACITY SERVICE

Capacity is measured at Master Storyboard and Duration Projection level.
Component multiplication is only an upper bound.

Recommended capacity layers:

1. SEMANTIC_CAPACITY: approved, current Master Storyboards.
2. PROJECTION_CAPACITY: valid child projections by duration/language/WPS.
3. EXECUTABLE_COPY_CAPACITY: projections that can materialize into V2 with
   current truth/evidence and the required lane.
4. PRODUCTION_CAPACITY: the minimum of executable copy, approved visual/
   choreography/treatment supply, content-combination novelty, and P6 lane
   window capacity.

For a recipe R:

valid_masters(R) = count of unique approved masters that pass all hard gates.

valid_projections(R, d) = count of approved/current projections for duration d
that pass WPS, CTA, continuity, novelty and materialization checks.

production_capacity(R, d) = min(
  valid_projections(R, d),
  visual_and_treatment_capacity(R, d),
  content_combination_capacity(R, d),
  verified_lane_window_capacity(R, d)
).

No formula_count × hooks × bodies × CTAs result may be reported as safe
capacity without applying these gates.

Capacity response:

- status: READY or SHORTFALL;
- requested masters and requested projections;
- valid masters/projections;
- stale/blocked/rejected/excluded counts;
- dimension pressure by product, angle, storyline, formula, stage, duration,
  language, evidence, scene and novelty;
- exact candidate digests excluded by history;
- next-best authoring actions;
- whether the result is semantic, executable, or production capacity;
- snapshot digest and request ID.

Shortfall codes should identify actionable supply gaps:

- MISSING_PRODUCT_TRUTH;
- MISSING_ANGLE;
- MISSING_STORYLINE_FAMILY;
- MISSING_FORMULA_STAGE;
- MISSING_HOOK_VARIETY;
- MISSING_BODY_CORE_ROUTE;
- MISSING_CTA_VARIETY;
- BRIDGE_SHORTFALL;
- EVIDENCE_SHORTFALL;
- WPS_DURATION_FIT_SHORTFALL;
- NOVELTY_SHORTFALL;
- SCENE_OR_TREATMENT_SHORTFALL;
- V2_MATERIALIZATION_SHORTFALL;
- P6_LANE_WINDOW_SHORTFALL.

The existing P6 preflight remains downstream evidence. Its current
approved-pool, exact-DNA-history, treatment and lane-window checks should be
fed a bounded V2-backed selection, not an unbounded V3 matrix. Capacity is an
objective, not a provider SLA.

## PRODUCTION STUDIO INTEGRATION

Production Studio is a consumer of approved production supply, not a copy
authoring surface.

Current forensic path:

- P6 loads product, scene strategy, approved visual/treatment resources, model
  and duration pools.
- Under ADR-011, P6 resolves a persisted V2 binding for
  PRODUCTION_STUDIO_P6.
- The service projects V2's derived Hook/Body/CTA view into historical P6
  dimension fields so DNA and compatibility code can continue to operate.
- P6 compilation passes V2 context into the workspace generation package and
  revalidates the persisted binding at queue/start.
- Creative Treatment and Scene Choreography remain separate immutable visual
  authorities.

Target V3 integration:

1. Production Studio selects an APPROVED Storyboard Landbank projection, not a
   raw component, legacy CopySet, or free-text override.
2. The selection resolves to a V3 master/projection digest and current Product
   Truth.
3. An explicit materializer creates or retrieves the corresponding V2 DRAFT.
4. The existing V2 approval, binding and activation gates run.
5. P6 receives the V2 binding, approved execution text, projection lineage and
   selected visual/treatment context.
6. P6 builds the bounded content matrix and applies its existing DNA,
   historical-combination, treatment, queue and credit controls.
7. Queue/start revalidates Product Truth, V2 binding, projection/materialization
   link, treatment hashes and lane readiness.

For copy-required video and poster lanes, no raw V3 text may reach the engine.
For explicitly copy-free image lanes, the existing COPY_NOT_REQUIRED policy
remains explicit. P6 does not auto-approve V3 or V2 and does not inherit a
copy reuse policy silently.

## V2 MATERIALIZATION

V2 materialization is an explicit adapter:

V3 Master Storyboard + selected Duration Projection
→ V2 CopyBlueprintV2 DRAFT
→ V2 validation
→ human semantic review and readiness proof
→ V2 PRODUCTION_VALID
→ CopyExecutionBindingV2
→ explicit activation/selection.

Materialization rules:

- Lazy materialization is the default. Do not create a V2 blueprint for every
  theoretical combination.
- Materialize only a selected approved projection or an explicitly selected
  review batch.
- Preserve V3 master ID/revision, projection ID/revision, recipe ID/revision,
  component revisions, storyline family, and digests in structured provenance.
- Map every V3 FormulaStagePlan node to an ordered V2 FormulaStage.
- Preserve V3 evidence references as current V2 evidence references.
- Set target duration/WPS only from canonical V2/compiler authority.
- Resolve derived Hook/Body/CTA only as V2 projections.
- Do not rewrite or flatten a multi-stage formula into three text slots.
- Run V2 Product Truth/evidence/current-authority validation again at
  materialization time.
- Materialization creates a V2 DRAFT. It never creates an approved V2 row.
- V2 approval and activation remain human and explicit.

One V2 blueprint may be bound to the required lanes according to the current
V2 activation contract. V3 must not create one V2 blueprint per visual output
or per P6 item. Output-level uniqueness belongs to P6's dialogue/visual/
scene combination ledger.

Approved V2 text is immutable. If an operator changes a V3 source after
materialization, the correct result is a new V3 revision and a new V2 draft;
there is no in-place synchronization of approved text.

## APPROVAL / IMMUTABILITY

There are three distinct governance layers:

1. Component approval: the reusable component is safe and correctly
   evidence-bound for its declared stage/identity.
2. Storyboard approval: the complete master and selected projection are
   coherent, novel enough for the recipe, and ready for V2 materialization.
3. V2 production approval: the materialized ordered-stage blueprint passes
   current V2 validation, semantic review, readiness proof and immutable
   approval snapshot.

Approval invariants:

- DRAFT and REVIEW_REQUIRED are mutable only through revision-safe operations.
- APPROVED artifacts cannot be edited in place.
- Rejection preserves the reviewed content and reason.
- Archive removes supply from active capacity but preserves history.
- Supersession points to the replacement revision.
- Current Product Truth drift marks artifacts stale/blocked; it never rewrites
  their historical content.
- Approval records actor, timestamp, rationale, input snapshot/digest and
  validator versions.
- Bulk review cannot become invisible bulk approval.
- Activation changes a pointer/selection, not an immutable artifact.
- Production binding is a receipt over approved inputs, not a permission to
  mutate those inputs.

The current V2 database triggers and frozen models are the precedent. V3
implementation should use the same fail-closed posture, including database
guards where they are already the repository pattern, but no such migration is
part of this document.

## DATABASE / STORAGE MODEL

This is a logical storage model for a future implementation. It is not a
migration plan being executed now.

Canonical existing authorities to reference, not duplicate:

- product and Product Truth snapshot;
- copy_evidence_fact_v2;
- checked-in formula registry and WPS authority;
- copy_blueprint_v2;
- copy_execution_binding_v2 and authority pointer;
- Creative Treatment and Scene Choreography V2;
- P6 plan/item/attempt/audit tables;
- content_combination and downstream artifact ledgers.

Recommended additive V3 logical records in the same canonical database:

### angle_v3

Identity/revision, product/truth lineage, objective, definition, audience,
proof, compatibility, source, digest and lifecycle. The row is immutable after
approval.

### storyline_family_v3

Identity/revision, angle lineage, ordered route, formula compatibility,
transitions, proof placement, CTA closure, source, digest and lifecycle.

### storyboard_component_v3

Identity/revision, product/truth/objective/angle/storyline/formula lineage,
component class, stage bindings, text, bridges, evidence refs, word count,
dedupe/semantic fingerprints, source, approval and usage linkage.

### master_storyboard_v3

Identity/revision, campaign/recipe, product/truth/objective/angle/storyline/
formula snapshot, ordered stage plan, resolved component refs, evidence map,
semantic summary, digests, validation receipts, lifecycle and supersession.

### duration_projection_v3

Identity/revision, master lineage, target duration/language/WPS/engine, block
plan, allocations, exact dialogue slices, word budgets, CTA placement,
continuity states, validation receipts, digest and lifecycle.

### scene_projection_v3

Identity/revision, master/projection lineage, scene strategy, choreography IDs
and SHAs, beat map, treatment linkage, visual fingerprint and validation.

### copy_recipe_v3

Identity/revision, campaign scope, dimensions, formulas, angles, storyline
policy, count targets, duration targets, novelty/reuse policy, review policy,
capacity snapshot and owner.

### storyboard_candidate_v3 or equivalent review envelope

A generated candidate should have a stable ID, master/projection references,
recipe/run ID, full gate receipt, exception list, digest, status and actor
events. This may be a physical table or a review read model over the master and
projection tables; it must not duplicate the entire text payload.

### landbank_usage_v3

Append-only usage events for component, master, projection, V2 materialization,
P6 selection and downstream combination. Include actor, lane, campaign,
request ID, input digest, outcome and reversal/dead-state evidence.

### review_event_v3 and materialization_link_v3

Append-only review/approval/rejection/archive events and the explicit mapping
between a V3 approved projection and a V2 blueprint/revision/binding.

Keys and indexes:

- unique identity on product/truth/objective/angle/storyline/formula/revision;
- stage and status indexes for capacity;
- product/recipe/campaign/duration/language indexes;
- evidence fact and truth snapshot indexes;
- digest indexes for exact dedupe;
- parent/child indexes for master → projection → materialization;
- append-only event indexes by request ID and actor;
- no uniqueness rule that treats a formula label as a new text combination when
  the resolved stage text is identical.

Storage rules:

- JSON can hold versioned receipts and stage maps, but queryable lineage keys
  should be first-class indexed fields.
- Store references and digests instead of copying visual/choreography payloads.
- Use one canonical database. Do not create a parallel V3 database.
- Use transactions for candidate batch creation and review status transitions.
- Preserve legacy rows and their migration receipts; do not mutate them to look
  like V3.

## API CONTRACTS

The following are future contract sketches only. No route is created by this
document.

Read contracts:

- GET /api/storyboard-landbank/v3/authority/formulas
- GET /api/storyboard-landbank/v3/recipes
- GET /api/storyboard-landbank/v3/products/{product_id}/truth
- GET /api/storyboard-landbank/v3/products/{product_id}/supply
- GET /api/storyboard-landbank/v3/review-queue
- GET /api/storyboard-landbank/v3/landbank
- GET /api/storyboard-landbank/v3/storyboards/{id}
- GET /api/storyboard-landbank/v3/storyboards/{id}/projections
- GET /api/storyboard-landbank/v3/capacity/{run_id}

Authoring/compile contracts:

- POST /api/storyboard-landbank/v3/recipes/preview
- POST /api/storyboard-landbank/v3/components/draft
- POST /api/storyboard-landbank/v3/storyboards/compile
- POST /api/storyboard-landbank/v3/assistant/create
- POST /api/storyboard-landbank/v3/assistant/expand
- POST /api/storyboard-landbank/v3/assistant/fill-capacity

Review contracts:

- PATCH /api/storyboard-landbank/v3/drafts/{id}
- POST /api/storyboard-landbank/v3/review/{id}/approve
- POST /api/storyboard-landbank/v3/review/{id}/reject
- POST /api/storyboard-landbank/v3/review/{id}/archive
- DELETE /api/storyboard-landbank/v3/drafts/{id}
- POST /api/storyboard-landbank/v3/review/bulk-validate
- POST /api/storyboard-landbank/v3/review/bulk-approve

Materialization/selection contracts:

- POST /api/storyboard-landbank/v3/projections/{id}/materialize-v2
- GET /api/storyboard-landbank/v3/materializations/{id}
- POST /api/storyboard-landbank/v3/production-selections
- POST /api/storyboard-landbank/v3/capacity/refresh

Every mutating contract requires:

- request ID/idempotency key;
- authenticated actor;
- product/truth/formula/recipe input digest;
- explicit scope and revision;
- validation receipt;
- no provider call on read or capacity endpoints;
- no automatic approval or activation;
- no media-provider submission or credit spend.

The V3 materializer must call the existing V2 service contract rather than
write directly into V2 tables. The V2 API remains the current production
authority and is not replaced by a V3 route.

## UI/UX TARGET

The Copy Register becomes the operator home for supply planning without
collapsing the current V2 review controls.

### 1. Setup campaign

Show:

- product and current Product Truth readiness;
- objective;
- angle selection or reviewed angle creation;
- storyline family selection;
- explicit formula/version;
- target languages and durations;
- recipe: QUICK TEST, FAST54, MULTI-ANGLE, SCALE or CUSTOM;
- target master/projection quantities;
- novelty/reuse policy;
- scene/treatment constraints.

Block the next step when truth, formula, objective or scope is incomplete.

### 2. Build Storyboard Landbank

Show:

- theoretical versus valid versus approved capacity;
- missing formula stages and component classes;
- angle/storyline coverage;
- evidence coverage;
- candidate run status and deterministic run digest;
- CREATE, EXPAND and FILL_CAPACITY actions;
- a full storyboard preview, not only Hook/Body/CTA text;
- 8/16/24 projection tabs derived from the same master;
- separate copy and scene validation panels.

### 3. Review Queue

Provide:

- filters by product, formula, angle, storyline, duration, status and blocker;
- candidate cards with ordered stage graph;
- evidence fact display beside every claim-bearing clause;
- bridge and continuity diagnostics;
- WPS budget and CTA final-block receipt;
- exact/near duplicate and coverage warnings;
- edit draft, regenerate stage, approve, reject, archive and safe delete;
- bulk validation and exception-first review;
- explicit reviewer identity and rationale.

### 4. Storyboard Landbank

Provide:

- approved master and projection inventory;
- current/stale/blocked status against Product Truth;
- usage/fatigue and novelty distribution;
- materialization state into V2;
- “Select for Production” action that opens V2 materialization/review;
- no direct Generate action.

### AI Assistant surface

The assistant is a panel in the same workflow, not a separate prompt box. It
must explain which capacity deficit it is addressing, which facts it used,
which formula stages it filled, and why the result remains DRAFT or
REVIEW_REQUIRED.

### Current UI relationship

CopySetRegistryPage and CopywritingSourceSelector remain useful V2
last-mile surfaces. CopyIntelligencePage remains a review-only workbook
intelligence tool. CreativeProductionStudioPage remains downstream production
control. V3 should compose these responsibilities rather than make Production
Studio a second copy register.

## SCALE / PERFORMANCE

The target is hundreds, thousands and eventually 10,000+ outputs per product
without 10,000 provider authoring calls or 10,000 V2 blueprints.

Rules:

- Persist components and approved Master Storyboards, not every theoretical
  Cartesian combination.
- Generate candidate batches deterministically with cursors and stable seeds.
- Store only candidates that pass minimum machine gates or are explicitly
  needed for review; keep rejected/excluded receipts compact.
- Materialize V2 lazily for selected projections.
- Reuse one V2 blueprint across compatible visual outputs; output-level
  uniqueness remains downstream.
- Cache Product Truth/evidence/formula snapshots by digest.
- Cache compatibility and capacity by recipe/input digest.
- Use exact fingerprint indexes for fast exclusion.
- Partition queries by product, campaign, recipe, formula, angle, storyline and
  duration.
- Paginate landbank and review views; never load a whole product's 10,000
  candidate set into the browser.
- Use a bounded candidate window and marginal-capacity ranking for FILL_CAPACITY.
- Keep provider authoring asynchronous and explicit in a future implementation;
  reads, validation and capacity must be zero-provider.
- Reuse the existing deterministic LRU and round-robin concepts only where the
  V3 usage contract makes them meaningful.

The P6 service currently caps materialized enumeration at 250,000 combinations.
V3 should avoid reaching that limit by selecting bounded approved projections
before P6 and by exposing capacity shortfalls before matrix materialization.

Performance metrics:

- candidate compile latency by stage count;
- validation latency by gate;
- capacity query latency;
- review queue page latency;
- materialization rate and V2 draft reuse;
- provider calls per approved master;
- duplicate rejection rate;
- stale-truth invalidation rate;
- reviewer minutes per approved storyboard;
- P6 matrix size and exact-DNA exclusion rate.

## MIGRATION STRATEGY

### Phase 0 — owner review and contract freeze

Approve the decisions in this document. Freeze the FormulaDefinition shape,
Angle/Storyline identity rule, projection approval rule, usage policy and V2
materialization boundary.

Exit gate: architecture approval recorded; no runtime changes.

### Phase 1 — read-only forensic adapters

Build no-write read models over Product Truth, evidence, formula registry, V2
blueprints/bindings, current component pool, scene/choreography catalog and P6
capacity. Report where existing rows cannot satisfy stage-native lineage.

Exit gate: reproducible forensic report and zero provider/media calls.

### Phase 2 — logical V3 schema and validators

Implement additive same-database tables/records only after the schema decision.
Add pure formula-stage, bridge, evidence, continuity, novelty and projection
validators. Do not connect to production generation.

Exit gate: unit/property/golden tests and migration rollback proof.

### Phase 3 — governed supply ingestion

Ingest new components, angles and storyline families from approved Product
Truth. Legacy CopySet rows remain historical; any import enters DRAFT and must
pass revalidation.

Exit gate: no ungrounded or auto-approved supply; coverage and capacity read
models agree.

### Phase 4 — Master Storyboard and projection compiler

Compile FAST54 and other recipes into full Masters, then derive duration
projections through the canonical WPS/compiler authority. Add scene references
without copying choreography authority.

Exit gate: formula, continuity, evidence, WPS, CTA and novelty fixtures pass.

### Phase 5 — Review Queue and Storyboard Landbank

Add the Copy Register V3 workflow, review events, bulk exception handling and
approved landbank views. Keep V2 activation unchanged.

Exit gate: human review and immutable approved artifact proof.

### Phase 6 — explicit V2 materialization

Materialize selected approved projections into V2 DRAFTs, preserve structured
V3 lineage, and run the existing V2 approval/binding path. Do not materialize
all candidate rows.

Exit gate: one-to-one lineage proof, stale-truth rejection, no legacy fallback,
and zero provider/media credit spend in local rehearsals.

### Phase 7 — P6 shadow integration and pilot

Feed only selected V2-backed projections to P6 in a zero-credit rehearsal.
Compare V3 capacity with P6 preflight, treatment availability, exact DNA and
lane-window results.

Exit gate: reconciliation report; no live Google Flow UAT or credit spend until
the repository's current UAT contracts authorize it.

### Phase 8 — controlled adoption

Enable selected recipes/products, retain V2 as the production authority, and
retire only explicitly approved legacy authoring paths after receipt-preserving
migration. Never delete the historical evidence surface merely because V3 is
available.

## BACKWARD COMPATIBILITY

Compatibility laws:

- ADR-007 API-first generation remains unchanged.
- ADR-010 V2 formula/evidence/approval/immutability/lineage/compiler laws
  remain unchanged.
- ADR-011 V2-only active production resolution remains unchanged.
- Existing V2 APIs and tables remain readable and authoritative.
- Existing V2 consumers receive the same V2 binding and approved execution
  text; V3 is upstream.
- P6 may retain historical H/B/C-shaped compatibility fields, but V3 must
  supply them only through a validated V2 projection.
- Existing CopySet and copy_component rows remain historical/maintenance data
  unless an explicit, receipt-preserving migration revalidates them.
- No V3 path may fall back from an absent V2 materialization to a legacy CopySet.
- COPY_NOT_REQUIRED image lanes remain explicitly copy-free.
- Existing Scene Choreography/Treatment hashes and lifecycle rules remain
  authoritative.
- The FAST54 workbook remains reference documentation/input, not a live
  database or formula authority.

The safe interoperability boundary is:

V3 approved projection → V2 draft/approval/binding → existing compiler/P6.

Any design that instead sends V3 text directly into the canonical prompt
compiler, Production Studio, or provider lane is rejected.

## TEST STRATEGY

Future implementation must prove the following without live provider or media
calls:

### Formula contract

- every canonical formula has a stable version and ordered stages;
- unknown/version-mismatched formulas fail closed;
- required/optional stage rules are enforced;
- derived H/B/CTA projections cannot reconstruct or replace stages;
- review-only formulas cannot bind to production.

### Component and compatibility

- component stage bindings are contiguous and formula-valid;
- product/angle/objective/storyline compatibility is deterministic;
- cross-lineage combinations fail closed;
- bridges and claim-bearing evidence rules are enforced;
- approved component immutability and revision behavior are proven.

### Master Storyboard

- all 54 FAST54 candidates are evaluated as full stage graphs;
- invalid combinations reduce valid capacity and produce reason codes;
- narrative continuity and CTA closure are tested with adversarial text;
- exact and near duplicates are distinguished from coverage diversity;
- angle and storyline breadth/concentration are reported.

### Duration/WPS

- 8, 16 and 24 projections derive from one master;
- 16 uses the canonical two-block plan and 24 the canonical three-block plan
  where the authority says so;
- unsupported duration/language/WPS fails closed;
- per-block word budgets and seam margins pass;
- CTA remains in the final block;
- projection text concatenates to the master-derived dialogue without loss or
  reordering.

### Scene and P6

- scene projections reference current choreography IDs/SHAs;
- stale hashes, placeholders, fallback strategies and incompatible presence
  fail closed;
- Creative Treatment remains separate and immutable;
- P6 accepts only approved V2-backed selected projections;
- exact DNA, historical exclusions, treatment hashes and lane capacity are
  preserved;
- no live start or credit spend occurs in tests.

### Review and storage

- approved artifacts cannot be edited or deleted;
- revisions preserve parents and supersession;
- bulk approval is explicit and auditable;
- stale Product Truth blocks use without mutating history;
- materialization is idempotent and records V3 → V2 lineage;
- no parallel database or untracked table is introduced.

### Scale

- property tests cover deterministic candidate ordering;
- capacity queries remain bounded at 10,000-output targets;
- review UI paginates and does not load all candidate text;
- exact fingerprint indexes prevent repeated batches;
- provider call count is measured and separated from media credit spend.

## RISKS

| Risk | Consequence | Mitigation |
|---|---|---|
| V3 becomes a second production authority | Consumers disagree about approved copy | Keep V2 binding/compiler/P6 boundary mandatory; V3 is supply only. |
| Existing copy_component is silently repurposed | BODY and formula stages are lost | Version stage semantics or use new additive V3 records in the same DB. |
| H/B/CTA display fields become source of truth | Multi-stage formulas flatten or drift | Store and validate ordered FormulaStagePlan; projections are derived only. |
| FAST54 is treated as guaranteed capacity | Blocked/unverified candidates are counted as ready | Report theoretical, valid, approved, executable and production capacity separately. |
| Cross-storyline mixing | Coherent components create incoherent stories | Storyline Family identity and bridge graph hard gates. |
| Product Truth changes after approval | Claims become stale | Snapshot/digest lineage and revalidation at every boundary. |
| WPS values drift | Dialogue overruns or CTA disappears | Use the retained WPS/block authority and canonical compiler only. |
| Scene copy is confused with choreography | Visual action contradicts product/scene law | SceneProjection references current Scene Choreography/Treatment; no duplicate authority. |
| AI assistant auto-approves or routes to production | Governance and credit risk | DRAFT/REVIEW_REQUIRED only, human V2 approval remains required. |
| V2 activation is global while V3 is campaign-scoped | One campaign changes another's active V2 pointer | Keep current V2 scope until owner approves a scoped activation model. |
| Reuse cap is inherited silently | Capacity and fatigue are misreported | Make V3 usage policy explicit in recipe and owner decisions. |
| Candidate storage explodes | Slow review and database growth | Lazy projections/materialization, bounded candidate runs, indexed digests. |
| Near-duplicate detector overblocks | Valid variety is lost | Keep exact duplicate hard; near duplicate a configurable review signal unless policy says otherwise. |
| Legacy import appears approved | Historical unsafe copy enters supply | Import as DRAFT, rebind to current truth, require review. |
| P6 matrix remains Cartesian | V3 improvements are lost downstream | Select bounded V2-backed projections before P6 materialization. |
| Workbook is mistaken for truth | Unverified sample claims reach production | Workbook remains reference only; Product Truth gate is authoritative. |

## OWNER DECISIONS

Only the following decisions remain because they change product behavior or
governance:

1. V3 physical storage shape: extend the current atomic component table with
   explicit versioned stage semantics, or add new V3 tables in the same
   canonical database. Recommendation: new versioned V3 records, preserving
   the current legacy vocabulary and rows.
2. Angle identity granularity: promise/pain only, or promise/pain × audience.
   Recommendation: make audience/objective part of compatibility while keeping
   the strategic Angle identity stable enough to support breadth reporting.
3. Storyline Family authority: Product Intelligence-derived, operator-authored,
   or both with a registration workflow. Recommendation: both, but every
   family needs an immutable reviewed definition and compatibility contract.
4. Canonical family taxonomy: which family labels and transitions are initially
   allowed. The repository currently supplies no final V3 taxonomy.
5. Formula promotion: whether any current operator-review formula may become
   production canonical, and what proof is required. Recommendation: none
   until the registry and compiler contract are explicitly promoted.
6. Projection approval: whether Master approval plus mechanical projection
   validation is sufficient, or whether each selected 8/16/24 projection
   needs independent human approval. Recommendation: require an explicit
   projection confirmation before V2 materialization because duration changes
   resolved text and WPS allocation.
7. Cross-storyline policy: whether any cross-family composition is permitted.
   Recommendation: blocked by default; require explicit compatibility proof.
8. V3 reuse/fatigue policy: whether a new cap, per-recipe cap, or no exact
   reuse is allowed. Recommendation: do not inherit the legacy 15 cap without
   a V3 owner decision.
9. Activation scope: retain current product-global all-required-lane V2
   activation, or introduce campaign/lane-scoped authority. Recommendation:
   retain current V2 scope during initial V3 adoption.
10. Bulk approval policy: one human confirmation for a fully validated batch,
    or human confirmation per exception group/projection. Recommendation:
    batch approval may cover machine-clean rows only; exceptions require
    explicit review.
11. Scene coupling: whether a recipe selects a fixed scene/treatment family or
    lets Production Studio choose among approved compatible variants.
12. Future text-assist budget and provider policy: whether V3 authoring may use
    the existing text-assist lane, with what token budget, receipts and
    operator confirmation. This is separate from Google Flow media credits.

Resolved by current repository authority and therefore not owner decisions here:

- V2 remains the active production copy authority.
- Legacy fallback is forbidden in normal runtime.
- Approved V2 text and bindings are immutable.
- Product Truth/evidence snapshots own factual claims.
- The formula registry owns formula IDs and versions.
- The canonical prompt compiler owns final engine-facing rendering.
- The WPS/block-plan authority owns duration budgets.
- Production Studio/P6 and Scene Choreography remain downstream authorities.
- No live generation or credit-spending work is part of this architecture task.

## IMPLEMENTATION PHASE PLAN

The implementation sequence is intentionally gated:

| Phase | Deliverable | Non-negotiable exit gate |
|---|---|---|
| 0 | Owner decisions and contract amendment | No unresolved authority conflict. |
| 1 | Read-only forensic adapters and supply gap report | Existing V2/P6 behavior unchanged; zero provider/media calls. |
| 2 | Same-DB V3 logical schema, digests, statuses and pure validators | Formula, truth, evidence, bridge, continuity and immutability tests pass. |
| 3 | Angle/Storyline/Component Landbank | No ungrounded or auto-approved component; current truth lineage present. |
| 4 | Master Storyboard compiler and FAST54 recipe | 54 attempts are full formula candidates; valid capacity is fail-closed. |
| 5 | WPS-driven 8/16/24 projections and scene references | One-master derivation, CTA-final, WPS and choreography receipts pass. |
| 6 | Review Queue and Storyboard Landbank UI/workflows | Human approvals, revisions, archive and bulk exception proof. |
| 7 | Lazy V2 materializer | V3 → V2 lineage, V2 approval, binding and stale-truth gates pass. |
| 8 | P6 shadow adapter and zero-credit rehearsal | P6 accepts only selected V2-backed projections; no live dispatch. |
| 9 | Controlled pilot and adoption | Owner-approved scope, production proof and rollback/receipt plan. |

No phase may skip the current repository contracts to reach a visual demo.
Generation, live UAT and media credit spend remain separate authorization
events after the architecture and local gates are complete.

STATUS:
ARCHITECTURE_REVIEW_READY
