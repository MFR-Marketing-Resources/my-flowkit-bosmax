# PR #339 / #340 / #341 — Canonical Reference Authority Regression Closure

Mission: BOSMAX-VIDEO-PR337-PR338-REGRESSION-FULL-DELIVERY-2026-07-13
Date: 2026-07-13 · Starting main: `b5f1020888ee5398135b781738e203311590ef1f`
Final main: `3fa64d08cd1333cd66e75dd9a0440535355eb0c9` · Runtime :8100 serves final SHA (version-proof, `source_stale_since_start=false`).

## Reproduced defects (all live/code-proven on canonical main before patching)

1. **HYBRID automatic product-anchor destroyed (PR#338)** — `_bind_f2v_reference_assets`
   raised `HYBRID_EXACTLY_ONE_PRODUCT_REFERENCE_REQUIRED` without a manual
   `PRODUCT_REFERENCE` pick, although the approved package already resolves the
   product image into the `start_frame` slot. Live DB: pickable PRODUCT_REFERENCE
   rows existed for only 3/28 products (2 of them `media_id=NULL`).
2. **FRAMES server-truth gap** — start-frame requirement was UI-only; API callers
   could compile FRAMES with the raw product image silently standing in.
3. **No ownership / media-identity / rendered-text checks** in the binder
   (cross-product leakage possible; no-media picks produced plan-incapable packages).
4. **Stale binding state** — all six reference ids sent for every mode; never
   cleared on mode/product switch (F2V→HYBRID always 409).
5. **Package-id collision** — reference bindings were not part of the `wep_` id;
   re-create with different refs silently replaced resolved assets under an
   already-planned job (live-reproduced: BLOCKED re-create reused the READY job).
6. **Plan gate gap** — `plan_job` ignored `execution_allowed`; a BLOCKED package
   (missing required I2V recipe role) minted a complete plan (live: 200 not 422).
7. **Extend aspect mapping (surfaced by the repaired flow)** — job carried the
   package aspect `"9:16"`; `EXTEND_VIDEO_MODELS` is keyed by the captured enum →
   `EXTEND_FAILED / EXTEND_UNSUPPORTED_MODEL:9:16` (fail-closed, 0 credits).
   PR#334's golden job had `aspect_ratio=NULL` (runtime default applied) — never exposed.
8. **retry_safety=SAFE never honoured** — the failed extend's side-effect row held
   the idempotency key forever; resume returned without retrying (job stuck
   AUTHORIZED/"Preparing video").

## Fixes (merged)

- **PR #339** (`cc804e2e…`, merge `92c62b47…`): HYBRID anchor fallback (manual pick =
  override), FRAMES start REQUIRED server-side, WRONG_PRODUCT + MEDIA_IDENTITY_MISSING +
  rendered-text parity in the binder, asset fingerprints in the `wep_` id, plan-time
  `execution_package_execution_allowed` gate, role-aware UI guard + stale-binding reset +
  per-mode payload hygiene, picker product-scoping + no-media options disabled.
- **PR #340** (merge `fa166b6a…`): orchestrator maps `9:16/16:9/1:1` → captured Extend
  enum at its boundary; enum passes through; unknown still fails closed.
- **PR #341** (merge `3fa64d08…`): a provably zero-side-effect extend row
  (NOT_ATTEMPTED + SAFE + no operation_ref) is the ONE retryable state under a fresh
  single-use authorization; UNCERTAIN/SUBMITTED stay non-retryable.

## Validation

- Backend: focused suites 60 passed; frozen gate 107 passed; orchestrator suite 26
  passed (incl. new safe-retry + aspect-enum tests).
- Frontend: OperatorPage suites 41 passed incl. new `OperatorPage.referenceBinding.test.ts`.
- `verify-gate.ps1`: DASHBOARD_BUILD PASS · DASHBOARD_VITEST PASS · BACKEND_PYTEST_SMOKE
  PASS; mandor-check PASS in clean worktrees (paths=8 / 2 / 2).
