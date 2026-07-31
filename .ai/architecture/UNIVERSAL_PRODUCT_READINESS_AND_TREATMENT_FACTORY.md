# BOSMAX Universal Product Readiness and Treatment Factory

<!-- markdownlint-disable MD013 -->

**Status:** ARCHITECTURE AUTHORITY ON MERGE

**Version:** 1.0.0

**Mission:** `BOSMAX-UNIVERSAL-PRODUCT-TO-TREATMENT-FACTORY-20260731`

**Audit base SHA:** `a61dcacbb68be53f56ee8b28a610dea9fca2734a`

## 1. Authority and bounded scope

This contract defines the universal evidence-applicability, layered-readiness,
and product-to-treatment preparation authority upstream of P7.5 and P6. It is
subordinate to:

1. `AGENTS.md`;
2. `.ai/status/CURRENT_STATE.md`;
3. `.ai/contracts/*`;
4. ADR-007 and ADR-008;
5. `.ai/ENGINEERING_LOCKDOWN.md`;
6. `.ai/architecture/BATCH_CREATIVE_PRODUCTION_ORCHESTRATOR_ARCHITECTURE_LOCK.md`;
7. `.ai/architecture/CREATIVE_TREATMENT_AND_CHOREOGRAPHY_MAPPING.md`;
8. `docs/PRODUCT_TRUTH_RECONCILIATION_CONTRACT.md`.

The logical subdomain remains physically owned by the `workspace` Mandor
domain. This phase changes documentation and bounded ownership only. It does
not add runtime code, schema, API routes, provider calls, canonical data
mutation, or approvals.

The contract governs video-treatment preparation. It does not redesign the
ADR-007 provider lane, artifact retrieval, Copy Set authority, Avatar Registry,
Scene Strategy, Creative Selection, Creative Asset approval, Creative
Treatment approval, or P6 execution.

## 2. Verified current-state evidence

The audit used an online SQLite backup of the canonical database. The canonical
database and active runtime were not mutated or restarted.

| Evidence                       | Verified value                                                     |
| ------------------------------ | ------------------------------------------------------------------ |
| Audit base                     | `a61dcacbb68be53f56ee8b28a610dea9fca2734a`                         |
| Database backup SHA-256        | `2ca9767d516758daa3ee444858d451485ce137c98ffc57a2f6ada2a64f5b3946` |
| Database size                  | `124305408` bytes                                                  |
| Integrity / quick check        | `ok` / `ok`                                                        |
| Foreign-key violations         | `0`                                                                |
| Products                       | `659`                                                              |
| Active / archived              | `443` / `216`                                                      |
| P5.8 P6-ready                  | `438`                                                              |
| P5.7 matrix SHA-256            | `334f43ed6d39b40f160e7b2e4927725acb971c20f6091b64e96af514dc3d4dd5` |
| P5.8 matrix SHA-256            | `02d66b9ef87f76aedc2d5718728b0a1856d4e6b75e8992308a140d9451faee32` |
| Universal audit matrix SHA-256 | `fb6b7b0f328c1b9a501ca95c880034dd6ffdea2320ecf9190950a5f4ab9cd5ef` |
| Taxonomy-profile SHA-256       | `f8dd1f53d73ae85f94424cfc5ecab15c1c6c10181f64d6d3b989ecc853bc564d` |
| Provider / Google Flow calls   | `0` / `0`                                                          |
| Credit spend                   | `0`                                                                |

The exact audit matrix contains all 659 products. Its current-state
classification is diagnostic evidence, not the readiness contract defined
below.

### 2.1 Taxonomy and action coverage

- 128 product-type registry profiles exist.
- 122 profiles have a specific Scene Strategy, at least one indexed action,
  and P4 copy-strategy support.
- Six profiles remain `GENERIC_FALLBACK`, `FALLBACK_ONLY`, and
  `REVIEW_REQUIRED`: `beauty_personal_care_other`, `cleanser`, `serum`,
  `unknown_product_type`, `home_appliance`, and `vacuum`.
- One active product currently consumes generic fallback.
- No P6-ready product consumes generic fallback.
- Five active products are outside P5.8 P6-ready authority: three have
  insufficient Product Truth and two are review-blocked by exact reasons.

