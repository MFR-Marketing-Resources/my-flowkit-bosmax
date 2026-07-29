# P6 Batch Creative Production Orchestrator Evidence

Mission: `BOSMAX-P6-BATCH-CREATIVE-PRODUCTION-ORCHESTRATOR-20260729`

## Scope and authority

- Base authority: accepted `origin/main` containing merged P5.8 catalog authority.
- Frozen P5.8 launch cohort: 438 products; SHA-256
  `15b7e2aff4ede06b1a28805b111f9993b2208040e40bcee76693abc2a6ddbe7f`.
- Eligible input remains the exact conjunction
  `VERIFIED + READY + COVERED + P4_SUPPORTED`.
- Domain: `workspace`, explicitly `IN_PROGRESS` in
  `docs/MODULE_STATUS.yaml`.
- Canonical prompt compilers, `make_video.start_generate`,
  Product Truth, P5.8 authority files, and canonical database content are not
  rewritten by this patch.

## Durable control plane

The additive SQLite model contains production plans, waves, review batches,
creative items, execution lanes, generation attempts, lane leases, output QA,
and actor-bound audit events. All queue identities and transition request IDs
are durable and idempotent. Restart recovery never performs a blind resubmit.

Plan configuration binds:

- frozen P5.8 product scope and cohort hash;
- COPY_APPROVED and POSTER_COPY_APPROVED authorities;
- product-first APPROVED Avatar Registry selection;
- approved Creative Asset Registry roles;
- authoritative poster recipes;
- exact P5.8 non-fallback scene strategy;
- model, duration, operating-window and bounded controlled-reuse policies.

Raw operator-authored angle, hook and CTA overrides are intentionally absent.
Creative DNA uses the approved copy bundle, scene strategy, product interaction,
avatar profile, governed asset roles, model, duration, media mode and layout.
Historical exact DNA is excluded. Near-duplicate state is explicit and does not
silently become an exact-duplicate block.

## Capacity and scheduling

Capacity preflight reports requested volume, safe unique capacity, historical
exclusions, copy reuse pressure, avatar/scene pressure, lane-window capacity,
blockers, remediation and assumption evidence. The 8/12/24-hour estimates are
capacity objectives, not provider SLAs.

Execution reuses the accepted API-first generation door. The scheduler is inert
unless the existing default-false `BULK_LIVE_EXECUTION_CERTIFIED` boundary is
true, a scheduled plan carries explicit live authorization, the exact
credit-confirmation phrase is supplied, and a matching zero-credit dry-run
attempt exists. Video lane concurrency defaults to one verified inflight job.
The image/poster lane remains disabled and unverified until separate evidence is
recorded.

## Zero-credit rehearsal evidence

- Python focused P6 pack after both authority hardening follow-ups: 31 tests
  passed.
- Rendered Production Studio test: 6 tests passed.
- Full dashboard Vitest suite: 57 files, 478 tests passed.
- Dashboard TypeScript/Vite production build: passed.
- Provider media calls during focused tests: 0.
- Media credit spend during focused tests: 0.
- Recovery test registers an existing generated-artifact ledger row without
  calling the generation door.
- Disabled-certification scheduler test proves zero dispatch.
- Fresh SQLite online backup rehearsal:
  `C:\Users\USER\AppData\Local\Temp\bosmax-p6-rehearsal-final-60c6b90dc6d5464db1b034d9cf704997\flow_agent.db`;
  pre-migration SHA-256
  `7121dcfda550e4fc3598d071adbe0a06d04f4b35865c9fc8d1788e6d128abd13`,
  `PRAGMA integrity_check=ok`, 659 products and zero pre-existing P6 tables.
- Rehearsal authority readback: cohort 438, frozen hash matched, governed pool
  blockers zero, preflight `PREFLIGHT_READY`, one matrix item, compile
  `PENDING_APPROVAL`, plan `APPROVED`, one wave, seven audit events.
- Rehearsal dry-run: checked 1, ready 1, blocked 0, provider media calls 0,
  media credit spend 0. The isolated image lane and synthetic Flow UUID were
  explicitly labeled `ISOLATED_ZERO_CREDIT_REHEARSAL_ONLY` and
  `ISOLATED_SIMULATED_FLOW_UUID_NO_PROVIDER_CALL`; neither is canonical runtime
  certification.
- Scheduler tick after rehearsal: live certification false, plans examined 0,
  attempts dispatched 0 and credit spend 0.
- Isolated FastAPI runtime on port 18106 returned health `ok`, cohort 438 with
  matching frozen hash, two execution lanes and the persisted rehearsal plan.
  A live-start request with the exact phrase returned HTTP 403
  `P6_LIVE_EXECUTION_NOT_CERTIFIED`; attempt count remained 1 before/after and
  plan state remained `SCHEDULED`.
- Broad P6/catalog/copy/queue/bulk regression: 453 passed. Four failures in
  `test_batch_planner.py` and `test_batch_queue.py` reproduced byte-for-byte on
  a clean `origin/main` archive (two missing fixed-product fixtures and two
  existing `20 values for 21 columns` insert failures); they are not P6
  regressions and those frozen files were not changed.
- Official local verification gate: Mandor, real dashboard build and dashboard
  Vitest passed. Its backend smoke result was 187 passed / one failed; the
  exact `AVATAR_REGISTRY_SELECTION_REQUIRED` failure in
  `test_legacy_entrypoint_delegates_and_uncaps_blocks` reproduced on clean
  `origin/main` and remains outside the P6 ownership boundary.
- Dependency graph: 168 modules and 467 dependencies cruised, with zero
  violations, errors or warnings.
- Scoped Biome check for every P6 TypeScript surface and `App.tsx`: exit 0.
- Mandor ownership check: `workspace`, 20 changed paths, exit 0.

## Delivery and canonical proof

- Feature PR #542 merged as
  `c74adde12e452c10d0a0d926b117340618503bd8`.
- F2V compiler-authority follow-up PR #543 merged as
  `be0456f6028cc4ff1ccb3abd11337fe759bf55ba`.
- Canonical migration created the nine P6 tables against an online backup with
  `PRAGMA integrity_check=ok`; the 659-product catalog was preserved.
- Canonical browser rehearsal created one governed F2V item, compiled it through
  the real workspace compiler, approved it, assigned one durable wave, and
  produced one matching `NOT_SUBMITTED` dry-run attempt. Provider job ID stayed
  null and intended credit spend stayed zero.
- Pause survived an official runtime restart. Resume, reconciliation, retry
  refusal and cancellation were rendered and persisted. The final plan and item
  are `CANCELLED`; the attempt is `NOT_SUBMITTED`; no lane lease remains.
- A post-deployment truth audit found that canonical runtime carried a
  pre-existing global live-execution certificate while the UI text claimed the
  deployment certificate was disabled. The final surgical hardening exposes the
  backend certificate in the typed lane response, binds live-button enablement
  to that value, and renders the actual runtime state. The regression test
  supplies the exact phrase but never clicks dispatch.
- Final truth-hardening validation: Mandor resolved all five changed paths to
  the `workspace` domain; scoped Biome returned exit 0; the dashboard production
  build returned exit 0; all 57 dashboard files and 478 tests passed; the P6
  Python pack passed 31 tests; dependency-cruiser examined 168 modules and 467
  dependencies with zero violations.

Live media generation, provider submission and throughput certification remain
outside this mission's validation boundary.
