# Universal Product-to-Treatment Factory canonical activation

Mission: `BOSMAX-UNIVERSAL-FACTORY-FINAL-CLOSURE-20260731`

## Authority boundary

- Source base at activation: `5b17d4ae3a7a227fa6101368369d8073a97cc1fb` plus the unmerged PR #568 implementation in the isolated `codex/universal-product-treatment-factory` worktree.
- Canonical database: `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`.
- Canonical runtime remained loaded from `5b17d4ae3a7a227fa6101368369d8073a97cc1fb` during the additive migration and scan; accepted-source runtime loading remains a post-merge gate.
- Provider calls, Google Flow calls, media-generation calls, and credit spend were prohibited and remained `0`.
- The configured live video lane was financially armed but untouched. Immediately before migration, processing requests, due/running schedules, production runs, P6 runs, live-authorized P6 plans, unreleased leases, and running Creative Supply runs were all `0`.

## Recoverable backup and pre-change proof

- Online backup: `C:\tmp\bosmax-universal-factory-final-closure\flow_agent-pre-activation-20260731.db`.
- Backup size: `124305408` bytes.
- Backup SHA-256: `44a1259e615004a25ca685f41fce5b5b6f98c8b2f9e675299888f9ad073c72bd`.
- Backup `integrity_check`: `ok`.
- Backup `quick_check`: `ok`.
- Backup foreign-key violations: `0`.
- Backup products: `659`; Creative Treatments: `0`; Variation Groups: `0`.

## Additive migration and idempotency

- `agent.db.schema.init_db()` pass 1: `PASSED`.
- `agent.db.schema.init_db()` pass 2: `PASSED`.
- Created exactly three bounded tables: `product_treatment_factory_plan`, `product_treatment_factory_task`, and `product_treatment_factory_event`.
- Post-migration `integrity_check`: `ok`.
- Post-migration `quick_check`: `ok`.
- Post-migration foreign-key violations: `0`.
- No existing Product Truth, Copy Set, Selection, Asset, Creative Treatment, Variation Group, or P6 schema was replaced.

## Canonical catalog activation

- Active products scanned: `443`.
- Plan: `ptfp_448b323aab68472f9d2987959f29a631`.
- Plan identity SHA-256: `34d49cc64e2e1ada912aea21f87b51ab866bb1773064561aa379e743e6b86cd7`.
- Cohort SHA-256: `ad0b5dbafd387bf94cbb3969bfc2edd696f0cf2e13428c546ac2df97b95a7823`.
- Context SHA-256: `da14917193e6c7f10ce57440baf28998197abad3f79a1509595cf6ec97993149`.
- Derived tasks: `4430`; audit events: `2`; factory plans: `1`.
- Primary readiness: `REVIEW_REQUIRED=438`, `UNSUPPORTED_PRODUCT_TAXONOMY=5`, all other states including `READY=0`.
- The single isolated scan error was product `60c65d01-5d27-465b-8b9b-20d3a8cd8b99` with exact code `UNSUPPORTED_PRODUCT_TAXONOMY`; the cohort completed and sibling products remained available.
- Rerun returned the identical plan ID, plan hash, cohort hash, context hash, product count, task count, and readiness summary. Plan/task/event counts remained `1/4430/2`.
- Exact product IDs by readiness and blocker counts are locked in `universal-product-treatment-factory-catalog.json`.

Three approved Creative Treatments created by a concurrent upstream authority were observed after the pre-change backup and preserved. They were authored as `codex-p75-p6-final-closure`; the factory migration/scan did not create or approve them. Canonical Variation Groups remained `0`, and P6-ready product count remained `0`.

## Post-activation snapshot and rollback

- Online snapshot: `C:\tmp\bosmax-universal-factory-final-closure\flow_agent-post-activation-20260731.db`.
- Snapshot SHA-256: `227ea840dc786dd3754bd940a69aa16b5d41ce7c0ddcb9207502f97ff5df87cf`.
- Snapshot `integrity_check`: `ok`; `quick_check`: `ok`; foreign-key violations: `0`.
- Snapshot factory rows: plans `1`, tasks `4430`, events `2`.
- Snapshot Creative Treatments: `3`; Variation Groups: `0`.
- Rollback is recoverable from the verified pre-activation online backup. No destructive down migration was executed.

## Zero-credit scale proof

The disposable proof opened no database and exercised the existing applicability registry, Treatment Template authority, P6 creative-DNA projection, compiler prompt hashing, workspace execution payload construction, scheduler payload hashing, and final deterministic revalidation.

- Supported profiles resolved: `101/101` (`103` total registry profiles; unsupported profiles failed closed).
- Format/mode matrix: `12/12` ready across UGC/PGC/CINEMATIC and T2V/I2V/F2V/HYBRID.
- Single product: `100 planned / 100 materialized / 100 compiled / 100 dry-run ready`, deterministic replay `true`.
- Mixed product: `100 planned / 100 materialized / 100 compiled / 100 dry-run ready`, deterministic replay `true`, one additional unsupported fixture isolated with an exact reason.
- Variation Group: exactly `5` members, byte-identical dialogue identity, `5` distinct visual fingerprints, unrestricted Cartesian mixing `false`.
- Scale artifact SHA-256: `0b9251c8968b5298b7378d3fd4a2e2f42df764427314723340f2683768add7c6`.
- Provider calls: `0`; Google Flow calls: `0`; media-generation calls: `0`; credit spend: `0`.

The canonical catalog result is intentionally not reported as production-ready: current human approval/evidence/asset/treatment gates remain authoritative and no missing authority was fabricated.