The refresh includes merged PR #561. Latest source now contains specific
`CLEANSER`, `SERUM`, and `VACUUM` Scene Strategy and P4 authority. Against the
preserved database backup, the official P5.8 dry run proposed three registry
updates and nine taxonomy updates but performed no mutation; the before/after
state fingerprints remained identical. The six stored fallback profiles above
therefore remain exact database evidence, not a claim that latest source lacks
all six strategies.

Implementation must evaluate the latest stored registry plus latest source
authority. It must not hard-code this six-profile snapshot. Static source or
registry presence alone does not prove universal production readiness.

### 2.2 Product Truth and evidence

`product_intelligence_review_draft_service.REQUIRED_FIELDS` applies one
14-field completeness tuple to every product. Its approval path separately
recognizes an eight-field `COPY_GROUNDING_REQUIRED_FIELDS` subset.

- 422 active products have a latest approved Product Truth snapshot.
- 104 active products satisfy the generic 14-field completeness test.
- 422 active products satisfy the existing copy-grounding subset.
- Across active products, generic missing-field counts include:
  `ingredients_text=333`, `allowed_claims_json=329`, `warnings_text=323`,
  and `usage_text=322`.
- 308 active approved snapshots contain an empty allowed-claims array without
  a distinct durable semantic state proving that the empty set was intentional.
- Claim-safety floors remain independent: 420 active snapshots are
  `CLAIM_SAFE`, one is `CLAIM_REVIEW_REQUIRED`, one is `CLAIM_BLOCKED`, and
  21 active products have no approved snapshot.

The existing registration evidence audit contains one narrow,
textile-specific `ingredients=NOT_APPLICABLE` rule. It does not provide a
universal taxonomy + risk + action + format + mode applicability engine.

### 2.3 Copy, selection, assets, and treatments

- 2,429 Copy Sets exist; 2,069 are approved, but they cover only 12 active
  products.
- 1,036 Copy Components exist; 924 are approved, covering 13 active products.
- No `creative_product_selection` row exists.
- 97 Creative Assets exist; only three active products have a product-bound,
  active, approved, resolvable asset marked for video support.
- No Creative Treatment or Variation Group row exists.

The first observed blocker for the 443 active products is:

| Current observed gap               | Products |
| ---------------------------------- | -------: |
| `COPY_SUPPLY_REQUIRED`             |      406 |
| `PRODUCT_TRUTH_APPROVAL_REQUIRED`  |       19 |
| `CREATIVE_SELECTION_REQUIRED`      |       11 |
| `TAXONOMY_OR_P6_AUTHORITY_BLOCKED` |        5 |
| `CLAIM_REVIEW_REQUIRED`            |        1 |
| `CLAIM_BLOCKED`                    |        1 |

This proves that P7.5 and P6 fail closed correctly, but upstream preparation is
not universal.

## 3. Root cause and integration seams

The root cause is authority collapse: generic Product Truth completeness is
being used as a proxy for context-specific treatment readiness.

The bounded seams are:

1. `require_verified_product_strategy_taxonomy` for taxonomy authority;
2. indexed `SCENE_STRATEGIES.allowed_actions` for action authority;
3. latest approved Product Truth plus field provenance for evidence authority;
4. `resolve_copy_grounding` and Copy Set approval for copy authority;
5. Creative Selection handoff for avatar, scene, and camera authority;
6. Creative Asset validation for role, mode, approval, and resolvable-source
   authority;
7. P7.5 Creative Treatment creation, review, hashes, and Variation Groups;
8. P6 treatment preflight, compile, payload revalidation, and one-treatment-
   per-video materialization.

The implementation must compose these seams. It must not replace them.

## 4. Canonical terminology

### 4.1 Applicability profile

An **Applicability Profile** is an immutable, versioned policy projection for
one verified product taxonomy. It defines:

- risk flags;
- allowed indexed action classes;
- format and logical-mode compatibility;
- evidence applicability rules;
- required asset roles;
- copy-critical and treatment-critical requirements;
- unsupported contexts.

A profile is code authority, not product evidence. A missing, stale, fallback,
or unsupported profile yields `UNSUPPORTED_PRODUCT_TAXONOMY`.

### 4.2 Evidence requirement

An **Evidence Requirement** is a named product fact or governed decision needed
by a specific context. The minimum requirement families are:

- product identity;
- benefits and USPs;
- target customer;
- allowed claims;
- ingredients or composition;
- materials or components;
- usage or instructions;
- warnings or limitations;
- physical scale and state;
- visual asset identity.

Every requirement declares whether it is copy-critical,
treatment-critical, both, or optional.

