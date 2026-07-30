# P7.5-D Canonical Activation and Live UAT Evidence

## Status

`BLOCKED_BEFORE_TREATMENT_CREATION`

P7.5-D completed the canonical migration and the bounded two-product readiness
audit. Neither authorized `SPICE_SEASONING` candidate passes the complete
upstream-authority gate, so no treatment, Variation Group, P6 plan, provider
job, or live UAT record was created.

## Authority and baseline

- Current remote main/worktree SHA:
  `8fa4c48abff1f2477d16cec97309379f6dea4199`.
- Initial D1 execution base:
  `bc3616cb105973f4a61532ba70bd2d32d653a700`.
- Required P7.5-A merge ancestor:
  `d5f4e59079fc45d137db3419d95726dbf8b35f7a`.
- Required P7.5-B merge ancestor:
  `e9b3649bfa76c25d9de648d2da3226226991cdaa`.
- Required P7.5-C merge ancestor:
  `bc3616cb105973f4a61532ba70bd2d32d653a700`.
- Isolated branch: `docs/p7-5d-canonical-activation-uat`.
- Canonical database binding: `$FLOW_AGENT_DIR/flow_agent.db`.
- Canonical runtime before activation:
  `d4eb4fd39d400d2f959a59279e46e81561f2b13b`, detached branch, 501 routes,
  `source_stale_since_start=false`.
- Latest-main source import proof: 507 routes, including all eight required
  Creative Treatment and Variation Group route shapes.

The canonical runtime was not restarted because the readiness gate failed
before any P7.5 API operation. This avoids an unnecessary runtime ownership
change while preserving the exact source/runtime distinction.

## VERIFIED

### Canonical migration and health

A consistent SQLite online backup was created outside Git with the
repository-proven `sqlite3.Connection.backup` procedure before migration.

- Pre-migration backup SHA-256:
  `e7d8e88fcf9966e2fbdae78dfdec3f4057e542f119ef334fa2e0a0653fe8f919`.
- Backup size: 124,088,320 bytes.
- Backup `PRAGMA integrity_check`: `ok`.
- Backup `PRAGMA quick_check`: `ok`.
- Backup products: 659.
- Migration pass 1: `PASS`.
- Migration pass 2: `PASS`.
- Post-migration online snapshot SHA-256:
  `b45bc6f931cfd1fe3ed761744c9d0b4e369f3aea4812685846039d20769f95a0`.
- Post-migration snapshot size: 124,112,896 bytes.
- Post-migration `PRAGMA integrity_check`: `ok`.
- Post-migration `PRAGMA quick_check`: `ok`.
- Post-migration foreign-key violations: 0.

Remote main advanced during the audit through PR #557. The isolated branch was
fast-forwarded without collision to
`8fa4c48abff1f2477d16cec97309379f6dea4199`, whose additional official
migration adds only `creative_production_plan.plan_snapshot_json`. The
latest-main migration also passed twice:

- Latest-main pass 1: `PASS`.
- Latest-main pass 2: `PASS`.
- Final online snapshot SHA-256:
  `2ca9767d516758daa3ee444858d451485ce137c98ffc57a2f6ada2a64f5b3946`.
- Final snapshot size: 124,305,408 bytes.
- Final `PRAGMA integrity_check`: `ok`.
- Final `PRAGMA quick_check`: `ok`.
- Final foreign-key violations: 0.
- `plan_snapshot_json` present: yes.

The second migration run created no duplicate authority. The database changed
from 61 to 64 application tables by adding exactly:

- `creative_variation_group`;
- `creative_treatment`;
- `creative_treatment_audit_event`.

All required P7.5 indexes and immutable-content/hash triggers exist exactly
once. All three new tables contain zero rows because D2 did not authorize a
candidate.

### Row-count preservation

Total application rows remained 24,577 across the immediate P7.5 migration
window. During the later remote-main reconciliation, the independently running
canonical runtime appended 13 normal `creative_production_audit_event` rows
(90 to 103); the latest-main schema diff contains no such insert. All protected
authority and production-object counts remained:

