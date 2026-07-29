# P5.8 Final Catalog Authority Evidence

## Mission and authority

- Mission:
  `BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729`.
- Domain: `workspace`, status `IN_PROGRESS`.
- Accepted base:
  `82bd26c70b37d1ad5b7d8731ed39019d5e169bb8`.
- Worktree:
  `C:\Users\USER\.codex\worktrees\p58-final-catalog-authority\_ref_flowkit`.
- Branch: `codex/p5-8-final-catalog-authority`.
- Product Truth authority remains exact source taxonomy or an explicit,
  product-ID-bound reviewed decision. Runtime title inference is not authority.
- P6 execution is out of scope. P5.8 only freezes the explicit cohort.

## Frozen source scope

- `docs/MODULE_STATUS.yaml`
- `agent/authority/catalog_product_type_truth.py`
- `agent/authority/product_type_copy_strategy_registry.py`
- `agent/models/product_type_copy_strategy.py`
- `agent/services/scene_strategy_library.py`
- `agent/services/product_strategy_scouting_service.py`
- `agent/services/catalog_coverage_service.py`
- `agent/services/catalog_authority_review_service.py`
- `agent/services/catalog_authority_apply_service.py`
- `agent/api/copywriting.py`
- `scripts/p58-catalog-authority-closure.py`
- `dashboard/src/api/products.ts`
- `dashboard/src/types/index.ts`
- `dashboard/src/pages/ProductTypeRegistryPage.tsx`
- `dashboard/src/pages/ProductTypeRegistryPage.test.tsx`
- `tests/unit/test_catalog_product_type_truth.py`
- `tests/unit/test_scene_strategy_library.py`
- `tests/unit/test_product_strategy_scouting_service.py`
- `tests/unit/test_product_type_copy_strategy_service.py`
- `tests/unit/test_catalog_coverage_service.py`
- `tests/unit/test_catalog_authority_review_service.py`
- `tests/unit/test_catalog_authority_apply_service.py`
- `tests/api/test_product_type_copy_strategy_api.py`
- `docs/evidence/p5-8-final-catalog-authority.md`
- `docs/evidence/p5-8-deepseek-review-ledger.json`

Scope expansion requires an explicit update to this ledger before the added
file is modified.

Explicitly excluded:

- `agent/services/product_knowledge_service.py`
- `agent/services/ai_copy_provider_adapter.py`
- P5.6-R2 source files
- schema migrations
- dependency updates
- media generation and Google Flow execution

## Canonical read-only baseline

The baseline came from a consistent SQLite online backup while the canonical
runtime remained live:

- Canonical source database:
  `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`.
- Backup SHA-256:
  `1d579cd5c12ce46f972c5c53f02c90478921acada27cfc68a70f9012511d3673`.
- SQLite `integrity_check`: `ok`.
- SQLite `quick_check`: `ok`.
- Total: 659 products (443 active, 216 archived).
- Product Truth mapped: 476.
- P4 supported: 399.
- `unknown_product_type`: 133.
- `unknown_product_type` with P4: 0.
- Baseline P6-shaped cohort: 112.
- Matrix SHA-256:
  `1cec26923c4ea9d87c5211b130f7d4d7fe1430868ff5a96b29de2cf34fe07cd4`.

The canonical runtime proof reported source and served bundle alignment with
`source_stale_since_start=false`. No canonical mutation or restart occurred
during baseline capture.

## P5.7 isolated prerequisite rehearsal

P5.7 was applied twice to an isolated copy:

- First pass: 47 registry inserts, 20 registry updates, 290 taxonomy updates.
- Second pass: zero registry or taxonomy mutations.
- Manual overrides preserved: 169.
- Post-rehearsal Product Truth mapped: 476.
- Post-rehearsal P4 supported: 566.
- Post-rehearsal unknown: 61, including 37 active.
- Post-rehearsal P6-shaped cohort: 112.
- Stable matrix SHA-256:
  `a4d9b5affbaf0d025f3d6b2a9b1967e679e3d4f44d4bdc18b91e405d43b31da4`.

## Root cause

The residual catalog is not one homogeneous missing-strategy problem:

1. Exact source product types exist but are absent from Product Truth mapping.
2. Broad source buckets contain multiple real product types and cannot share a
   generic P4 strategy.
3. Category-only rows require explicit approved Product Truth review; category
   alone is not sufficient authority.
4. Previously reviewed taxonomy rows can become stale when the exact source
   mapping becomes more specific.
5. Some rows remain legitimately blocked because approved Product Truth is
   absent, contradictory, or insufficient.

