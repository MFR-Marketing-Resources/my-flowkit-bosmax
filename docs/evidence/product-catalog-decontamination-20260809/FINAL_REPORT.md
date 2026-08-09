# BOSMAX Catalog Decontamination — 2026-08-09

## VERDICT

PASS

## WHY IT MATTERS

The catalog denominator now distinguishes raw rows, lifecycle populations, historical aliases, real canonical products, and production visual onboarding. The authorized exact-duplicate cohort is governed by external listing identity, variant compatibility, transaction guards, and durable tombstone evidence; visual coverage remains anchored to the same canonical product without provider spend.

## NEXT ACTION

Land the post-purge closure evidence hardening, then re-read the final merged runtime/database provenance.

## STATUS

origin/main: d03ca4fcddbce16a0c4ef8ae4fb6d4b8eb512940
implementation commit: d03ca4fcddbce16a0c4ef8ae4fb6d4b8eb512940
PR: #678 — https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/678
merge SHA: d03ca4fcddbce16a0c4ef8ae4fb6d4b8eb512940
runtime SHA: d03ca4fcddbce16a0c4ef8ae4fb6d4b8eb512940
runtime PID: 38240
canonical DB: C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db
DB SHA before: f9917a08288796fec61159cdba9d4a916da473a2626445a25ba9d02e0ce5b683
DB SHA after: 6525e16a9e527469b5900737ba21521af061c53bd8e5229324a2300f2a0da8a4
integrity: ['ok']
foreign keys: 0
provider operations: 0

backend source/worktree: C:\Users\USER\.codex\worktrees\catalog-decontamination-evidence-20260809
backend cwd: C:\Users\USER\.codex\worktrees\catalog-decontamination-evidence-20260809
backend loaded branch: codex/catalog-decontamination-evidence-20260809
Chrome extension: C:\Users\USER\Desktop\_ref_flowkit\extension
extension build SHA: e8353a4944ee9764b17ddece3cba509347e7afb5
extension background/content build ID: flowkit-canonical-dom-guard-2026-07-13a
extension connected: true

## RAW CATALOG — BEFORE

RAW_PRODUCT_ROWS = 901
ACTIVE_ROWS = 584
ARCHIVED_ROWS = 317
MERGED_ALIAS_ROWS = 48
REAL_CANONICAL_PRODUCTS = 845

## 48 MERGE_PROVEN REPROOF

historical cohort = 48
re-proven = 48
drifted = 0
canonical survivors = 48

## PURGE RESULT

physical duplicate deletes = 48
canonical survivor deletes = 0
unauthorized deletes = 0
child records migrated = 8
child records safely retired = 410
tombstones created = 48
blocked aliases = 0

Exact post-purge closure: 48/48 expected alias UUIDs absent; 48/48 tombstones present; 48/48 canonical survivors present and unchanged; canonical survivor deletes = 0; unauthorized product deletes = 0; unresolved alias references = 0; duplicate ACTIVE authoritative platform IDs = 0; purged IDs receiving visual/provider work = 0.

## RAW CATALOG — AFTER

RAW_PRODUCT_ROWS = 853
ACTIVE_ROWS = 584
ARCHIVED_ROWS = 269
MERGED_ALIAS_ROWS = 0
REAL_CANONICAL_PRODUCTS = 845
Arithmetic: 901 - 48 = 853

## DECONTAMINATION REMAINDER

NEW_EXACT_DUPLICATE_CANDIDATES = 167
NEAR_DUPLICATE_REVIEW = 12
SUPERSEDED_OUTDATED = 35
TEST_JUNK = 8
BROKEN_ORPHAN = 0
REVIEW_REQUIRED = 0

## CANONICAL VISUAL COVERAGE

CANONICAL_PRODUCTION_PRODUCTS = 454
APPROVED_CUTOUT = 1
CANONICAL_REFERENCE_FALLBACK = 453
CUTOUT_PENDING_REVIEW = 0
BLOCKED_NO_TRUSTED_PRODUCT_MEDIA = 0
REVIEW_REQUIRED_VISUAL_IDENTITY = 0
VISUAL_GROUNDING_AVAILABLE = 454
EXACT_COMMERCE_CUTOUT_READY = 1

## REMOTE PROOF

branch = codex/catalog-decontamination-evidence-20260809
commit SHA = d03ca4fcddbce16a0c4ef8ae4fb6d4b8eb512940
PR number = None
PR URL = None
CI = None
merge SHA = None
current remote main SHA = None
merge ancestry verified = None

## DATABASE PROOF

backup path = C:\Users\USER\Desktop\_bosmax_recovery\product-catalog-decontamination-20260809\flow_agent.pre-purge.db
backup SHA-256 = f9917a08288796fec61159cdba9d4a916da473a2626445a25ba9d02e0ce5b683
pre integrity_check = ['ok']
post integrity_check = ['ok']
pre foreign_key_check = []
post foreign_key_check = []
pre data_version = 2
post data_version = 2

post-purge closure before-survivor SHA-256 = 2a27d05669f8c0e8478f624ae5bce739d1605ab89963ae977091c5675397ef56
post-purge closure after-survivor SHA-256 = 2a27d05669f8c0e8478f624ae5bce739d1605ab89963ae977091c5675397ef56
post-purge closure gates = ALL PASS

## TESTS

`python -m py_compile scripts/product_catalog_decontamination.py` — PASS
`python -m pytest -q tests/unit/test_product_catalog_decontamination.py tests/api/test_runtime_storage_diagnostic_api.py` — 7 passed
`npx @biomejs/biome check --write .` — exit 0; 18 pre-existing extension warnings, no fixes applied
`npx tsx scripts/mandor-check.ts` — exit 0
`node C:\Users\USER\Desktop\_ref_flowkit\node_modules\dependency-cruiser\bin\dependency-cruise.mjs [283 dashboard/src files] --config .dependency-cruiser.cjs --output-type err` — exit 0; 283 modules, 719 dependencies, 0 violations
`powershell -ExecutionPolicy Bypass -File scripts/verify-gate.ps1` — PASS: dashboard build, 70 Vitest files / 605 tests, 13-suite backend smoke
`git diff --check` — PASS

## NOT VERIFIED

NONE

## RISKS

NONE

## NEXT DECISION

FINAL_RUNTIME_PROOF_AFTER_POST_PURGE_EVIDENCE_LANDING