| Authority | Before | After | Delta |
|---|---:|---:|---:|
| Product | 659 | 659 | 0 |
| Product Truth snapshots | 447 | 447 | 0 |
| Copy Sets | 2,429 | 2,429 | 0 |
| Creative Product Selections | 0 | 0 | 0 |
| Creative Assets | 97 | 97 | 0 |
| Creative Scene Prompts | 168 | 168 | 0 |
| Creative Camera Presets | 17 | 17 | 0 |
| P6 plans | 13 | 13 | 0 |
| P6 items | 28 | 28 | 0 |
| P6 generation attempts | 23 | 23 | 0 |
| Production runs | 59 | 59 | 0 |
| Video production jobs | 61 | 61 | 0 |
| Generated artifacts | 3 | 3 | 0 |

### Candidate gates that passed

Both authorized candidates are active, exact verified
`SPICE_SEASONING` products with `fallback_used=0`, `specific_strategy=1`,
`scene_coverage_status=COVERED`, active `rempah_seasoning` registry binding,
P4 support, and `P6_READY` catalog authority.

| Product | Product ID | Product Truth snapshot | Product Truth SHA-256 |
|---|---|---|---|
| Rempah Nasi Khowmok | `0a26caf0-1bc6-43a9-a267-7d2a1dbaccab` | `21cb61b9-5512-40e9-b3a6-5ae0d35a4cee` | `def670ba12bed5da457030f2a3c11aeb228a7e0b7d0551f8b2fd49fb9fe2ceb6` |
| Rempah Ayam Madu | `3f0e0206-a21a-4db6-a323-170ce505703f` | `b857ce79-6ccf-4e72-9de9-e5f2bcba81df` | `35a230671976f4893680b8f20e6665cbea524d60a8ae2c81666782c356316c78` |

These hashes are the P7.5 `product-truth-v1` semantic projections from the
latest approved snapshots. Approval status alone is insufficient: both
snapshots remain incomplete as recorded below.

## FAILED

### D2 canonical product selection

No candidate passes every mandatory gate.

| Gate | Rempah Nasi Khowmok | Rempah Ayam Madu |
|---|---|---|
| Active lifecycle | PASS | PASS |
| Exact `SPICE_SEASONING` taxonomy | PASS | PASS |
| Latest approved Product Truth exists | PASS | PASS |
| Complete Product Truth | FAIL: `MISSING_REQUIRED_FIELDS`, completeness 0.7143 | FAIL: `MISSING_REQUIRED_FIELDS`, completeness 0.7143 |
| Approved rotation-eligible Copy Sets | FAIL: 0 | FAIL: 0 |
| Approved Creative Selection | FAIL: absent | FAIL: absent |
| Approved avatar/wardrobe binding | FAIL: no approved selection | FAIL: no approved selection |
| Approved scene/background/camera binding | FAIL: no approved selection | FAIL: no approved selection |
| Product-bound approved video Creative Assets | FAIL: 0 | FAIL: 0 |
| P6 eligibility | PASS: `P6_READY` | PASS: `P6_READY` |
| Generic fallback dependency | PASS: absent | PASS: absent |

The Nasi Khowmok product has one `copy_intelligence_seed` in
`NEEDS_REVIEW`; it is not an approved Copy Set and was not promoted. The Ayam
Madu product has no candidate seed in that ledger. No upstream record was
fabricated, promoted, or synthetically approved.

### Source-level compatibility contradiction

The approved P7.5 contract requires concurrent UGC and PGC treatments for one
product, but the current implementation has one product-level Creative
Selection:

1. `creative_product_selection.product_id` is the primary key.
2. `_resolve_authority` always resolves that one selection by `product_id`.
3. `_validate_format` requires a resolved avatar and wardrobe for UGC.
4. `_validate_format` rejects any resolved avatar for PGC.