`unknown_product_type` remains fail-closed and will never receive a generic P4
strategy.

## Bounded DeepSeek review

The configured `text_assist` provider was `deepseek/deepseek-v4-pro`, ready and
enabled at preflight. Provider review remained bounded to unresolved signature
groups and used a strict response schema plus independent source-authority
review.

- Attempt 1: 20 unresolved signatures; `httpx.ReadTimeout` after 42.8 seconds.
- Attempt 2: 10 compact unresolved signatures; `httpx.ReadTimeout` after 42.4
  seconds.
- Provider-call budget consumed: 2 of 20.
- Valid provider decisions: 0.
- Provider decisions admitted to Product Truth: 0.
- Raw provider output stored in the repository or canonical database: none.

The provider lane was stopped after the repeated failure. All admitted
decisions are deterministic Codex-reviewed, product-ID-bound decisions grounded
in approved Product Truth or an exact duplicate Product Truth signature.

## P5.8 isolated transactional rehearsal

P5.8 was rehearsed against a clean isolated copy of the P5.7-state database:

- Database:
  `C:\Users\USER\AppData\Local\Temp\bosmax-p58-82bd26c-baseline\rehearsal-v4-final\flow_agent.db`.
- Pre-apply backup SHA-256:
  `33d94884a9bf79fcf024d28e7d30c1e8ab28750b1f52eda314bd6f50a7255e0c`.
- SQLite `integrity_check`: `ok`.
- SQLite `quick_check`: `ok`.
- Products before and after: 659.
- Dry run: 49 registry inserts, 420 taxonomy updates, 37 manual taxonomy
  decisions preserved, and zero database mutation.
- First apply state fingerprint:
  `eef2071ac7030bffb00f6f9e64d608bbed3218d52a544f5164e7ee0d68463a52`
  -> `742835df83f5a8225283aa08032a68b5da07b91d6b42b6568e1841e55df542c4`.
- Second apply: zero registry or taxonomy mutations; final fingerprint
  unchanged.
- Protected non-authority tables before and after:
  `d68dbe0870c19877a8ce605fe4881bcd08b532f86f1187b291ea5c30f263868c`.
- Post-apply SQLite `integrity_check`: `ok`.
- Post-apply SQLite `quick_check`: `ok`.
- Rollback posture: the runner uses one `BEGIN IMMEDIATE` transaction, rolls
  back on verification failure, and records the pre-apply backup manifest.

The resulting authoritative matrix has exactly one terminal state for every
product:

| Terminal state | Products |
| --- | ---: |
| `P6_READY` | 438 |
| `REVIEW_BLOCKED_WITH_EXACT_REASON` | 2 |
| `INSUFFICIENT_PRODUCT_TRUTH` | 3 |
| `ARCHIVED_NOT_IN_SCOPE` | 216 |
| **Total** | **659** |

Additional closure proof:

- Product Truth mapped: 628.
- P4 supported: 640.
- `unknown_product_type`: 14.
- `unknown_product_type` with P4: 0.
- Matrix SHA-256:
  `c6953840db97f6b003130cc6fa84433fec5ab18dc6400f61d7d23c9be115b90d`.
- Explicit P6 cohort: 438 `VERIFIED + READY + COVERED + P4_SUPPORTED`
  products.
- P6 cohort SHA-256:
  `15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f`.
- P6 jobs started: 0.

The three insufficient rows have explicit product-ID-bound reasons: approved
truth absent for one herbal cream, sample-size-only truth for one baby sample,
and title-only truth for one gift bag. The two active review blockers retain
exact reasons: unverified output/runtime claims for one headlamp and unverified
savings plus electrical-safety claims for one power-saving device.

Generated rehearsal evidence is held outside the repository at:
`C:\Users\USER\AppData\Local\Temp\bosmax-p58-82bd26c-baseline\rehearsal-v4-final\evidence`.

The runner emitted all eight final deliverables, including the 659-row
CSV/JSON matrix, 128-row registry export, five-row residual review queue,
438-product sorted P6 cohort, blocker summary, sanitized DeepSeek ledger, and
transaction manifest.

## Local validation

- Final focused authority, taxonomy, API, and Smart Registration backend
  matrix: 256 passed.
- Product Type Registry UI suite: 8 passed.
- Adjacent Products and Smart Registration UI suites: 16 passed.
- Full dashboard Vitest: 472 passed.
- Dashboard production build: Exit Code 0.
- Source production bundle: `index-DOULX3xT.js`.
- Python compilation: Exit Code 0.
- TypeScript project build: Exit Code 0.
- Focused Biome check: Exit Code 0.
- Dependency graph: 232 modules and 600 dependencies, zero violations.
- Mandor: `workspace` ownership resolved, Exit Code 0.

