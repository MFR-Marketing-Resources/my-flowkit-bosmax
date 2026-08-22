# BOSMAX Video Live Certification — Round 2

Mission: Round 2 live lifecycle certification
Date opened: 2026-08-22 (Asia/Kuala_Lumpur)
Repository: `MFR-Marketing-Resources/my-flowkit-bosmax`
Mission-start `origin/main`: `0caaad6fb3c659ea67d03862bc710a0f8c25b636`
Historical Round-1 merge: `0caaad6fb3c659ea67d03862bc710a0f8c25b636`
Canonical runtime: `C:\Users\USER\Desktop\_bosmax_runtime\releases\0caaad6fb3c659ea67d03862bc710a0f8c25b636`
Canonical DB: `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`
Canonical dashboard bundle: `index-CS11jDi4.js`
Canonical extension: `C:\Users\USER\Desktop\_bosmax_runtime\releases\0caaad6fb3c659ea67d03862bc710a0f8c25b636\extension`

## Operating rules

- This is a sanitized evidence ledger. No cookies, authorization headers,
  reCAPTCHA tokens, session secrets, or API credentials may be written here.
- Every new provider submit requires a distinct certification objective and an
  immediate provider identity receipt.
- An uncertain submit is reconciled; it is never blindly resubmitted.
- `PASS` requires artifact-backed evidence, including bytes, SHA-256, measured
  duration, registration readback, and result/library identity where applicable.

## Pre-credit baseline

- Provider generation submits: **0**
- Google Flow calls for this Round-2 mission: **0**
- Runtime provenance: `RUNTIME_CANONICAL_OK`; runtime SHA equals `origin/main`;
  DB canonical/integrity gate pending final read-only receipt.
- Browser UAT health: `BROWSER_UAT_READY=true`, loopback CDP only, dedicated
  profile.
- Provider readiness at the initial preflight was **NOT_READY** —
  `OWNER_GOOGLE_FLOW_LOGIN_REQUIRED`; this historical blocker is retained below.
- Current provider readiness after owner login is **READY**:
  `FLOW_PROVIDER_UAT_READY=true`, `flow_auth_status=AUTHENTICATED`, Flow
  project `2c10c186-33d0-4c8e-b067-de1a8818a22`, transport bound, content script
  alive, session challenge verified, numeric credit balance `1068`, and no video
  job in flight. No provider operation has been submitted.
- Extension release path is the immutable canonical release path above. Its
  deterministic source tree is proven by the receipt below; it is not by itself
  a live provider proof.
- Provider-free proof already run: extension static checks, 22-case F2V asset
  harness, Flow readiness contract tests, Round-1 restart closure (16 tests),
  Native Extend core (55 tests).
- Current known provider-free watchlist: 17 curated Copy V2 failures and 7
  Montage fixture/authority failures; classification is recorded in the task
  report and must not be fixed unless it materially blocks the target path.

## Certification matrix

| Surface | 8s | 10s Omni Flash | 16s | 24s |
|---|---|---|---|---|
| Hybrid | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Faceless | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Montage | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |
| Production Studio / P6 | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |

Allowed cell states: `NOT_RUN`, `BLOCKED_PRE_PROVIDER`,
`PROVIDER_SUBMITTED`, `GENERATED_NOT_RETRIEVED`, `RETRIEVED_NOT_REGISTERED`,
`PASS`, `FAIL`.

## Provider operation accounting

| # | Case | Lane | Model | Duration | Reason / expected submits | Actual provider identity | Actual submits | Result |
|---:|---|---|---|---:|---|---|---:|---|
| 0 | Round-2 preflight | — | — | — | No provider operation authorized before readiness | — | 0 | PASS |

## Evidence entries

Append one dated entry per certification operation. Keep request/job/provider
identities, measured media evidence, registration/readback evidence, and
restart/reconnect observations together. Do not overwrite earlier entries.

### 2026-08-22 — pre-credit readiness

- Runtime readiness: canonical SHA and `origin/main` both
  `0caaad6fb3c659ea67d03862bc710a0f8c25b636`.
- Browser: Chrome `152.0.7977.42`, dedicated profile, CDP
  `http://127.0.0.1:9222`, loopback-only.