Therefore no single current approved selection can make both UGC and PGC
simultaneously valid: an avatar value blocks PGC, while a null avatar blocks
UGC. This is a `HIGH` production blocker for the required 12-treatment matrix.

No source fix was created under the P7.5-D no-fix activation law. The minimum
proposed surgical review boundary is:

- `agent/services/creative_treatment_service.py`;
- `tests/unit/test_creative_treatment_service.py`.

Any change must preserve the architecture rule that PGC consumes no
avatar/wardrobe and must not weaken immutable selection hashing or stale
authority rejection.

## NOT VERIFIED

- Selected canonical Rempah product: none.
- Twelve approved canonical treatments: not created.
- Five-member Variation Group: not created.
- P6 capacity preflight 12/12: not run.
- P6 materialization 12/12: not run.
- P6 compile 12/12: not run.
- P6 dry-run 12/12: not run.
- Treatment-lineage propagation: not run.
- P7.5 fail-closed runtime matrix: not run.
- Exact eight-item pre-live pack: not prepared.
- Live provider submission: prohibited and not attempted.
- Artifact retrieval and visual review: not attempted.

## ZERO-CREDIT PROOF

- Provider calls: 0.
- Google Flow calls: 0.
- Media generation calls: 0.
- Credit spend: 0.
- Treatment/Variation Group rows created: 0.
- Production-run, video-job, generation-attempt, and generated-artifact row
  counts were unchanged across migration.

Only SQLite backup, additive schema initialization, read-only database
inspection, source import, and route enumeration were executed.

## LIVE PROOF

`NOT ATTEMPTED`

The mission does not authorize provider submission or credit spend. D2 failed
before the eight-item pre-live gate, so `LIVE_UAT_AUTHORIZATION_REQUIRED` was
not reached and no live authorization was requested or inferred.

## OWNER SIGN-OFF

`REQUIRED_FOR_UPSTREAM_AUTHORITY_AND_SOURCE_DECISION`

One consolidated owner decision is required before P7.5-D can resume:

1. complete and approve a latest Product Truth snapshot for one authorized
   candidate through the governed Product Truth workflow;
2. review and approve sufficient non-archived Copy Sets through the Copy Set
   workflow;
3. create and approve the product Creative Selection, including governed
   avatar, wardrobe, scene, background, and camera bindings;
4. register and approve the required video-support Creative Assets;
5. decide the minimum source correction for simultaneous UGC and PGC
   compatibility without weakening P7.5 authority.

The owner must use the existing approval surfaces and exact confirmation
phrases. This document is not an approval phrase and does not impersonate the
owner.

## Tests

- P7.5 migration/service/API/P6 integration/compiler/pilot suite:
  `29 passed`.
- Mandor:
  `PASS_MODULE_STATUS_DOMAIN_RESOLVED domain=workspace paths=2`.
- Biome write gate: exit code 0; its unrelated formatter output was removed
  from this isolated worktree as required by the no-formatter-noise law.
- Dependency graph: 240 modules and 613 dependencies cruised; zero violations.
- `git diff --check`: pass for the tracked ownership update; the new evidence
  document has no trailing whitespace.
- Markdownlint: not installed; not run.

## Files changed

- `docs/MODULE_STATUS.yaml`;
- `docs/evidence/p7-5d-canonical-activation-live-uat.md`.

## Risks

- The latest-main P7.5 API is source-proven but not currently served by the
  canonical runtime.
- The additive P7.5 tables are present and inert; destructive rollback is
  prohibited.
- Treating an incomplete approved Product Truth snapshot as complete would
  weaken the readiness gate and is forbidden.
- Creating treatment records before upstream approvals would manufacture
  authority and is forbidden.

## Next decision

`OWNER_AUTHORITY_AND_SOURCE_DECISION_REQUIRED`

Resume D2 only after the governed upstream records exist and the UGC/PGC
compatibility decision is merged. Re-evaluate both authorized products from
current canonical state; do not substitute Sambal Nyet.