### 4.3 Treatment Template and Treatment Instance

A **Treatment Template** is an immutable, deterministic policy projection:

```text
taxonomy + risk flags + indexed action + format + logical mode
→ evidence requirements + actor policy + asset roles + shot-grammar constraints
```

It contains no product fact, approval, asset, free-form claim, or provider
permission.

A **Treatment Instance** is the existing P7.5 Creative Treatment bound to one
product, approved Product Truth snapshot, approved Copy Set, approved Creative
Selection, assets, actions, and structured shots.

The factory records template ID/hash to treatment ID/hash lineage in its task
snapshot. The resolved P7.5 treatment remains the downstream production
authority; P6 never executes a template directly.

## 5. Mandatory evidence states

Every applicable requirement resolves to exactly one state:

| State                     | Meaning                                                                                                   |
| ------------------------- | --------------------------------------------------------------------------------------------------------- |
| `VERIFIED_VALUE`          | A value or explicit empty allowed-claims set is supported by reviewed provenance.                         |
| `NOT_APPLICABLE`          | The versioned applicability rule proves the requirement is structurally irrelevant to this exact context. |
| `NOT_STATED_IN_EVIDENCE`  | The requirement is relevant and reviewed source evidence does not state it.                               |
| `UNKNOWN_REVIEW_REQUIRED` | Evidence is absent, stale, contradictory, ambiguous, or not yet reviewed.                                 |

Rules:

- fake values such as `"N/A"`, `"none"`, or guessed content are forbidden;
- `NOT_APPLICABLE` is rule-derived and cannot be chosen merely to clear a
  blocker;
- `NOT_STATED_IN_EVIDENCE` never means safe, none, or not applicable;
- conflicting provenance resolves to `UNKNOWN_REVIEW_REQUIRED` with an exact
  conflict code;
- a stale source or projection cannot retain `VERIFIED_VALUE`;
- the projection carries source IDs, source hashes, rule version, and context
  hash.

### 5.1 Allowed-claims invariant

Allowed claims are always evaluated.

- A non-empty reviewed set may be `VERIFIED_VALUE`.
- An empty set is valid only when field provenance records an explicit,
  intentional human decision for that exact approved snapshot.
- An empty JSON array by itself is not proof of evaluation.
- `CLAIM_BLOCKED` remains blocking.
- `CLAIM_REVIEW_REQUIRED` remains satisfiable only by the existing explicit
  human acknowledgement path.
- Existing claim-risk floors may only raise restriction.

## 6. Applicability inputs and rules

The deterministic evaluator signature is:

```text
evaluate(
  product,
  verified taxonomy + fingerprint,
  claim risk + taxonomy risk flags,
  indexed Scene Strategy action,
  UGC | PGC | CINEMATIC,
  logical mode,
  generation mode
)
→ requirements
→ evidence states
→ readiness layers
→ blocker codes
→ next actions
→ projection version/hash
```

`generation_mode=EXTEND` remains unsupported under P7.5.

### 6.1 Minimum rule behavior

| Requirement             | Applicability law                                                                                                                                                                                                                  |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Product identity        | Always applicable.                                                                                                                                                                                                                 |
| Allowed claims          | Always applicable and explicitly reviewed.                                                                                                                                                                                         |
| Ingredients/composition | Applicable to composition-sensitive taxonomies and when an action or claim depends on composition, ingestion, preparation, or topical formulation.                                                                                 |
| Materials/components    | Applicable when a non-consumable product's action or claim depends on material, component, compatibility, durability, installation, or operation.                                                                                  |
| Usage/instructions      | Applicable when the selected action demonstrates, instructs, applies, installs, assembles, operates, consumes, or otherwise uses the product. A static product-hero action does not require usage solely because the field exists. |
| Warnings/limitations    | Applicable for high-risk, regulated, ingestible, topical, child, electrical, chemical, or mechanically hazardous contexts and whenever the selected action makes safe-use truth material.                                          |
| Physical scale/state    | Applicable when hands, presenter interaction, installation, use, comparison, or continuity depends on scale or state.                                                                                                              |

Consequences:

- electronics and apparel do not require ingredients;
- food, consumable, cosmetic, and wellness composition remains protected;
- usage is action-aware;
- warnings are risk- and action-aware;
- unknown never becomes not-applicable;
- field applicability never weakens claim safety.

## 7. Layered readiness authority

