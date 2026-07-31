# P7.5-P6 Integration Closure Evidence

## Delivery identity

- Request: `BOSMAX-P7.5-P6-INTEGRATION-CLOSURE-20260731`
- Base: `d3343bf83242004575b79f2201e8bdcec980b348`
- Branch: `codex/p75-p6-treatment-governed-extend`
- Worktree:
  `C:\Users\USER\Desktop\_ref_flowkit\.claude\worktrees\codex-p75-p6-treatment-governed-extend`
- Mandor domain: `workspace`
- Domain status: `IN_PROGRESS`

## Pre-implementation evidence

- PR #560 merged cleanly into the selected base before branch creation.
- Canonical runtime source SHA before delivery:
  `feda1b1e...`; `source_stale_since_start=false`.
- Canonical database: 659 products, 13 P6 plans, 23 attempts.
- Creative Treatments: 0 approved; eligible cohort capacity: 0.
- Active provider-known attempts: 0; active lane leases: 0.
- Provider request metrics before delivery: 586 requests, 541 successes,
  43 failures.
- Credit status read returned `UNAUTHENTICATED`; no submission was made.
- Existing focused treatment/P6 suite: 25 passed.

## Reproduced blockers

### B01 - Production Studio selection authority absent

- backend create-plan requires explicit `pools.treatment_ids`;
- frontend request type and payload omit `treatment_ids`;
- Studio exposes no availability/capacity/format selector;
- therefore the browser cannot create an authoritative treatment-backed video
  plan.

### B02 - governed EXTEND rejected

The rejection is enforced independently by:

- Pydantic `CreateTreatmentRequest`;
- SQLite `creative_treatment.generation_mode` CHECK;
- treatment authority resolution;
- P6 product-dimension materialization;
- compile service;
- UGC/full-storyboard prompt compiler;
- canonical block renderer;
- scheduler payload construction.

The existing durable video-production orchestrator already supports ordered
16/24-second continuation and concat and is intentionally unchanged.

## Frozen changed-file ledger

1. `docs/MODULE_STATUS.yaml`
2. `.ai/architecture/CREATIVE_TREATMENT_P6_INTEGRATION_CLOSURE.md`
3. `docs/evidence/p7-5-p6-integration-closure.md`
4. `agent/db/schema.py`
5. `agent/db/creative_treatment_crud.py`
6. `agent/models/creative_treatment.py`
7. `agent/services/creative_treatment_service.py`
8. `agent/models/creative_production.py`
9. `agent/services/creative_production_plan_service.py`
10. `agent/api/creative_production.py`
11. `agent/services/creative_production_compile_service.py`
12. `agent/services/workspace_execution_package_service.py`
13. `agent/services/ugc_video_prompt_compiler_service.py`
14. `agent/services/canonical_prompt_compiler.py`
15. `agent/services/creative_production_scheduler_service.py`
16. `dashboard/src/api/creativeProduction.ts`
17. `dashboard/src/pages/CreativeProductionStudioPage.tsx`
18. `tests/api/test_creative_treatments_api.py`
19. `tests/api/test_creative_production_api.py`
20. `tests/unit/test_creative_treatment_migration.py`
21. `tests/unit/test_creative_treatment_service.py`
22. `tests/unit/test_creative_production_treatment_integration.py`
23. `tests/unit/test_creative_treatment_prompt_compiler.py`
24. `tests/unit/test_workspace_execution_package_service.py`
25. `dashboard/src/pages/CreativeProductionStudioPage.test.tsx`

Any additional file requires this ledger to be amended before that file is
modified.

## Validation and delivery proof

### Mission-owned tests

- `python -m pytest tests/unit/test_creative_treatment_migration.py
  tests/unit/test_creative_treatment_service.py
  tests/api/test_creative_treatments_api.py
  tests/api/test_creative_production_api.py
  tests/unit/test_creative_production_treatment_integration.py
  tests/unit/test_creative_treatment_prompt_compiler.py
  tests/unit/test_workspace_execution_package_service.py -q`
  - exit code 0;
  - 61 passed;
  - one pre-existing Pydantic field-shadowing warning.
- `npx vitest run src/pages/CreativeProductionStudioPage.test.tsx
  --pool=forks --maxWorkers=1 --minWorkers=1`
  - exit code 0;
  - 11 passed.

