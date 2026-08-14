<!-- markdownlint-disable MD013 -->

# ADR-011: Copy Register V2-Only Canonical Cutover

- Status: Accepted
- Date: 2026-08-14
- Owner authorization: explicit operator direction in the Copy Register canonical-database cutover mission
- Supersedes: the default-off, selectable-legacy rollout policy in ADR-010 for active Copy Register and production consumers
- Preserves: ADR-010 formula, evidence, approval, immutability, lineage, compiler, and fail-closed invariants

## Context

Copy Architecture V2 persistence and lane adapters are present, but the active runtime can still resolve the feature flag as OFF. The Operator workspace, Production Studio/P6, and Poster Builder also retain selectable legacy `copy_set` or `poster_copy_set` paths. This creates two competing copy authorities: the formula-native Copy Register and the old flat-copy ledgers.

Deleting legacy rows before removing those readers would break active pages and historical foreign-key lineage. Keeping both authorities selectable would let old copy silently re-enter production. Neither outcome is acceptable.

## Decision

The formula-native Copy Register V2 is the only active copy authority.

1. New authoring writes only `copy_blueprint_v2`, `copy_evidence_fact_v2`, and `copy_execution_binding_v2`.
2. All copy-required production lanes resolve one persisted V2 binding and fail closed with `V2 BINDING REQUIRED` when it is absent or invalid.
3. The three copy-free image lanes remain explicitly `COPY_NOT_REQUIRED`, but still require Product Truth, provenance, readiness, and safety proof.
4. Active UI and API surfaces do not list, select, rotate, recommend, approve, mutate, or bind legacy copy rows.
5. Legacy public authoring and selection endpoints return HTTP 410 with `LEGACY_COPY_STORAGE_DISABLED`.
6. No V2 failure may fall through to legacy copy, HSO, landbank, or a default formula.
7. A newly approved V2 blueprint may be explicitly bound to required lanes; approval itself remains human-only and is never inferred.

The required consumer set is:

| Group | Lane | Copy policy | Canonical projection |
| --- | --- | --- | --- |
| Video Production | T2V | REQUIRED | `VideoCopyProjection` |
| Video Production | F2V | REQUIRED | `VideoCopyProjection` |
| Video Production | Hybrid | REQUIRED | `VideoCopyProjection` |
| Video Production | I2V | REQUIRED | `VideoCopyProjection` |
| Video Production | Faceless | REQUIRED | `VideoCopyProjection` |
| Video Production | Montage | REQUIRED | `VideoCopyProjection` |
| Video Production | Production Studio/P6 | REQUIRED | `VideoCopyProjection` |
| Image Production | Image Gen | NOT_REQUIRED | `ImageCopyProjection` |
| Image Production | IMG Fastlane | NOT_REQUIRED | `ImageCopyProjection` |
| Image Production | IMG Cockpit | NOT_REQUIRED | `ImageCopyProjection` |
| Image Production | Poster Builder | REQUIRED | `ImageCopyProjection` |

## Legacy-data disposition

Legacy copy text is not Product Truth and must not remain selectable. Historical lineage is still evidence and must not be destroyed without a receipt.

The production migration therefore runs only after a consistent database backup and a successful dry run. In one transaction it must:

1. record the source database SHA-256 and exact row/reference counts;
2. copy legacy `copy_set`, `copy_component`, and `poster_copy_set` rows into immutable, non-selectable receipt tables with canonical row JSON and digest;
3. preserve each historical reference as a receipt reference before detaching it from an active legacy foreign key;
4. empty the active legacy copy tables;
5. install database triggers that reject new legacy writes; and
6. emit a migration receipt containing before/after counts, table integrity, foreign-key-check results, backup identity, and migration version.

The migration must never delete or mutate products, approved Product Intelligence snapshots, Product Truth evidence, taxonomy, avatars, provider receipts, token/accounting records, generated artifacts, or V2 rows.

If any reference cannot be represented losslessly in the receipt ledger, the migration fails and rolls back before deleting a legacy row.

## Runtime activation and rollback

V2-only is the normal runtime state. A request cannot opt itself back into the legacy path. Legacy recovery is an explicit maintenance operation requiring:

- the previous immutable runtime release;
- the matching pre-cutover database backup;
- stopped generation queues; and
- an operator-recorded rollback decision.

Rollback is not an in-process fallback and is not exposed in production pages. Restoring only code or only data is forbidden because it would recreate runtime skew.

## Delivery sequence

This decision resolves the conflict with ADR-010 before implementation. Delivery remains split into reviewable boundaries:

1. this decision PR;
2. V2-only consumer, API, UI, database-migration tooling, and focused proof PR;
3. dry-run receipt on a consistent production database copy;
4. merge and immutable runtime release build;
5. queue-idle proof, database backup, transactional migration, and controlled canonical-runtime restart; and
6. post-merge API, all-11-lane, browser, database, and runtime-provenance proof.

No provider call, live media generation, credit spend, mass approval, or Product Truth mutation is authorized by this decision.

## Acceptance gates

The cutover is complete only when all of the following are proven:

- all eight copy-required lanes resolve only persisted V2 bindings;
- all three copy-free lanes prove their explicit non-copy gates;
- active Video Production and Image Production pages issue no legacy copy API request;
- active lane code performs no legacy copy-table read or write;
- legacy public APIs fail with `LEGACY_COPY_STORAGE_DISABLED`;
- the migration dry run and apply receipts are deterministic and restorable;
- active legacy tables contain zero rows and reject writes;
- receipt counts equal migrated source counts and historical references resolve;
- `PRAGMA foreign_key_check` and `PRAGMA integrity_check` pass;
- the exact repository verify gate and focused V2 tests pass;
- runtime, dashboard bundle, extension, database migration, and `origin/main` identities are reported without skew; and
- provider calls, credits spent, and production approvals performed by the migration are all zero.