Every active catalog product resolves to exactly one primary status:

- `TREATMENT_READY`;
- `REVIEW_REQUIRED`;
- `EVIDENCE_REQUIRED`;
- `ASSET_REQUIRED`;
- `COPY_SUPPLY_REQUIRED`;
- `UNSUPPORTED_PRODUCT_TAXONOMY`.

Every result also carries all blockers and next actions. Primary status uses
this fail-closed precedence:

1. missing, fallback, or unsupported taxonomy/profile →
   `UNSUPPORTED_PRODUCT_TAXONOMY`;
2. relevant reviewed sources explicitly do not state treatment-critical
   evidence → `EVIDENCE_REQUIRED`;
3. unknown, contradictory, stale, claim-review, high-risk review, or pending
   human approval → `REVIEW_REQUIRED`;
4. evidence is ready but no approved or deterministically composable copy
   supply exists → `COPY_SUPPLY_REQUIRED`;
5. copy and selection are ready but required approved visual roles are absent
   → `ASSET_REQUIRED`;
6. one current approved treatment passes P7.5 and P6 revalidation →
   `TREATMENT_READY`;
7. otherwise the treatment candidate or approval remains
   `REVIEW_REQUIRED`.

Readiness layers are independently reported:

1. taxonomy;
2. Product Truth;
3. copy grounding;
4. claim safety;
5. action evidence;
6. Copy Set;
7. Creative Selection;
8. visual assets;
9. Treatment Template;
10. Treatment Instance;
11. P6.

No layer may infer approval from presence.

## 8. Determinism, hashes, and staleness

All new projections use the P7.5 canonical JSON and SHA-256 rules.

The readiness hash covers:

- projection version;
- product ID;
- taxonomy ID/fingerprint and profile version/hash;
- risk inputs;
- indexed action authority;
- format and modes;
- requirement applicability and evidence states;
- Product Truth snapshot ID/hash;
- reviewed provenance IDs/hashes;
- Copy Set, selection, asset, template, treatment, and Variation Group
  authority when present.

Operational timestamps, usage counters, and reviewer display notes are excluded
unless they change authority.

Any upstream approval, content, evidence, taxonomy, profile, or asset change
invalidates the prior projection. Revalidation occurs during scan, task resume,
treatment materialization, P6 preflight, compile, dry-run, and payload
construction.

## 9. Universal preparation factory

The factory scans one product or a cohort and creates one durable plan with
stable, per-product tasks for:

- Product Truth evidence/review;
- copy grounding;
- deterministic Copy Set composition where approved component supply exists;
- Copy Set review;
- Creative Selection;
- required asset supply;
- Treatment Template resolution;
- treatment candidate creation;
- treatment review;
- P6-ready capacity.

Task types use stable names:

- `PRODUCT_TRUTH_REVIEW`;
- `EVIDENCE_REVIEW`;
- `COPY_GROUNDING`;
- `COPY_COMPOSITION`;
- `COPY_REVIEW`;
- `CREATIVE_SELECTION`;
- `ASSET_SUPPLY`;
- `TREATMENT_CANDIDATE`;
- `TREATMENT_REVIEW`;
- `P6_CAPACITY`.

### 9.1 Lifecycle

Plan lifecycle:

```text
DRAFT → SCANNED → PREPARING → PAUSED
→ COMPLETED | COMPLETED_WITH_BLOCKERS | FAILED
```

Task lifecycle:

```text
PENDING → READY → RUNNING
→ REVIEW_REQUIRED | SATISFIED | PAUSED | FAILED | SUPERSEDED
```

### 9.2 Idempotency and failure isolation

- plan identity hashes cohort, authority versions, and requested context;
- task identity hashes plan, product, task type, and required authority;
- unchanged reruns create no duplicate run, task, Copy Set, or treatment;
- changed upstream authority supersedes stale tasks and creates a new
  projection;
- one blocked product never aborts the cohort;
- pause/resume is database-backed;
- every transition is auditable;
- provider and text-provider calls default to disabled;
- no media generation occurs.

The factory may reuse existing deterministic component composition and P7.5
creation services. It may create review-required drafts. It never approves
Product Truth, claims, Copy Sets, selections, assets, Variation Groups, or
treatments.

## 10. Human review boundaries

Human authority remains mandatory for:

- Product Truth and provenance review;
- explicit empty allowed-claims decisions;
- high-risk claim acknowledgement;
- Copy Set approval or explicit formula override;
- Creative Selection approval;
- asset approval and video-support eligibility;
- treatment and Variation Group approval.