### Build and architecture gates

- `npm run build`
  - exit code 0;
  - real `tsc -b && vite build` passed;
  - emitted `dist/assets/index-B-tTs-MQ.js`;
  - existing bundle-size advisory only.
- `npx @biomejs/biome check --write .`
  - exit code 0;
  - 32 configured files checked;
  - no lint errors;
  - 7 existing unsafe optional-chain suggestions and one schema-version info;
  - formatter-only changes outside the authorized ledger were restored exactly.
- `npx depcruise dashboard/src --config .dependency-cruiser.cjs`
  - exit code 0, no violations;
  - Windows directory discovery cruised zero modules.
- Meaningful Windows dependency traversal from
  `dashboard/src/main.tsx`, with the same `no-circular` rule and a temporary
  filter-free configuration:
  - exit code 0;
  - 177 modules and 619 dependencies cruised;
  - no dependency violations.
- `npx tsx scripts/mandor-check.ts`
  - exit code 0;
  - `PASS_MODULE_STATUS_DOMAIN_RESOLVED domain=workspace paths=25`.

### Aggregate verification gate

`scripts/verify-gate.ps1` completed with:

- Mandor: passed;
- dashboard build: passed;
- dashboard Vitest: passed;
- backend smoke: 187 passed, one failed;
- aggregate result: failed.

The sole failure is
`tests/unit/test_canonical_prompt_compiler.py::
test_legacy_entrypoint_delegates_and_uncaps_blocks`, which raises
`AVATAR_REGISTRY_SELECTION_REQUIRED`. The identical failure was reproduced
against the clean detached base
`d3343bf83242004575b79f2201e8bdcec980b348`. The failing guard is outside the
mission diff, so this is recorded as a pre-existing baseline failure and is not
patched by this closure.

### Provider and credit invariant

No provider authorization, generation submission, Generate click, DeepSeek
request, or credit-spending action occurred during implementation or local
validation.

## Post-merge rendered UAT remediation ledger

Browser UAT on canonical data proved a performance blocker in
`/api/creative-production/cohort-authority`.

26. `agent/services/product_intelligence_service.py`
27. `tests/unit/test_product_intelligence_service.py`
28. `agent/services/product_image_analysis_service.py`
29. `tests/unit/test_product_image_analysis_service.py`
30. `agent/services/catalog_coverage_service.py`
31. `tests/unit/test_catalog_coverage_service.py`

No other follow-up file is authorized until this ledger is amended again for
that follow-up.

## Post-merge remediation validation

- Initial canonical browser UAT on merge `214db5e...` rendered Studio but
  `/api/creative-production/cohort-authority` exceeded 30 seconds and
  blocked the governed product picker.
- CPU profiling proved all 659 taxonomy read models were recomputed
  twice and sales-name/image-path work was repeated per product.
- Repair:
  - reuses the pre-normalized sales-name index;
  - avoids filesystem canonicalization for metadata-only image paths;
  - reuses one attached taxonomy product set across both matrices.
- Canonical-data read-only authority benchmark:
  - 18.322 seconds;
  - 659 products;
  - P6 launch cohort count 438;
  - SHA-256 `0a7d54cdd46bf1ab6cad98b282c6ee1dd21463b2692cb3f05fa059e9ee72f0ec`.
- Focused product-intelligence/image-analysis/catalog suite:
  - exit code 0; 42 passed.
- Original P7.5-P6 mission regression suite:
  - exit code 0; 61 passed; one pre-existing Pydantic warning.
- `npx tsx scripts/mandor-check.ts`:
  - exit code 0; `domain=workspace paths=7`.
- `npx @biomejs/biome check --write .`:
  - exit code 0; 32 configured files checked;
  - 29 formatter-only files outside the ledger were restored exactly.
- `npx depcruise agent/services --config .dependency-cruiser.cjs`:
  - exit code 0; zero violations; zero modules traversed.
- Aggregate `scripts/verify-gate.ps1`:
  - Mandor, dashboard build, and dashboard Vitest passed;
  - backend smoke retained the clean-base failure: 187 passed, one failed.
- No provider call, generation submission, Generate click, DeepSeek request,
  browser action with submit semantics, or credit-spending action occurred.
- Final rendered no-submit UAT remains gated on merging and rolling out this
  follow-up branch.
