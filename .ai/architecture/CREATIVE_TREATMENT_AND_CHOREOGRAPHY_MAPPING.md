# BOSMAX Creative Treatment and Choreography Mapping

**Status:** APPROVED ARCHITECTURE AUTHORITY
**Version:** 1.0.0
**Authority phase:** P7.5-A
**Base SHA:** `71a07fe89810ede8544f975b3d9397ebb3c686cd`

## 1. Authority and scope

This contract defines the bounded Creative Treatment authority consumed by the
P6 Batch Creative Production Orchestrator. It is subordinate to:

1. `AGENTS.md`
2. `.ai/status/CURRENT_STATE.md`
3. `.ai/contracts/*`
4. ADR-007 and ADR-008
5. `.ai/ENGINEERING_LOCKDOWN.md`
6. `BATCH_CREATIVE_PRODUCTION_ORCHESTRATOR_ARCHITECTURE_LOCK.md`

The logical Creative Treatment subdomain remains physically owned by the
`workspace` Mandor domain because `scripts/mandor-check.ts` currently resolves
delivery exclusively to that domain. Ownership is nevertheless bounded to the
exact ledgers in section 16.

P7.5 governs P6 `VIDEO` production only. Existing `IMAGE`, `POSTER`, manual
workspace generation, ADR-007 provider execution, retrieval, and artifact
registration remain outside this authority.

## 2. Verified current-state evidence

The P7.5-A audit on the base SHA established:

- `CreativePoolSelection` contains raw copy, avatar, asset, scene, style,
  layout, model, and duration pools, but no approved treatment IDs.
- `creative_production_plan_service._product_dimension_rows` constructs visual
  pools with `itertools.product` and then expands copy x visual x scene x
  layout x model x duration.
- capacity preflight records
  `capacity_is_unique_cartesian_product: true`.
- P6 item Creative DNA contains no Product Truth snapshot ID/hash, treatment
  ID/hash, Variation Group, or dialogue fingerprint.
- `compile_plan` compiles durable prompt packages without provider calls, but
  it has no treatment-authority revalidation.
- `canonical_prompt_compiler.render_block` accepts an explicit `shot_plan`;
  this is the sanctioned extension seam under ADR-008.
- every non-image render currently begins Section 5 with handheld vertical
  micro-jitter language, including `CINEMATIC_PRO`.
- `PGC_CAMPAIGN` exists only as an inert creative-direction/poster composition
  concept. No video PGC treatment grammar exists.
- `_build_item_payload` is the final zero-credit payload construction boundary
  before payload hashing and matching dry-run enforcement.
- latest-approved Product Truth snapshots, Copy Set approval, Creative
  Selection approval, and avatar/scene/camera handoff validators already exist
  and must be referenced rather than rebuilt.

Therefore P7.5 adds one bounded approval authority and routes P6 video planning
through it. It does not create another prompt renderer or provider lane.

## 3. Canonical Creative Treatment

A **Creative Treatment** is an immutable, versioned, operator-approved
production contract for exactly one product, approved Product Truth snapshot,
approved Copy Set, approved Creative Selection, creative format, action
sequence, structured shot grammar, duration, and compatible visual bindings.

One approved treatment represents exactly one eligible P6 video candidate.
P6 must not independently recombine the treatment's copy, avatar, wardrobe,
scene, background, camera, action, or shot dimensions.

A treatment is not:

- a Copy Set;
- an Avatar Registry entry;
- a Scene Strategy entry;
- a provider prompt;
- a generated asset;
- a generic template fallback;
- permission to spend credits.

## 4. Required dependency bindings

Every treatment must persist the following IDs and deterministic dependency
hashes:

| Dependency | Required binding |
|---|---|
| Product | `product_id` |
| Product Truth | `product_truth_snapshot_id`, `product_truth_sha256` |
| Copy | `copy_set_id`, `copy_set_sha256` |
| Creative setup | `creative_selection_id`, `creative_selection_sha256` |
| Taxonomy/action authority | `scene_strategy_id`, `scene_strategy_sha256` |
| Avatar | `avatar_code`, `avatar_sha256` when the format requires a presenter |
| Wardrobe | normalized wardrobe value and `wardrobe_sha256` when an avatar is used |
| Scene/background | selected scene/template IDs and hashes |
| Camera | selected camera preset code and hash |
| Assets | ordered role/asset ID/hash bindings |

Dependency hashes use semantic projections. Mutable operational fields such as
usage counters, last-used timestamps, reviewer notes, and database update
timestamps are excluded. Approval status is always revalidated separately and
cannot be made valid merely by matching an old hash.

Product Truth authority is the latest approved
`product_intelligence_snapshot`, not the mutable product row.

The treatment's `content_angle` must equal the normalized angle of its bound
approved Copy Set. Dialogue is a deterministic projection of that Copy Set's
approved hook, subhook, USP set, and CTA; a treatment cannot introduce
unreviewed free-form sales copy.

## 5. Canonical serialization and hashes

All P7.5 hashes use SHA-256 over UTF-8 canonical JSON:

```text
json.dumps(
  canonical_payload,
  ensure_ascii=False,
  sort_keys=True,
  separators=(",", ":"),
)
```

Before serialization:

- strings are Unicode NFC;
- CRLF and CR become LF;
- leading and trailing whitespace is removed;
- object keys are sorted by the serializer;
- action and shot arrays preserve authored sequence;
- asset bindings are sorted by `(role, asset_id)`;
- integers, booleans, and null retain JSON scalar semantics;
- timestamps, generated IDs, and audit metadata are excluded unless a
  projection explicitly names them.

Projection versions are mandatory:

- `product-truth-v1`
- `copy-set-v1`
- `creative-selection-v1`
- `scene-strategy-v1`
- `creative-binding-v1`
- `creative-treatment-v1`
- `creative-variation-group-v1`

The treatment hash covers the projection version, every dependency ID/hash,
format, generation mode, duration, content angle, deterministic dialogue,
Action Sequence, Shot Grammar, compatibility profile, Variation Group ID and
member ordinal, visual fingerprint, and supersession lineage.

The **dialogue fingerprint** hashes only the normalized spoken dialogue or
voice-over. The **visual fingerprint** hashes format, actions, shots, avatar,
wardrobe, scene/background, camera, and asset bindings. Five members may share
one dialogue fingerprint only when their visual fingerprints are distinct.

## 6. Lifecycle and immutability

Treatment lifecycle:

```text
DRAFT
→ REVIEW_REQUIRED
→ APPROVED | REJECTED
→ SUPERSEDED
```

Variation Group lifecycle uses the same states.

Rules:

- creation always produces `DRAFT`;
- submission freezes the candidate hash and moves to `REVIEW_REQUIRED`;
- approval requires operator identity, exact expected hash, and the explicit
  confirmation phrase defined by the P7.5-B model;
- approval never occurs implicitly through creation, migration, API defaults,
  fixtures, or P6;
- approved semantic fields are immutable;
- changing approved content requires a new treatment ID/version with
  `supersedes_treatment_id`;
- approving the successor atomically marks the predecessor `SUPERSEDED`;
- rejected or superseded rows never regain approval;
- every transition emits a durable audit event.

## 7. Compatibility profile

Compatibility is evaluated at creation, review submission, approval, P6
preflight, compile, and final payload construction.

The profile binds:

- product and verified taxonomy;
- scene strategy;
- approved Copy Set product/angle;
- logical/source mode;
- `generation_mode`;
- engine-supported duration;
- creative format;
- required actor policy;
- avatar and wardrobe policy;
- scene/background and camera policy;
- required asset roles;
- allowed and forbidden product interactions;
- action-to-shot coverage;
- dialogue/voice-over policy.