- Provider readiness result: `OWNER_GOOGLE_FLOW_LOGIN_REQUIRED`.
- No provider generation or credit spend occurred.

### 2026-08-22 — authenticated pre-credit readiness

- Canonical runtime receipt: `RUNTIME_CANONICAL_OK`; runtime, deployment, and
  `origin/main` SHA are all `0caaad6fb3c659ea67d03862bc710a0f8c25b636`;
  dashboard bundle `index-CS11jDi4.js`; canonical DB and bundle match verified.
- Extension provenance receipt: `COMMIT_TREE_DETERMINISTIC`; last extension
  commit `f9099c3bb9b4688d14538ab4479219865abaaa6e`; extension tree SHA-256
  `60be5c53e89c128b9049390316cd3d25eefe1b13dfb1a549499be5e45d1e932a`;
  16 files; clean.
- Dedicated UAT browser remains loopback-only with project tab and extension
  loaded. `FLOW_PROVIDER_UAT_READY=true`; auth is `AUTHENTICATED`, transport is
  connected/bound, the session challenge is verified, and the content script is
  alive. Project ID is `2c10c186-33d0-4c8e-b067-de1a8818a22`; extension ID is
  `ccocoknpemfoobjmmebefjpgepepoedl`; extension build matches
  `flowkit-canonical-dom-guard-2026-07-13a`. Session identifiers and secrets
  are intentionally omitted.
- Provider generation submits: `0`; Google Flow calls: `0`; credit spend:
  `0`. The gate is now clear for the explicitly authorized bounded canary.

### 2026-08-22 — remote provenance refresh before canary

- An unrelated remote merge landed after mission start: `origin/main` moved from
  the mission-start SHA `0caaad6fb3c659ea67d03862bc710a0f8c25b636` to
  `018e08a072794b41a03d7a95cdcf1748186d893b`. The canonical runtime was
  advanced to that exact already-merged SHA before any provider submit; no
  source changes were made for this refresh.
- Runtime receipt: `RUNTIME_CANONICAL_OK`, release SHA and deployment SHA
  `018e08a072794b41a03d7a95cdcf1748186d893b`, DB canonical, bundle matched,
  release clean, `source_stale=false`.
- Dedicated UAT Chrome was restarted with the matching immutable release
  extension. Final readiness: `FLOW_PROVIDER_UAT_READY=true`, project
  `9eb77338-c7db-42d1-b550-00287eeb3b06`, auth `AUTHENTICATED`, transport and
  content-script challenge bound, extension build matched, numeric balance
  `1068`, no active video job. Session identifiers are omitted.
- Provider generation submits remain `0`; Google Flow generation calls remain
  `0`; credit spend remains `0`.

### Planned operation 1 — bounded 8s Hybrid canary (pending submit)

- Objective: one `F2V` + `HYBRID` provider operation using the server-owned
  official AQUABLANCE visual, portrait `9:16`, default known 8s direct model,
  then prove poll → retrieve → artifact register → readback and restart-safe
  durable state. No retry or second submit is permitted.
- BOSMAX request ID: `bdc281b8-8d6f-4d11-932e-de131fde52c3`.
- Product authority: product
  `243bf466-8a42-40b3-a75b-e3068cc430f6`; V2 binding is active for the HYBRID
  and F2V consumers; official visual is locally downloaded and has a persisted
  Flow media identity.
- Expected provider submit count: exactly `1`; expected credit spend: one
  bounded 8s canary only. Current actual provider submit count: `0` pending the
  owner-authorized request.

### Operation 1 result — blocked before provider

- Request `bdc281b8-8d6f-4d11-932e-de131fde52c3` was rejected at the backend
  Copy V2 authority gate with `COPY_V2_TAXONOMY_AUTHORITY_STALE`.
- Evidence: request telemetry and stage events show first failure at
  `API_LANE_REJECTED`; no durable video job, `video_job_side_effect`, provider
  operation identity, artifact, or provider submit row was created. Provider
  generation submit count remains `0`; credit spend remains `0`.