The factory may identify and prepare work. It may not impersonate an approver.

## 11. Generic fallback and unsupported taxonomy

Generic fallback is forbidden for production readiness.

- A fallback taxonomy, scene, action, camera, actor, asset, Copy Set, template,
  or treatment cannot yield `TREATMENT_READY`.
- A registered taxonomy without a specific applicability profile is
  `UNSUPPORTED_PRODUCT_TAXONOMY`.
- Unsupported profiles return exact profile, taxonomy, and remediation codes.
- No product ID, including the two rempah products, defines universal behavior.

## 12. Operator control surface

The operator surface must reuse P6 Production Studio and existing remediation
surfaces. No new top-level dashboard page is authorized.

The Production Studio panel must support:

- all-product or selected-cohort scan;
- filters by taxonomy, readiness, and blocker;
- coverage, capacity, and next-action counts;
- visible distinction between `NOT_APPLICABLE`,
  `NOT_STATED_IN_EVIDENCE`, and `UNKNOWN_REVIEW_REQUIRED`;
- links to Product Truth, Copy Set, Creative Selection, and Asset remediation;
- pause/resume and partial-cohort failure;
- approved-treatment selection for P6;
- explicit zero-credit state.

Required UI states are loading, empty, ready, review-required,
evidence-required, unsupported, partial failure, success, stale, and
permission/approval blocked.

## 13. Migration, activation, and rollback

The applicability engine is a computed, read-only projection and requires no
schema migration.

The factory persistence migration must be:

- additive and idempotent;
- isolated from existing Product Truth, Copy Set, selection, asset, treatment,
  and P6 tables;
- free of legacy backfill and auto-approval;
- verified by clean, representative-upgrade, double-run, integrity, and
  foreign-key tests.

Canonical activation requires:

1. recoverable online backup;
2. SHA-256, row counts, integrity, quick check, and foreign-key proof;
3. official migration procedure;
4. full active/P6-ready scan;
5. second idempotent scan;
6. exact classification for every product;
7. no provider call, Google Flow call, or credit spend.

Rollback removes source consumption while leaving additive audit records inert.
Destructive down migration and database replacement are forbidden.

## 14. Legacy policy

- Existing approved snapshots, Copy Sets, selections, assets, treatments, P6
  plans, attempts, and artifacts remain historical authority.
- Existing records are not silently reclassified or backfilled.
- A nonterminal treatment or P6 item is revalidated at its next boundary.
- Stale or missing readiness lineage blocks; operators create a new
  factory-bound plan.
- Image, poster, manual workspace generation, provider execution, retrieval,
  and artifacts remain unchanged.

## 15. Zero-credit mass-production acceptance

### 15.1 Full catalog

- every active product has one primary readiness status;
- every non-ready product has exact blockers and routes;
- no unclassified row or production generic fallback exists;
- a blocked product does not abort the cohort;
- two identical scans are idempotent.

### 15.2 Representative archetypes

Where canonical evidence exists, the cohort covers consumable, cosmetic,
electronics, apparel, household, accessory, and wellness/high-risk products.
Evidence-blocked products are acceptable only when the requirement is
applicable and the missing owner evidence is exact.

### 15.3 Single-product 100-item proof

The disposable proof must produce:

- 100 planned video items;
- 100 compiled items;
- dry-run `100 ready / 0 blocked`;
- one approved treatment per item;
- deterministic capacity accounting;
- no Cartesian multiplication;
- same-dialogue reuse only through approved Variation Groups of two to five
  visually distinct members.

### 15.4 Mixed-product 100-item proof

The disposable proof must produce:

- multiple materially different archetypes;
- deterministic allocation totaling 100;
- 100 planned and 100 compiled items;
- dry-run `100 ready / 0 blocked`;
- per-product failure isolation;
- no cross-product Product Truth, Copy Set, selection, asset, treatment, or
  dialogue leakage.

Fail-closed proofs include unknown taxonomy, missing or not-stated critical
evidence, claim block, stale upstream authority, generic fallback, unsupported
EXTEND, missing treatment lineage, a sixth Variation Group member, and
accidental duplicate dialogue.

## 16. Sequential implementation boundaries

Every PR starts from latest verified `origin/main`, freezes only its ledger,
checks active PR paths, publishes an honest exact-head local-verification
status, uses the governed watcher/controller, and requires exact-head owner
confirmation before landing.