Any unresolved dependency, missing required asset, generic fallback, mismatched
product ID, forbidden interaction, or unsupported format/mode/duration blocks
approval or production.

## 8. Structured Action Sequence

An Action Sequence is an ordered list. Each entry contains:

- `sequence`;
- `scene_strategy_id`;
- `allowed_action_index`;
- the resolved immutable `action_text`;
- `actor_role`: `PRESENTER`, `HANDS`, `PRODUCT`, or `NONE`;
- `product_state_before`;
- `product_state_after`;
- continuity requirements.

`allowed_action_index` must resolve inside the selected Scene Strategy. The
stored text must match that indexed authority when validated. Free-form actions
that do not map to the strategy are incompatible.

Every action must be used by at least one shot. Every shot must reference one
declared action.

## 9. Structured Shot Grammar

A Shot Grammar is an ordered list whose entries contain:

- `sequence`;
- `action_sequence`;
- `purpose`;
- `framing`;
- `camera_motion`;
- `subject`;
- `duration_seconds`;
- `continuity_in`;
- `continuity_out`.

Shot durations must be positive and sum to the treatment duration. Continuity
must preserve the declared product state and asset identity.

The canonical compiler remains the only final renderer. P7.5 passes validated
shots through the existing `render_block(shot_plan=...)` seam and adds only
the minimum format-aware Section 5 camera law required to avoid contradictory
directives.

## 10. Creative formats

### 10.1 UGC

- human-first, approved-presenter treatment;
- approved avatar and wardrobe are required;
- believable hook, product-use demonstration, result context, and CTA;
- natural handheld movement and controlled micro-imperfection are allowed;
- studio/cinematic motion cannot be silently substituted.

### 10.2 PGC

PGC means **product-generated/product-led content at the treatment level**. It
is not a rename of UGC and is not the poster-only `PGC_CAMPAIGN` enum.

- product/process-first;
- no visible presenter and no avatar/wardrobe consumption;
- hands may appear only when explicitly declared by an action;
- stabilized top-down, macro, side-process, or product-hero shots;
- dialogue, when present, is voice-over;
- handheld creator language, selfie framing, and presenter directions are
  prohibited.

PGC still compiles through ADR-008's canonical renderer; the treatment format
selects a distinct shot and camera grammar before final rendering.

### 10.3 CINEMATIC

- controlled commercial movement such as locked, dolly, slide, macro, or
  deliberate orbit;
- lighting, depth, and material continuity are explicit;
- avatar use is optional but, when present, must be approved and hashed;
- handheld micro-jitter and creator-selfie language are prohibited;
- product scale and state remain locked.

## 11. Variation Group authority

A Variation Group is the only authority for deliberate same-dialogue reuse.

Rules:

- one group binds one product, one approved Copy Set, and one dialogue
  fingerprint;
- member treatments declare the group ID and a unique ordinal `1..5`;
- two through five members are valid for group approval;
- a sixth member is rejected before persistence/approval;
- duplicate ordinals are rejected;
- member visual fingerprints must be distinct;
- undeclared dialogue duplication against another active approved treatment is
  rejected;
- a group hash covers the ordered `(ordinal, treatment_id, treatment_sha256,
  dialogue_sha256, visual_fingerprint_sha256)` members;
- P6 may schedule same-dialogue members only when both treatment and group are
  currently approved and both hashes match.

## 12. Generic fallback prohibition

Production treatments may not consume:

- an unknown/fallback product taxonomy;
- scene-strategy fallback output;
- direct-script fallback slots in place of the approved Copy Set;
- deterministic avatar fallback;
- generic scene, camera, action, or shot defaults;
- a synthesized treatment created by P6.

Preview utilities may retain their existing fallback behaviour outside P7.5.
No fallback output can be promoted into an approved treatment without explicit
review and immutable dependency bindings.

## 13. SINGLE and EXTEND policy

P7.5 v1 supports `generation_mode=SINGLE` only.