- Root cause: AQUABLANCE binding blueprint fingerprint
  `728e3c1af62031b6cf89434af1fdf2383dce2bb1e24dd9c898684dea11347934` does not
  match current authority fingerprint
  `a7e29d5c6f4de2a3e91fb47ec59fe0320dd85ffbe90ad04d4cf32c71e2cd4cac`.
  The fail-closed behavior is retained; this is classified as
  `Hybrid/8s=BLOCKED_PRE_PROVIDER` for this product and is not counted as a
  provider failure.

### Planned operation 2 — bounded 8s Hybrid canary (pending submit)

- Objective remains exactly one `F2V` + `HYBRID` portrait 8s operation, now using
  the pre-existing product whose current V2 authority resolution is `READY`:
  product `6483d624-a03d-4933-9bba-6ca2e5f7b6fd` (Minyak Warisan Cap Burung
  25ml). The official visual will be uploaded only if the API-first transport
  requires it; no second generation submit is allowed.
- BOSMAX request ID: `7a99db61-630e-4df3-8f7d-2ce0bcecbf11`.
- Expected provider submit count: exactly `1`; current actual provider submit
  count remains `0`.

### Operation 2 result — blocked before provider

- Request `7a99db61-630e-4df3-8f7d-2ce0bcecbf11` returned HTTP `422` and was
  rejected by the product custody gate with `ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN`.
- This product is governed by the exact-product policy, while the bounded
  canary route is generative reference conditioning. The fail-closed result is
  correct; no provider operation, durable video job, side effect, artifact, or
  credit spend was created. Provider generation submit count remains `0`.

### Evidence-backed target-path remediation — AQUABLANCE V2 authority

- The original AQUABLANCE block was separately reconciled as a safe
  `SAFE_FINGERPRINT_ONLY_RECONCILIATION`: stored strategy fingerprint
  `284e71099ab27545ff299444ff58bc199ab04ba7da63e6b3c68b5aafbaf77a62` to
  current `27bc662bafc4fa9d7080289fb4e006a99b5321613f8e349d2d9dff4aa2eef04a`,
  with unchanged strategy binding, active registry, VERIFIED/READY provenance,
  and durable snapshot
  `.ai/audits/product-243-fingerprint-reconciliation-20260822.json`.
- The immutable V2 blueprint then required a new revision; the surgical
  revision `2` preserved every stage text and evidence reference and changed
  only Product Truth lineage. Old authority fingerprint
  `728e3c1af62031b6cf89434af1fdf2383dce2bb1e24dd9c898684dea11347934` was
  replaced by current `ad48adc19792359105ace17b27bef65090d4b2f7cb65427436eaedbd2cdd72c9`.
  The revision validated, received explicit closure approval, and activated
  all eight required lanes through the normal V2 service path.
- Post-remediation readback: HYBRID resolution `READY`, blueprint revision `2`;
  direct 8s route eligible; 10s remains intentionally
  `DIRECT_10S_CONTRACT_NOT_CERTIFIED`. No Google Flow call occurred during
  remediation.

### Planned operation 3 — bounded 8s Hybrid canary (pending submit)

- Objective: one `F2V` + `HYBRID` portrait 8s operation using the
  server-owned AQUABLANCE visual now backed by current V2 authority; then prove
  poll, retrieve, artifact registration/readback, and restart-safe durability.
- BOSMAX request ID: `e65d7b9f-9a6c-4e9b-a6d6-30f1dba7f2a4`.
- Product: `243bf466-8a42-40b3-a75b-e3068cc430f6`.
- Expected provider submit count: exactly `1`; no retry or second submit is
  permitted.

### Operation 3 result — PASS with restart/reconnect proof

- Request `e65d7b9f-9a6c-4e9b-a6d6-30f1dba7f2a4` was accepted through the
  API-first direct capture lane as one `F2V` + `HYBRID` portrait operation.
- Durable job: `g_9de948fa7d6c`; provider media target / operation identity:
  `d095d3de-c6b9-4e36-8bde-210988e856d7`; provider submit count `1`;
  provider resubmission `false`.
- Captured submit contract: RPC `r2v`, generation type
  `reference_frame_2_video`, aspect enum `VIDEO_ASPECT_RATIO_PORTRAIT`, model
  key `veo_3_1_r2v_fast_portrait`, tier `PAYGATE_TIER_ONE`, requested duration
  `8`, one reference, one output.