- **Zero-credit matrix 12/12 (isolated :8123, real DB, 0 credits):** HYBRID auto-anchor
  package+plan (exactly one ref) · T2V zero-ref plan · FRAMES missing-start 409 ·
  FRAMES ordered start+end plan · cross-product 409 WRONG_PRODUCT,MEDIA_IDENTITY_MISSING ·
  I2V recipe-role plan (3 refs) · BLOCKED I2V plan → 422
  `INCOMPLETE_PRODUCTION_PLAN: execution_package_execution_allowed`.
- **DOM guard (post-merge, :8100, extension connected):** POST /api/flow/execute-flow-job
  `{source_mode:"HYBRID"}` → 422 `ERR_CANONICAL_MODE_LEGACY_DOM_ROUTE_FORBIDDEN`. No
  canonical mode dispatches EXECUTE_FLOW_JOB.
- **Post-merge real-browser validation (:8100 dashboard):** HYBRID package loaded and
  persisted with NO manual pick (`wep_ef3f3433ce465a0d`, then `wep_8a656fc3bf21b25f`
  with approved Copy Set); F2V pickers start*/end-optional; I2V character*/scene*/style
  optional; T2V no binding surface.

## Paid HYBRID 16s actual-user chain (final acceptance)

- Initiated from the dashboard Full Video control (plan → confirm dialog listing
  1 initial + 1 extend + 1 final render → Confirm & generate).
- Job `vj_2502426e7791` · logical key `ljk_6571a576b42c70e15f621a3e` ·
  package `wep_8a656fc3bf21b25f` · product `6483d624-a03d-4933-9bba-6ca2e5f7b6fd`
  (Minyak Warisan Tok Cap Burung 25ml) · project `cf0cf5ed-4762-46d2-ad6f-077358881b44` ·
  scene `770fc16b-8c82-4c28-b68d-0076c0d7a679` · initial_source_mode HYBRID.
- Initial (8s): media `1902fea3-9556-4437-8b1c-c744f7432a1c` (raw gen `a7a4c543…`,
  scene-adopted copy — the two project-gallery cards are the SAME clip),
  model `veo_3_1_r2v_lite`, seed 932411, ONE submit.
- Extend (8s): child `6b1ef7dc-4e49-4906-bdfd-7eef27f56db5`, lineage
  `EXTEND_SUCCEEDED` parent `1902fea3…` block_position 1, same scene. ONE provider
  submit (effective_submit_count=2: first attempt was the fail-closed NOT_ATTEMPTED).
- Concat: `projects/365941595420/locations/us-east1/jobs/0dfc8a47-bb69-478e-8437-0f4a3c619912`
  (runVideoFxConcatenation), ONE submit.
- Final artifact: `final_vj_2502426e7791` · **16.000000s** (ffprobe) ·
  **15,015,497 bytes** · SHA-256
  `85cf546d85e552b49d6fb66363f852ce8f8692a58d43198453c07bba4cfa43fe` ·
  retrieved byte-exact via `/api/flow/retrieved/final_vj_2502426e7791`.
- Credit ledger: 1450 → 1440 (initial, 10) → 1430 (extend, 10); concat free.
  Total 20 credits, zero waste (both fail-closed failures spent nothing).
- Side effects: INITIAL ×1 TERMINAL · EXTEND ×1 provider submit TERMINAL ·
  CONCAT ×1 TERMINAL — no duplicate provider side effects, no uncontrolled retry.

## Known non-blockers (parked, not regressions of this mission)

- `credit_balance_before/after` columns on side effects are NULL (ledger proven via
  /api/flow/credits polling instead).
- I2V character assets registered with `engine_slot_eligibility=["subject"]` don't
  match recipe slot mapping (`scene`); unrestricted (`[]`) avatar rows work. Data/recipe
  alignment is a follow-up.
- Extension recovery: `reload-extension` during a pending RELOAD_FLOW_TAB killed the
  MV3 worker until the Owner manually revived it; clean runtime restarts reconnect in ~10s.