### 16.1 Contract PR

Exactly:

1. `.ai/architecture/UNIVERSAL_PRODUCT_READINESS_AND_TREATMENT_FACTORY.md`
2. `docs/MODULE_STATUS.yaml`

No runtime code, schema, API, provider call, or canonical mutation.

### 16.2 Applicability/readiness engine PR

Exactly:

1. `agent/models/product_readiness.py`
2. `agent/authority/product_readiness_applicability_registry.py`
3. `agent/services/product_readiness_applicability_service.py`
4. `agent/api/product_readiness.py`
5. `agent/main.py`
6. `tests/unit/test_product_readiness_applicability_service.py`
7. `tests/api/test_product_readiness_api.py`

No schema migration, Product Truth mutation, P6 change, provider call, or
approval.

### 16.3 Universal factory backend PR

Exactly:

1. `agent/models/product_treatment_factory.py`
2. `agent/db/product_treatment_factory_crud.py`
3. `agent/services/product_treatment_template_service.py`
4. `agent/services/product_treatment_factory_service.py`
5. `agent/api/product_treatment_factory.py`
6. `agent/db/schema.py`
7. `agent/main.py`
8. `scripts/universal-product-treatment-factory-rehearsal.py`
9. `tests/unit/test_product_treatment_factory_migration.py`
10. `tests/unit/test_product_treatment_template_service.py`
11. `tests/unit/test_product_treatment_factory_service.py`
12. `tests/unit/test_universal_product_treatment_factory_rehearsal.py`
13. `tests/api/test_product_treatment_factory_api.py`

No dashboard, P6 compiler/scheduler, provider, or approval-authority changes.

### 16.4 Operator surface PR

Exactly:

1. `dashboard/src/api/productTreatmentFactory.ts`
2. `dashboard/src/components/production-studio/ProductTreatmentFactoryPanel.tsx`
3. `dashboard/src/components/production-studio/ProductTreatmentFactoryPanel.test.tsx`
4. `dashboard/src/pages/CreativeProductionStudioPage.tsx`
5. `dashboard/src/pages/CreativeProductionStudioPage.test.tsx`
6. `tests/ui/test_creative_production_ui_contract.py`

No new top-level page and no backend behavior change.

### 16.5 Canonical activation and evidence PR

Exactly:

1. `docs/evidence/universal-product-treatment-factory-activation.md`
2. `docs/evidence/universal-product-treatment-factory-catalog.json`
3. `docs/evidence/universal-product-treatment-factory-scale-proof.json`

This PR records accepted output; it does not introduce runtime behavior.

### 16.6 PR #558

Only after universal readiness and zero-credit activation are accepted:

- rebase or base-update PR #558 without discarding history;
- preserve its existing two-file ledger;
- replace rempah-only current framing with resolved universal evidence;
- keep historical blocker evidence marked as resolved;
- govern and land its exact current head separately.

If implementation proves any frozen ledger insufficient, stop that PR and
amend this contract through a separate architecture decision. Do not silently
expand scope.

## 17. Collision classification

At contract freeze:

- PR #558 shares `docs/MODULE_STATUS.yaml` only to add its P7.5-D evidence path.
- PR #230 shares `docs/MODULE_STATUS.yaml` only to add poster-design authority
  paths.
- Both patches are additive and touch independent ownership entries.

Classification:

```text
COEXISTENCE_REQUIRED — NOT BLOCKED
```

Neither branch may be modified, closed, merged, or discarded by this mission.
Later base updates must preserve all ownership additions.

## 18. Definition of internal completion

The internal mission is complete only when:

- this contract and all four implementation/evidence PRs are merged
  sequentially;
- every merge SHA is reachable from remote main;
- canonical migration and full-catalog scan pass;
- representative zero-credit activation passes as far as verified evidence
  permits;
- both 100-item proofs pass;
- PR #558 is current, accepted, merged, and remotely verified;
- canonical runtime loads the accepted artifact;
- provider calls, Google Flow calls, and credit spend remain zero;
- the bounded live-UAT pack is ready.

`MASS_PRODUCTION_CONTENT_FACTORY_READY` may be claimed only after those
zero-credit gates pass.

`LIVE_THROUGHPUT_CERTIFIED` requires separate provider measurement and credit
authorization and cannot be inferred from this contract or a bounded visual
UAT.
