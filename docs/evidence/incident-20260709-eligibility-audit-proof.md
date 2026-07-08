# Incident 2026-07-09 — Eligibility Audit / Prompt Integrity: Proof Bundle

Branch `fix/traditional-herbal-oil-physics-class` (PR #287).
Backend under proof: commit `7c122568e6de0fb462b9e5c632550b22e1c50586`, pid 38344,
served bundle `index-DOx5RJCl.js`, 334 routes.

## 1. Route-table proof (live `/openapi.json` extract)

```text
/api/creative-asset-eligibility/audit          ['get']   <- PRIMARY (collision-proof prefix)
/api/creative-assets                           ['get', 'post']
/api/creative-assets/eligibility-audit         ['get']   <- legacy alias, order-pinned by test
/api/creative-assets/{asset_id}                ['get', 'patch']
/api/creative-assets/{asset_id}/archive        ['post']
/api/creative-assets/{asset_id}/download       ['get']
/api/creative-assets/{asset_id}/preview        ['get']
/api/creative-assets/{asset_id}/unarchive      ['post']
```

Regression test: `tests/api/test_creative_asset_api.py::test_eligibility_audit_url_never_hits_asset_detail_handler`
(asserts, for all 7 surfaces on BOTH URLs, HTTP 200, no `CREATIVE_ASSET_NOT_FOUND`,
and that the asset-detail handler records ZERO calls; then asserts the dynamic
`{asset_id}` route still resolves for a real id).

## 2. Version-proof endpoint (live JSON)

```json
{
  "pid": 38344,
  "process_started_at": "2026-07-08T18:52:21.682222+00:00",
  "git_head": "7c122568e6de0fb462b9e5c632550b22e1c50586",
  "git_branch": "fix/traditional-herbal-oil-physics-class",
  "route_count": 334,
  "critical_routes": {
    "/api/creative-asset-eligibility/audit": true,
    "/api/creative-assets/eligibility-audit": true,
    "/api/flow/execute-flow-job": true,
    "/api/flow/generate": true,
    "/api/workspace/execution-package": true
  },
  "dashboard_bundle": "index-DOx5RJCl.js",
  "source_stale_since_start": false,
  "stale_source_sample": []
}
```

Boot log: `2026-07-09 02:52:23,120 [INFO] agent.main: ROUTE_TABLE_OK 334 routes, all 5 critical routes registered`

## 3. Browser network proof (real served dashboard, Chrome DevTools capture)

```text
/operator/f2v:
  GET /api/local-agent/version-proof                                              [200]
  GET /api/creative-asset-eligibility/audit?surface=F2V_START_FRAME_PICKER&...    [200]
  GET /api/creative-asset-eligibility/audit?surface=F2V_END_FRAME_PICKER&...      [200]
/operator/hybrid:
  GET /api/creative-asset-eligibility/audit?surface=HYBRID_START_FRAME_PICKER&... [200]
  GET /api/creative-asset-eligibility/audit?surface=HYBRID_END_FRAME_PICKER&...   [200]
/operator/i2v:
  GET /api/creative-asset-eligibility/audit?surface=I2V_CHARACTER_PICKER&recipe_id=PRODUCT_HELD_BY_CHARACTER_IN_SCENE&... [200]
  GET /api/creative-asset-eligibility/audit?surface=I2V_SCENE_PICKER&...          [200]
  GET /api/creative-asset-eligibility/audit?surface=I2V_STYLE_PICKER&...          [200]
```

UI a11y snapshot excerpts (live): banner `backend 7c122568 (fix/traditional-herbal-oil-physics-class) · pid 38344 · bundle index-DOx5RJCl.js · 334 routes`;
audit chips `Library has 27 assets; 12 eligible for this surface; 9 excluded` with
reason chips `ROLE POOL 21 / PENDING APPROVAL 7 / PENDING-REJECTED 7 / WRONG SLOT 4 / ARCHIVED 4`;
style picker shows the distinct `Assets found but none eligible for this surface` state;
`Generate Final Prompt` rendered DISABLED with "requires fallback confirmation" and an
explicit `I understand and confirm fallback copy usage for this run.` checkbox.

## 4. Execution-package payload proof (no generation fired, zero credits)

Product: MWTCB `6483d624-a03d-4933-9bba-6ca2e5f7b6fd`. All requests sent with
`duration_seconds=8, aspect_ratio="9:16", model="Veo 3.1 - Lite"`.

| case | mode | source_mode | wep_id | snapshot | copy binding | resolved assets |
|---|---|---|---|---|---|---|
| T2V | T2V | T2V | `wep_34846eafa36b4dbb` | `pkg_fbdbcde44c5c9b46` | `selected_copy_set / BOUND / 1174cefb…` | (none — text-only, correct) |
| F2V | F2V | FRAMES | `wep_0c071b738acec14d` | `pkg_810e52af7628576b` | `selected_copy_set / BOUND / 1174cefb…` | `start_frame → product-image:6483d624…:start_frame` |
| HYBRID | F2V | HYBRID | `wep_e61005d3e09445ae` | `pkg_810e52af7628576b` | `selected_copy_set / BOUND / 66da3eef…` | `start_frame → product-image:6483d624…:start_frame` |
| I2V | I2V | INGREDIENTS | `wep_8f1700d52d381341` | `pkg_c436969938d5ee32` | `selected_copy_set / BOUND / 491f50cf…` | `subject → product-image:6483d624…` |
| FALLBACK (confirmed) | T2V | T2V | `wep_a1e57e0158a24dc8` | `pkg_fbdbcde44c5c9b46` | `landbank_fallback / NOT_SELECTED / None` | (none) |
| FALLBACK (unconfirmed) | T2V | T2V | — | — | **409 COPY_SET_FALLBACK_CONFIRMATION_REQUIRED** | — |

`image_media_ids` note: Flow media ids are assigned at job-execution upload time
(manual lane), not at packaging; the package carries the resolved asset slots
above. Historical proof of the executed order: `generation_result` row
`27a238d8…` (2026-07-08) records `reference_media_ids=["408678c4-…"]` for the
single-start-frame F2V run. LKG byte-baselines for T2V/I2V/HYBRID payloads:
**NOT VERIFIED** (no historical execution packages exist for those modes; the
settings columns for all 54 stored packages May 18 → Jul 8 are uniformly
`8s / 9:16 / Veo 3.1 - Lite`, which is the strongest available baseline).

## 5. Section 6 spoken-dialogue proof (three cases, compiled — no AI call)

1. **MWTCB, approved family-night set** (`1174cefb…`):
   `Anak anda menangis malam-malam, tak boleh tidur lena? Mungkin perut dia kembung atau berangin.`
   — approved copy verbatim; zero bank filler.
2. **MWTCB, avatar-specific set** (`66da3eef…`, worried-parent avatar angle):
   `Anak anda kerap menangis malam kerana perut kembung? Risau melihat si kecil tidak selesa dan sukar tidur lena?`
   — dialogue tracks the avatar-targeted copy angle.
3. **MWTCB, fallback (explicitly confirmed)** — labeled `landbank_fallback / NOT_SELECTED`:
   `Anak melalak pukul 2 pagi baru kau kalut nak cari minyak? Minyak hijau cap merah ni simpan siap-siap dalam laci bilik tidur.`
   — product landbank copy, clearly labeled, only reachable behind the 409 gate.

Golden tests: `test_bound_approved_copy_excludes_family_bank_filler` (the literal
"Botol dia tersusun / tak rasa hype" bank filler CANNOT appear when
`copy_source=selected_copy_set`) and `test_fallback_copy_still_gets_bank_support`.

## 6. F2V truth-source wording — before / after

**OLD (from the real Jul 8 run's stored prompt, `generation_result` row):**
> Use the uploaded finished frame as the **single visual reference**. Continue only from the visible frame state … Treat the uploade[d product reference image as the hard visual, geometry, and physical-scale truth source …]

**NEW (live compile, commit 7c12256):**
> **FRAME CONTINUITY SOURCE:** Use the uploaded finished frame only for presenter pose, scene continuity, lighting, camera distance, and motion continuation. Continue only from the visible frame state … **PRODUCT TRUTH SOURCE:** Any attached product reference image controls product identity, physical scale, cap, body, and label geometry, and label placement only. It must not reset the scene, replace the presenter, override the uploaded frame composition, or create a new shot.

Grep proof: `"single visual reference" in final_FRAMES prompt → False`.
Golden tests: `test_frames_composed_frame_is_scoped_continuity_truth`,
`test_frames_scopes_frame_continuity_vs_product_truth_sources`,
`test_frames_is_motion_delta_only_no_rebuild` (now asserts the old phrase is ABSENT).
Files: `agent/services/canonical_prompt_compiler.py` (S3 FRAMES branch),
`agent/authority/VIDEO_PROMPT_COMPILER_TEMPLATES.yaml`, `agent/authority/BOSMAX_CUSTOM_INSTRUCTION.txt`.

## 7. Source-lineage law proof

- `mode=FRAMES, source_mode unset` → lineage **FRAMES** (was: silent HYBRID).
- `mode=F2V, source_mode unset` → documented HYBRID product-anchor default (unchanged).
- `source_mode="FRAMSE"` (junk) → `SOURCE_MODE_INVALID` fail-closed at the preview
  boundary, inside the compiler, and in the F2V generation-package lane normalizer.
- Tests: `test_preview_source_mode_resolution_pins_caller_lineage`,
  `test_f2v_source_lane_normalizer_fails_closed_on_junk`,
  `test_explicit_frames_lineage_compiles_frames_branch`,
  `test_explicit_hybrid_lineage_compiles_hybrid_branch`,
  `test_unpinned_f2v_defaults_to_documented_hybrid_anchor`,
  `test_invalid_source_mode_fails_closed`.

## 8. Poster→video leakage matrix (independent read-only audit)

| # | Channel | Evidence | Changed in poster era? | Affects video? | Verdict |
|---|---------|----------|------------------------|----------------|---------|
| 1 | Video importing poster modules | 0 grep hits across canonical_prompt_compiler, ugc compiler, workspace pkg services, product_lock_builder, make_video, agent_video, flow.py; only agent/main.py mounts poster routers | No | No | CLEAN |
| 2 | Poster importing video utils | Read-only calls (crud, ProductTruthService, ai_copy brief helpers, copy grounding); zero module-state mutations / monkeypatching | Yes (imports added) | No | CLEAN |
| 3 | Shared DB tables/fields | Poster write sites: NONE (reads product + copy_set only); poster IMG output goes through one-door /api/flow/generate like any IMG job | No new writes | No | CLEAN |
| 4 | Copy banks / shared constants | POSTER_COPY_LIMITS + UNSAFE_CLAIM_TERMS imported only by poster modules; compiler S6/S8 banks self-contained; POSTER_RECIPES.yaml has 0 non-poster consumers | Poster-owned only | No | CLEAN |
| 5 | copy_set registry | Poster READS approved+non-archived sets only; never creates/approves; video binding fails closed on non-approved | No poster write path | No | CLEAN |
| 6 | Product metadata | Zero UPDATE/INSERT on product rows in all 10 poster files | No | No | CLEAN |
| 7 | Creative-asset flags | PRODUCT_POSTER lane forces allowed_modes=["IMG"], contains_rendered_text=True, approved_for_video_support=False (lane-derived, not caller-supplied); F2V/HYBRID gates: MODE + RENDERED_TEXT + APPROVED | Lane predates poster era | Only via deliberate operator mislabel | RISK (pre-existing; spawned hardening task) |
| 8 | Compiler utilities changed by poster PRs | git log over compiler/copy/truth services in poster window = EMPTY; PR #256 img settings refactor = byte-equivalent extraction; PR #281 = scripts/docs only | 2 no-op refactors | No | CLEAN |
| 9 | Avatar / copy-assist inputs | Poster reads grounding, returns to UI only; no writes to avatar/assist context | No | No | CLEAN |
| 10 | Runtime payload | Poster generate button posts mode:IMG to the one-door lane; video modes' payloads (this doc §4) carry no poster fields; compiled prompts contain zero poster tokens | — | No | CLEAN |

## 9. Test commands (final runs)

```text
pytest (touched+locked sweep, 21 files) ......... 394 passed  (pre-route-move)
pytest (post route+lineage sweep, 15 files) ..... 355 passed
pytest copy assist/grounding/caption/binding .... 44 passed
cd dashboard && npm run build ................... exit 0
cd dashboard && npx vitest run .................. exit 0 (full suite)
npx tsx scripts/mandor-check.ts ................. PASS domain=workspace paths=17
```