- Provider reached terminal success. Retrieval and local delivery succeeded:
  `2,215,257` bytes, SHA-256
  `44724a7f323ba90da9d7c4992acc65ad5bd0afd702bcf57051b2ff128144e3ad`, and
  measured duration `8.000000` seconds.
- `generated_artifact` registration and readback both succeeded; the Results
  Hub recovery endpoint, result detail, results list, and artifact/library
  list all resolve the same media identity and file. The canonical runtime
  database row is `DONE` with matching final media, path, SHA, and duration.
- After stopping and recreating the canonical backend and UAT browser, the
  same durable job remained `DONE`, retained the same artifact and file
  evidence, and still reported submit count `1`. Startup reconciliation
  recorded provider state `SUCCESS` with one persisted media handle and zero
  provider resubmissions. This proves restart/reconnect recovery for the
  accepted operation; product visual fidelity remains a separate human/QC
  review item and is not claimed here.
- Credit/provision accounting for this operation: one provider generation
  submit; the observed credit balance moved from `1068` to `1048`. No retry,
  arbitrary fallback, or second submit was performed.

### Remote/runtime drift after operation 3

- A subsequent unrelated remote merge advanced `origin/main` to
  `09e0515ece6a23257af2060394a103ec463a2273`. The canonical runtime was
  refreshed to that exact SHA before this next certification step; runtime,
  deployment, and `origin/main` match, the release is clean, and the dashboard
  bundle is `index-DyAEU1Bf.js`.
- UAT was restarted with the matching immutable extension release. Readiness is
  `FLOW_PROVIDER_UAT_READY=true`: authenticated, bound, build-matched, and no
  active video job. Session identifiers are intentionally omitted.

### Operation 4 result — blocked before provider

- Request `round2-omni10-20260822-01` was sent once through the manual
  wrapper, then failed at the persisted Copy V2 binding gate with
  `V2 BINDING REQUIRED`. Telemetry records `API_LANE_REJECTED`; no `g_` job,
  provider identity, artifact, or credit debit was observed.
- This was a BOSMAX pre-provider route failure, not a Google Flow failure. The
  request ID is closed and will not be replayed.

### Planned operation 5 — bounded Omni Flash 10s contract capture (pending submit)

- Objective: one provider-free-from-BOSMAX-contract perspective but explicitly
  owner-authorized live `T2V` operation using model `Omni Flash`, duration `10`,
  portrait `9:16`, count `1`, through the existing API-first conversational
  lane. Capture the approved SSE/tool identity, actual model/duration, terminal
  provider identity, retrieval, artifact registration/readback, and no-submit
  restart evidence. This is the minimum operation needed to promote the real
  Omni Flash 10s contract; it must not silently use the direct 8s route.
- BOSMAX request ID: `round2-omni10-20260822-02`.
- Expected provider submit count: exactly `1`; no retry or second submit is
  permitted. If the provider response is uncertain, stop and reconcile the
  persisted job instead of resubmitting.

### Operation 5 result — PASS for the real Omni Flash 10s contract

- Request `round2-omni10-20260822-02` was accepted once through
  `/api/flow/generate` on the API-first conversational lane as `T2V`, portrait
  `9:16`, count `1`, model `Omni Flash`, duration `10`.
- Approved SSE/provider contract: tool `generate_video_from_text`, model key
  `abra_t2v_10s`, `duration_used=10`, `model_ok=true`, `duration_ok=true`,
  `identity_captured=true`, and `gen_tool_matched=true`. The request did not
  fall through to the direct 8s reference route.
- Durable job `g_66f05d380d93` reached `DONE` and returned media
  `a462eea4-4fb3-4e30-8cab-00db0ff01323`. Output correlation matched the SSE
  generation identity and current project media; no second approve or submit
  occurred. The conversational contract exposes no separate batch operation
  handle, so the provider identity is the captured generation tool/model/
  response correlation plus the durable media result.
- Local artifact evidence: `2,618,997` bytes, SHA-256
  `49a6bb65a78f08898d2d3eac6d58ddc765b843973bd353938fd8b34fd09cfed9`, and
  measured duration `10.005000` seconds. `generated_artifact` registration,
  file readback, Results Hub recovery/detail, and `/api/flow/retrieved/{media}`
  all succeeded; the production ledger row is `DONE` with the same media, path,
  SHA, and `10.0` duration.
