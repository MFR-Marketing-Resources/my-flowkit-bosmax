# Poster Builder V3 PR-C QA Review — 2026-08-08

## Scope

PR-C adds the governed Campaign route behind the existing feature flag. The
route compiles a clean key visual request for Google Flow/Nano Banana, reuses
the approved Product Reference Pack, composes deterministic copy locally after
the provider result returns, exposes three controlled local variants, and
requires explicit human review. Exact Commerce is unchanged and remains the
rollback/fallback lane.

No provider generation, credit spend, or canonical database mutation occurred
during this static and focused QA pass.

## Source and gate evidence

| Check | Result |
| --- | --- |
| Worktree | `codex/poster-builder-v3-c-qa-review-20260808` |
| Source baseline | `1d4513b135eeb425e65df34a6090c59b4c2acf40` (PR-B merge) |
| `scripts/verify-gate.ps1` | PASS — build, Vitest, curated backend smoke, Mandor |
| `npx tsx scripts/mandor-check.ts` | PASS, exit 0; `domain=workspace` |
| `npx @biomejs/biome check --write .` | exit 0; legacy extension warnings only |
| Dependency graph | PASS — 201 modules, 549 dependencies, no violations |
| Focused poster/image regression | PASS — 122 tests, 2 warnings |
| Dashboard Poster Builder tests | PASS — 64 tests |
| Dashboard production build | PASS — Vite production build completed; final served bundle is recorded during canonical deployment |

Biome's 18 `useOptionalChain` warnings are pre-existing extension warnings;
the extension is outside this PR-C blast radius and was not reformatted with
unsafe fixes.

## No-spend benchmark

Command:

```text
python scripts/poster-builder-v3-benchmark.py --agent-dir C:\Users\USER\Desktop\_ref_flowkit
```

The command intentionally exits non-zero when a production gate is blocked. It
returned `DRY_RUN_BLOCKED` with `provider_operation_count=0`,
`maximum_provider_operations=1`, and `max_retry_operations=0`.

| Evidence | Value |
| --- | --- |
| Product | `6483d624-a03d-4933-9bba-6ca2e5f7b6fd` — Minyak Warisan Cap Burung 25ml |
| Approved snapshot | `c06504d2-1666-4ca1-8ae4-88a06d7c359c`, version 5 |
| Reference Pack | `prp_5f5ff615134b256b780935b42b22`, `APPROVED` |
| Machine pack QA | `WARN`; crop/cutout candidates retain human-review evidence |
| Model/output | `NANO_BANANA_PRO` / `CLEAN_KEY_VISUAL` |
| Selected dry-run route | `ROUTE_01`, score 78, `DRAFT_FALLBACK_NOT_PRODUCTION` |
| Blocker | `COPY_ROUTE_NOT_PRODUCTION_ELIGIBLE` |
| Local manifest fingerprints | 3 distinct fingerprints |

The blocker is intentional: a deterministic fallback copy candidate is not
silently promoted to production. The live UAT uses a separately approved copy
set whose copy score, approved facts and provenance satisfy the same lint.

## Full-suite classification

The full backend/UI suite returned `5162 passed, 4 skipped, 125 failed`.
The 125 failures are cross-domain/historical fixture failures, including the
known exact poster fixture without a persisted truth lock, legacy reference
slot expectations, product/scene fixture counts, video/PI rollback suites and
unrelated UI contract surfaces. The closest failures were reproduced on clean
PR-B commit `6bd43a5`:

- `tests/api/test_flow_ref_ordering.py::test_ref_slot_order_is_the_canonical_contract`
- `tests/api/test_poster_copy_sets_api.py::test_compose_api_flow_with_mocked_renderer`
- `tests/api/test_flow_request_lineage_payload_api.py::test_execute_flow_job_persists_request_lineage`

The PR-C focused suite and the mandatory verification gate are green. No
full-suite failure has a diff-linked reproduction in the PR-C files.

## Live acceptance gate

The feature flag and live benchmark authorization remain off by default until
the accepted merge SHA is deployed. The bounded live UAT is one provider
operation, zero retries, one clean key visual, followed by three local
compositor variants. Every operation ID, artifact hash, prompt fingerprint,
reference-role hash, machine QA result and human review decision must be
recorded. Production default remains Exact Commerce until artifact inspection
and canonical Profile 43 browser UAT meet the acceptance rubric.