The repository verification gate passed Mandor, dashboard build and all 472
dashboard tests. Its backend smoke lane reported 187 passed and one unrelated
canonical prompt/avatar failure. The exact failing test was reproduced on
untouched accepted main `82bd26c70b37d1ad5b7d8731ed39019d5e169bb8`;
P5.8 does not modify that compiler or its test, and the mission explicitly
forbids repairing this unrelated baseline failure.

## Canonical delivery evidence

The source patch and the canonical dry-run guard repair were merged through
reviewed, non-draft pull requests:

- PR #539:
  `https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/539`.
- Feature commit:
  `62b3e4322bf9e45e8fb017f46cb146072e335045`.
- Feature merge:
  `0d572d4e5f5712622cb0fcac4870b4100c5c91a9`.
- PR #540:
  `https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/540`.
- Canonical preview-guard repair:
  `bf63ee61a050d0cee259b4bbb45f6f500aa73517`.
- Canonical source merge:
  `2578c998c574c170f95a812828c4ec0606197d9c`.
- Both repositories reported no configured remote checks; no CI claim is made.

The final guarded transaction ran against:
`C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`.

- Pre-apply backup:
  `C:\Users\USER\AppData\Local\Temp\bosmax-p58-canonical-2578c99-final\backups\flow_agent.p58-pre-apply-20260729T104541Z.db`.
- Backup SHA-256:
  `1d579cd5c12ce46f972c5c53f02c90478921acada27cfc68a70f9012511d3673`.
- Backup integrity and quick checks: `ok`; product count: 659.
- Canonical dry run: 96 registry inserts, 20 registry updates, 541 taxonomy
  updates, 37 manual taxonomy decisions preserved, zero mutation.
- First apply authority fingerprint:
  `b429255ea88712694f3e4108d7f2f64ca837f370de7c8129ff4417ccdbc701a3`
  -> `d083b2b915ded3b14f850a87d3ab13b5cb4cb51a46a7324eb2e6213d97d4d0c1`.
- Protected non-authority fingerprint remained
  `d68dbe0870c19877a8ce605fe4881bcd08b532f86f1187b291ea5c30f263868c`.
- Second apply: zero registry/taxonomy mutations; authority and protected
  fingerprints unchanged.
- Post-apply integrity and quick checks: `ok`; product count: 659.
- Rollback was not required; the backup and transactional rollback path remain
  available.
- Final canonical matrix SHA-256:
  `5924a8e5509998cb41865ec3b6ee0ccff8226790d409ce83bba811c520535644`.
- Final P6 cohort SHA-256:
  `15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f`.
- P6 cohort count: 438; P6 execution started: 0.

The canonical evidence pack is:
`C:\Users\USER\AppData\Local\Temp\bosmax-p58-canonical-2578c99-final\evidence`.
It contains the final matrix CSV/JSON, registry, residual queue, cohort,
blocker summary, sanitized DeepSeek ledger, backup/apply manifest, queue
safety proof, and post-apply database checks.

## Canonical runtime and rendered UAT

The canonical runtime was restarted with the official repository helper after
the source merges. Runtime proof reported:

- backend Git SHA:
  `2578c998c574c170f95a812828c4ec0606197d9c`;
- dashboard bundle: `index-BJ8S5Y-H.js`;
- route count: 466;
- `source_stale_since_start=false`;
- effective database:
  `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`;
- product count: 659; storage warnings: none.

Rendered browser UAT covered direct refresh, loading, success, empty-filter,
compact 768x720, scoped authority-request failure, recovery, Products, and
Smart Registration states. The failure was injected only through a
tab-scoped blocked URL and was removed before recovery. It did not change the
server or database. Recovery returned HTTP 200 for the authority, P4, and
registry APIs and restored counts 659/438/2/3/216. Products loaded its active
298-row FastMoss view from HTTP 200. Smart Registration loaded its review queue
from HTTP 200 without a submit or mutation.

Browser evidence is held at:
`C:\Users\USER\AppData\Local\Temp\bosmax-p58-canonical-2578c99-final\browser-uat`.
The manifest is `p58-browser-uat-manifest.json`, SHA-256
`e1c918d1c7f0b850b55e5426ea94941b6bdc47850f4c04c386315ff2b06e39e7`.

A final canonical dry run after browser UAT reported zero registry/taxonomy
mutations, the same authority and protected fingerprints, 659 products,
integrity/quick checks `ok`, the same 438-product cohort, and
`p6_not_started=true`.