- Observed credit balance moved from `1048` to `1033` (15 credits, consistent
  with the current promo observation). This operation consumed exactly one
  authorized provider generation and no retry.

### Planned post-operation 5 restart/reconnect proof (no provider submit)

- Stop and recreate the canonical backend/UAT connection, then read the same
  durable job and Results Hub records. Expected: `DONE`, same media/file/SHA/
  duration, no new provider generation, no resubmission, and readiness green.
- This is a lifecycle proof only and does not authorize a new Google Flow call.

### Planned operation 6 — Native Extend 16s (one continuation submit)

- Source media/operation: `29b5572a-fb2e-4743-b705-3069aeec4d79`, project
  `9eb77338-c7db-42d1-b550-00287eeb3b06`, verified scene context recorded by
  the read-only resolver. The 16s plan is source block 1 plus one block-2
  Native Extend continuation.
- Dry-run proof: route executable, `veo_3_1_extension_lite`, planned operation
  count `1`, lineage `SOURCE_READY`, and no provider call.
- The approved manifest is the immutable two-item continuation authority for
  this source chain; live authorization is bound to this exact block-2 plan
  and count `1`. No retry or second submit is permitted.

### Operation 6 result — Native Extend 16s continuation PASS

- The one-shot authorization accepted exactly one planned operation. Native
  Extend returned `EXTEND_SUCCEEDED` for lineage
  `a2339209-bf10-4a2a-868f-fae9340df661`.
- Parent operation: `29b5572a-fb2e-4743-b705-3069aeec4d79`; child operation and
  primary media: `b7aa6275-e46b-41fd-963e-9d3f76ed108e`; child workflow:
  `2a9b9905-3573-4867-9c78-06db0829fc53`. The chain is source → child, with
  block 2 polled to provider terminal success and per-block `get_media`
  retrieval completed by the runtime. Durable lineage readback reports
  `EXTEND_SUCCEEDED`, the captured extension model, portrait aspect, frame
  window `1–24`, and the parent-aware idempotency key.
- The observed credit balance moved from `1033` to `1023`, consistent with one
  Native Extend operation. No second submit occurred. This proves the native
  16s block chain, but the current native Extend service stores per-block
  retrieval in lineage rather than inserting each child into
  `generated_artifact`; therefore this entry does not claim a registered final
  16s combined MP4 (the final-concat surface remains a separate certification
  concern).

### Planned operation 7 — Native Extend 24s (one new continuation submit)

- Reuse the already-succeeded block-2 lineage and dispatch only the new block 3
  against child `b7aa6275-e46b-41fd-963e-9d3f76ed108e`. The resume-aware dry run
  must report block 2 `needs_submit=false`, block 3 `needs_submit=true`, and
  planned operation count exactly `1`.
- Use the existing approved two-item manifest and one-shot authorization. No
  duplicate block-2 submit, retry, or final-concat submit is authorized in this
  operation.

### Operation 7 result — Native Extend 24s chain PASS

- Resume-aware live execution submitted only the new block 3 operation; the
  existing block 2 was returned as `EXTEND_SUCCEEDED` without resubmission.
- Block 3 lineage `713c76ea-a3ba-4791-bf63-1ca02f8ae868` is
  `EXTEND_SUCCEEDED`, parent child-2 media/operation
  `b7aa6275-e46b-41fd-963e-9d3f76ed108e`, child operation/primary media
  `2d70f206-e6f0-4ddb-a221-10dc14457bf4`, workflow
  `1632f696-5581-4560-a501-666d13eb789b`. The complete chain is source → block
  2 → block 3, with both continuation blocks polled terminal and retrieved by
  the native runtime.
- Credit balance moved from `1023` to `1013`: exactly one new Extend submit.
  No duplicate block-2 submit, retry, or final-concat submit occurred. As with
  operation 6, this proves the Native Extend chain and durable lineage, not a
  registered combined 24s MP4; final artifact registration is not performed by
  this per-block Extend runtime.

## Owner steer — taxonomy correction and Round-2 freeze (2026-08-22)