- the duration must be supported by the selected engine and represented by one
  canonical prompt block;
- `EXTEND`, multi-block choreography, or any requested-total duration is
  rejected with `TREATMENT_EXTEND_UNSUPPORTED`;
- `full_storyboard_extend_planner.py` is outside P7.5-C;
- no generic block splitting or silent conversion is allowed.

EXTEND treatment support requires a later architecture contract and separate
ledger.

## 14. P6 lineage and stale-authority policy

P6 video plans must receive explicit approved treatment IDs.

Lineage is preserved without new P6 columns:

- plan `pool_snapshot_json`: ordered treatment IDs, hashes, dependency hashes,
  and group hashes;
- item `creative_dimensions_json`: immutable treatment projection and visual
  fingerprint;
- item `creative_dna_sha256`: includes treatment and visual fingerprints;
- plan `compile_snapshot_json`: item-to-treatment compile evidence;
- item `prompt_package_json`: treatment lineage and compiled grammar;
- attempt `payload_snapshot_json`: the same lineage before payload hashing.

Preflight resolves treatments and reports safe capacity as the number of
eligible unique treatments. Materialization emits at most one video item per
treatment and assigns one compatible model/duration; it does not multiply
treatment dimensions.

Approval, dependency hashes, group authority, format compatibility, and
fallback absence are revalidated during preflight, compile, and
`_build_item_payload`. Because treatment lineage is part of the payload,
staleness changes the payload hash and invalidates prior dry-run evidence.

Stable production error codes:

- `TREATMENT_IDS_REQUIRED_FOR_VIDEO`
- `TREATMENT_NOT_FOUND`
- `TREATMENT_NOT_APPROVED`
- `TREATMENT_HASH_STALE`
- `TREATMENT_DEPENDENCY_STALE`
- `TREATMENT_INCOMPATIBLE`
- `TREATMENT_FORMAT_UNSUPPORTED`
- `TREATMENT_EXTEND_UNSUPPORTED`
- `TREATMENT_GENERIC_FALLBACK_FORBIDDEN`
- `TREATMENT_LINEAGE_REQUIRED`
- `VARIATION_GROUP_NOT_APPROVED`
- `VARIATION_GROUP_HASH_STALE`
- `VARIATION_GROUP_DIALOGUE_MISMATCH`

All these errors occur before provider dispatch.

## 15. Legacy-plan policy

- completed or terminal historical items remain historical evidence;
- no treatment IDs or approvals are backfilled;
- any nonterminal P6 video item without treatment lineage fails at its next
  preflight, compile, dry-run, or live-start boundary with
  `TREATMENT_LINEAGE_REQUIRED`;
- operators must create a new treatment-bound plan;
- image and poster planning remain byte-for-byte governed by their existing
  paths;
- manual non-P6 workspace generation remains unchanged.

## 16. Operator API decision

P7.5-B must expose a backend API because operator identity, expected-hash
review, approval, rejection, supersession, and audit readback require a durable
authority surface. No dashboard changes are authorized.

Required routes:

- `POST /api/creative-treatments`
- `GET /api/creative-treatments`
- `GET /api/creative-treatments/{treatment_id}`
- `POST /api/creative-treatments/{treatment_id}/submit-review`
- `POST /api/creative-treatments/{treatment_id}/review`
- `POST /api/creative-treatments/variation-groups`
- `GET /api/creative-treatments/variation-groups/{group_id}`
- `POST /api/creative-treatments/variation-groups/{group_id}/submit-review`
- `POST /api/creative-treatments/variation-groups/{group_id}/review`

Creation is never approval. Supersession is requested when creating the new
draft and becomes effective only when that successor is approved.

## 17. Frozen P7.5-B ledger

P7.5-B may change exactly:

1. `agent/models/creative_treatment.py` — NEW
2. `agent/db/creative_treatment_crud.py` — NEW
3. `agent/services/creative_treatment_service.py` — NEW
4. `agent/api/creative_treatments.py` — NEW
5. `agent/db/schema.py` — MODIFY
6. `agent/main.py` — MODIFY
7. `tests/unit/test_creative_treatment_migration.py` — NEW
8. `tests/unit/test_creative_treatment_service.py` — NEW
9. `tests/api/test_creative_treatments_api.py` — NEW

P7.5-B must not modify P6 planning, prompt compilation, scheduling, provider
execution, Copy Set, Avatar Registry, Creative Selection, or Scene Strategy
schemas.

## 18. Frozen P7.5-C ledger

P7.5-C may change exactly:

1. `agent/models/creative_production.py` — MODIFY
2. `agent/services/creative_production_plan_service.py` — MODIFY
3. `agent/services/creative_production_compile_service.py` — MODIFY
4. `agent/services/workspace_generation_package_service.py` — MODIFY
5. `agent/services/ugc_video_prompt_compiler_service.py` — MODIFY
6. `agent/services/canonical_prompt_compiler.py` — MODIFY
7. `agent/services/creative_production_scheduler_service.py` — MODIFY
8. `tests/unit/test_creative_production_treatment_integration.py` — NEW
9. `tests/unit/test_creative_treatment_prompt_compiler.py` — NEW
10. `tests/unit/test_creative_treatment_rempah_pilot.py` — NEW
11. `docs/evidence/p7-5-creative-treatment-rempah-pilot.md` — NEW

`full_storyboard_extend_planner.py`, P6 database schema/CRUD, dashboard,
provider, extension, and ADR-007 generation files are explicitly excluded.

## 19. Rempah pilot contract

The disposable pilot may evaluate only:

- `0a26caf0-1bc6-43a9-a267-7d2a1dbaccab` — Rempah Nasi Khowmok
- `3f0e0206-a21a-4db6-a323-170ce505703f` — Rempah Ayam Madu

Canonical-data eligibility requires exact verified `SPICE_SEASONING` taxonomy,
a complete approved Product Truth snapshot, approved Copy Set, approved
Creative Selection/assets, active lifecycle, and P6 eligibility.

The deterministic disposable-DB fixture must contain:

- four allowed SPICE_SEASONING action sequences;
- UGC, PGC, and CINEMATIC treatment grammar;
- twelve canonical treatment templates;
- one approved five-member same-dialogue Variation Group;
- five distinct visual fingerprints;
- no fallback;
- zero provider calls;
- zero credit spend.

If neither canonical product is currently eligible, fixture-level proof may
pass while canonical-data readiness is reported `NOT VERIFIED`. No title-based
substitute or fabricated approval is allowed.

## 20. Non-goals and rollback

Non-goals:

- live generation or credit spend;
- dashboard treatment management;
- EXTEND choreography;
- changes to Copy Set, Product Truth, Avatar, Creative Selection, Scene
  Strategy, or creative-asset schemas;
- provider, extension, retrieval, or artifact changes;
- legacy data backfill;
- generic treatment generation.

Rollback:

- P7.5-A is documentation/ownership only and can be reverted directly;
- P7.5-B source can be reverted while additive tables remain inert; destructive
  down migrations are forbidden;
- P7.5-C can be reverted without deleting treatment authority records;
- rollback never mutates historical approvals or provider artifacts.

## 21. Completion gates

P7.5 is complete only when:

- P7.5-A, P7.5-B, and P7.5-C are merged sequentially;
- remote main contains every merge SHA;
- migrations are additive and idempotent;
- treatment and Variation Group approvals are fail-closed;
- P6 video planning uses one approved treatment per candidate;
- UGC, PGC, and CINEMATIC produce distinct structured grammar;
- unsupported EXTEND fails closed;
- the disposable rempah pilot and deterministic-hash tests pass;
- existing image/poster behaviour is unchanged;
- provider calls and credit spend remain zero.