This append-only section supersedes the active-surface interpretation of the
earlier operation labels. The owner steer requires a complete freeze of new
paid Google Flow operations until the provider-free correction below is green.

### Freeze and accounting

- Status: `ROUND_2_PAID_OPS_FROZEN`; no provider submit, credit-spending call,
  UAT, push, or merge was performed after the owner steer.
- Branch under correction: `codex/video-lifecycle-round2`.
- Source SHA anchor: `0caaad6fb3c659ea67d03862bc710a0f8c25b636`; local correction
  commit: `04e541f83ef0f4328ef0a63c568e47dacb516275`. This commit is not pushed,
  merged, or deployed and is not a release/runtime claim.
- Total paid provider submits already consumed before the steer: **4**;
  observed credit movement `1068 -> 1013`, total **55 credits**. Post-steer
  paid submits: **0**. Google Flow generation calls for this closure: **0**.
- Operation 3 remains the only active-surface certification result: Hybrid 8s
  is `PASS` with one submit and one persisted provider identity.
- Operation 5 is reclassified as
  `OMNI_FLASH_10S_TRANSPORT_PROBE` / `B_INTERNAL_TRANSPORT`; its former
  transport `PASS` is removed from the active production matrix.
- Operations 6 and 7 are `B_INTERNAL_TRANSPORT` Native Extend lineage
  evidence. They have no registered combined final artifact and are not active
  16s/24s surface passes.

### Taxonomy audit

| Classification | Meaning | Audited occurrences and disposition |
|---|---|---|
| `A_ACTIVE_SURFACE` | Production surface identity | `HYBRID`, `FACELESS`, `MONTAGE`, and `PRODUCTION_STUDIO_P6` are the only active video lanes; these are persisted as `surface_lane` and shown as Hybrid, Faceless Video, Montage, and Production Studio / P6. |
| `B_INTERNAL_TRANSPORT` | Provider or implementation transport | `T2V`, `F2V`, `I2V`, `FRAMES`, `INGREDIENTS`, and `native_extend` remain in API contracts, compiler routing, scheduler payloads, and diagnostic metadata only. The new four-field provenance tuple separates these from `surface_lane`. |
| `C_LEGACY_COMPATIBILITY` | Dormant route/package/history compatibility | `dashboard/src/App.tsx` retains old `/operator/t2v`, `/operator/f2v`, and `/operator/i2v` definitions only behind deactivation filtering and explicit redirects to `/operator/hybrid`; old package/manual evidence remains reachable as internal documentation, not active navigation. |
| `D_WRONG_USER_FACING_TAXONOMY` | A production result or active navigation using a transport name as its primary surface | The corrected paths were `agent/api/results.py`, `dashboard/src/pages/ResultsHubPage.tsx`, `dashboard/src/pages/LibraryPage.tsx`, and the durable artifact/result/job writers. They now use `surface_label`/`surface_lane` first and expose transport only as secondary diagnostics. |

The remaining old strings found in `dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx`,
`dashboard/src/components/operator/OperatorManual.tsx`, and the mode helper
branches in `dashboard/src/pages/OperatorPage.tsx` are classified B/C because
they describe dormant package/transport compatibility or evidence. They are
not used as active Library/Results primary labels or active video navigation.
Native Extend is likewise an internal architecture path and has no matrix row.

### Corrected active production matrix

Only active surfaces are listed; columns are the owner-required duration
contract. Internal transport evidence is deliberately excluded.

| Active surface | 8s | 10s Omni Flash | 16s | 24s |
|---|---|---|---|---|
| Hybrid | `PASS` (operation 3) | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` |
| Faceless Video | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` |
| Montage | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` |
| Production Studio / P6 | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` | `NOT_RUN` |

The prior Omni Flash 10s row is not a PASS cell. A future Hybrid 10s test must
originate from the Hybrid surface, carry `surface_lane=HYBRID`, and use the
reference-aware Omni contract. It remains unauthorized until this correction
is green.

### Provider-free correction contract and evidence

The correction persists the following fields on new video jobs, generation
results, and generated artifacts:

`surface_lane`, `transport_mode`, `source_mode`, and
`provider_generation_type`.

The provider-free required tests are covered by the following files:

1. `dashboard/src/deactivatedSurfaces.test.ts` and
   `dashboard/src/App.navigation.test.tsx` — old route redirects/deactivation,
   active nav inclusion, and exclusion of Text to Video/Frames/Ingredients.
2. `tests/unit/test_video_surface_provenance.py` and
   `tests/api/test_results_api.py` — surface-vs-transport provenance,
   Hybrid-with-internal-F2V display, Montage internal reference display, P6
   Production Studio display, and no false remap of untyped legacy rows.
3. `tests/ui/test_artifact_library_page_ui_contract.py` — new Library video
   artifacts use active surface labels as the primary label.
4. `dashboard/src/utils/videoSurfaceProvenance.test.ts` — dashboard label
   normalisation and active-surface contract.

The dashboard build and targeted provider-free suites passed for the correction.
Known unrelated baseline failures remain outside this correction: the exact
17 curated Copy V2 fixture failures, two Montage fixture-drift assertions, the
P6 `copy_set` setup/fixture failures, and the pre-existing image-library Malay
contract mismatch. None represents a paid Hybrid/Faceless/Montage/P6 execution
failure, and no unrelated Copy V2 fixture repair is included.

Exact curated 17 failure inventory and live-surface intersection:

1. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_creates_and_pins_project_when_no_editor_open` — Copy V2 pre-provider; no active live execution.
2. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_materializes_remote_url_only_package_asset` — Copy V2 pre-provider; no active live execution.
3. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_resolves_i2v_refs_aspect_and_model` — internal I2V transport contract; no active live execution.
4. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_reuses_open_editor_without_minting` — Copy V2 pre-provider; no active live execution.
5. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_f2v_end_frame_reaches_flow_in_order` — internal F2V transport contract; no active live execution.
6. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_blocks_t2v_with_any_reference` — internal T2V transport contract; no active live execution.
7. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_blocks_i2v_with_fewer_than_two_refs` — internal I2V transport contract; no active live execution.
8. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_hybrid_is_exactly_one_product_image` — Hybrid-adjacent contract only; fails pre-provider and does not intersect paid/live execution.
9. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_blocks_f2v_with_more_than_two_refs` — internal F2V transport contract; no active live execution.
10. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_i2v_three_refs_preserve_slot_order` — internal I2V transport contract; no active live execution.
11. `tests/unit/test_manual_lane_reroute.py::test_manual_lane_rejects_client_source_mode_contradicting_package` — Copy V2 pre-provider; no active live execution.
12. `tests/api/test_generate_validation.py::test_duration_without_model_returns_422` — API validation pre-provider; no active live execution.
13. `tests/api/test_generate_validation.py::test_unknown_model_returns_422` — API validation pre-provider; no active live execution.
14. `tests/api/test_generate_validation.py::test_quality_4s_returns_422` — API validation pre-provider; no active live execution.
15. `tests/api/test_generate_validation.py::test_generate_resolves_refs_payload_contract` — Copy V2 pre-provider; no active live execution.
16. `tests/api/test_generate_validation.py::test_generate_busy_response_preserves_error_and_exposes_active_job` — Copy V2 pre-provider; no active live execution.
17. `tests/api/test_generate_validation.py::test_generate_blocks_stale_creator_byline_package_before_provider` — Copy V2 pre-provider; no active live execution.

### Next paid operation decision

- Exact next paid operation: **NONE AUTHORIZED**.
- Proposed operation after owner approval and a green correction/release gate:
  one Hybrid-surface, reference-aware Omni Flash 10s canary, exactly one
  provider submit, solely to fill the corrected Hybrid/10s active matrix cell.
  It must prove the persisted provider identity, poll/retrieve/register path,
  and zero resubmission after restart. No credit may be spent before the
  correction is green and the operation is explicitly authorized.
- Extension provenance is deterministic in the existing preflight receipt:
  extension commit `f9099c3bb9b4688d14538ab4479219865abaaa6e`, tree SHA-256
  `60be5c53e89c128b9049390316cd3d25eefe1b13dfb1a549499be5e45d1e932a`,
  16 files, clean. This is provenance evidence only; no readiness claim is
  made here.

`ROUND_1_COMPLETE` and `READY_FOR_ROUND_2_LIVE_CERTIFICATION` are not declared
by this correction entry.
