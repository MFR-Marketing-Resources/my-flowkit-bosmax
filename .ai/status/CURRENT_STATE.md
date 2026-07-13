# CURRENT_STATE

Last updated: 2026-07-02 (post PR #167). This file is the FIRST thing every
agent reads. If anything here conflicts with an older doc, THIS FILE and
ADR-007 win.

## Current Repo Head
- Verify live from Git (`git rev-parse HEAD` / `origin/main`); this file never
  self-declares a current SHA.

## VIDEO_EXTENSION_FINAL_SEAL (CLOSED — do not reopen)
- **Status: CLOSED.** All four modes (T2V / HYBRID / F2V / I2V) are live-proven
  end-to-end plus ONE shared full 16-second chain (initial → Native Extend →
  server concat). No more generation, Extend, concat or live proof is required.
- **Functional closure authority:** PR #334 (feature `a7618879…`, merged
  `acb95e5dd7ab16c1f1a7f1c85bebea515b20198d`). Start any new work from that merged
  main SHA (or later), never from historical audit branches.
- **Documentation closure authority:** the evidence-seal PR (this task) +
  `docs/evidence/video_extension_all_modes_golden_path_closure.sanitized.json`
  (the durable source of truth for the ledger, provenance, validation and tests).
- **Root cause (fixed, do not re-audit):** the FIRST Extend in a fresh project must
  bootstrap its Flow scene from the clip's `workflow_id`; that id is only in the
  media status poll (`check_video_status_by_media`), not `get_media`, and
  `createScene` re-issues the timeline `primaryMediaId`. Repaired surgically in
  `agent/api/flow.py` (`_ensure_scene_membership` captures the workflow id + adopts
  the scene's canonical member; `_map_lane_to_identity` and `POST /video-jobs` use
  it). `NATIVE_EXTEND_ENABLED=1` persisted in `.env`.
- **Final artifact:** `final_vj_25ca81841930` — 16.0s, 15,040,996 bytes, SHA-256
  `a58c96ab42b705a80bc0e484802ecd302fa23af32271642d69797f9ca52677fb`, retrieved via
  `/api/flow/retrieved/final_vj_25ca81841930` (byte-match). Golden lineage: harvest
  `780fb967` → workflow `6d159659` → scene `2accf53a` → parent `ce53dda4` → child
  `aeddefd1` → concat job `…/jobs/b2bb63cb-…`.
- **Credit truth:** 1530 → 1460 (−70). 4 modes CERTIFIED ≠ 4 new final-round
  initials: the final closure round submitted **3** new initials (T2V/F2V/I2V) and
  **reused/adopted** the HYBRID initial (`780fb967`); the −70 also covers 2 pre-fix
  failures (T2V provider render-fail, durable HYBRID scene-unresolved). 0 uncertain
  operations. Full itemised ledger is in the evidence JSON.
- **Runtime invariants:** API-first only; `NATIVE_EXTEND_ENABLED=1` (from `.env`);
  the durable source of truth is the DB (`video_production_job`, `video_job_side_effect`,
  `extend_lineage`, `generated_artifact`) + the evidence JSON + `output/retrieved/*.mp4`.
- **Regression-entry procedure (the ONLY way to reopen):** (1) reproduce on canonical
  main; (2) record the exact current job + provider identity; (3) diff against this
  evidence; (4) prove a NEW regression; (5) patch only that newly-proven defect;
  (6) never repeat the four-mode certification unless the shared downstream
  extend/concat architecture itself changes (it is source-mode-agnostic — zero
  `source_mode` branches).
- **Continuation note:** Codex, Hermes Agent, Cursor, Antigravity and future Claude
  sessions must treat this module as CLOSED. Do not restart historical audit work.
  New work must begin from the merged canonical SHA and be scoped to a newly
  reproduced defect. Check the existing final artifact and evidence BEFORE spending
  any credits.

## THE ONE ARCHITECTURE (ADR-007 — final, do not relitigate)
- Generation is **API-first**. The Chrome extension is **authenticated
  transport only** (session, reCAPTCHA, fetch relay, harvest). There is NO
  DOM-clicking generation lane anymore.
- Google Flow's live UI is Omni/V2: no Video/Frames tabs, no Start/End slot
  clicking, no settings-panel clicking. Any code or doc that assumes those is
  describing a DEAD UI.
- The one door: dashboard modules (F2V/T2V/I2V/IMG) → POST
  `/api/flow/execute-flow-job` → `_run_manual_job_via_generate` →
  `make_video.start_generate` → flowCreationAgent negotiation → render →
  retrieval → `generated_artifact` library. Programmatic callers may use
  POST `/api/flow/generate` directly.

## PROVEN AND LOCKED (as of PRs #160–#167, all merged to main)
Do NOT "improve", refactor, or re-debug these unless a listed harness FAILS:
1. **Stack-overflow fix**: `collectFlowPageStateDiagnostic` must NEVER call
   `collectProjectCreationState` (mutual recursion killed the renderer).
2. **Listener re-injection guard** in content-flow-dom.js (last injection wins).
3. **GFV2 root-shell rejection** (`root_shell_no_project`) — a non-/project/
   tab never gets editor authority.
4. **Manual lane hardening** (`agent/api/flow.py`):
   - every image slot (startAsset + refs.subject/scene/style/image) resolves
     via: live UUID validation (pre-credits) → self-heal re-upload → local file
     upload → remote downloadUrl materialize+upload;
   - composite BOSMAX asset ids (`product-image:<uuid>:start_frame`) are NOT
     Flow media ids (`_FLOW_MEDIA_UUID_RE` gate);
   - project self-provision when no editor is open (API_PROJECT_CREATED);
   - telemetry bridge → request rows resolve COMPLETED/FAILED.
5. **USER SETTINGS ARE LAW**: aspect|aspectRatio|orientation, count (1–4,
   negotiated AND retrieved in full), duration_s (validated), model ui_label
   (strict — unknown model FAILS CLOSED with ERR_UNKNOWN_MODEL, never a silent
   downgrade). Telemetry stage `API_USER_SETTINGS_APPLIED` records what ran.
6. **Negotiation brain** (`agent_video.py`): cap-gate (num_videos == user
   count, cost ≤ ceiling×count), approve exactly once, post-approve
   model+duration verification, failure-reply knowledge
   (REFERENCE_IMAGE_MISSING → re-upload, NEVER bare "regenerate";
   RENDER_FAILED → safe resubmit), zero-credit render-status probe.
7. **Retrieval**: pre-poll snapshot excludes pre-existing media (false-DONE
   fix); periodic bound-tab reload (Omni/V2 DOM never live-updates); collects
   ALL `count` videos; honest partial on shortfall.
8. **Model registry** (`video_models.py`): Omni Flash's internal engine name is
   `abra` (fired tool `abra_r2v_10s`, captured live) — alias is load-bearing.
9. **Artifact library**: `generated_artifact` table; every DONE registers its
   files; GET `/api/flow/artifacts`; dashboard Library gallery + inline
   completed-video player (`/api/flow/retrieved/{media_id}`).
10. **Telemetry one-way contract**: `sendRuntimeMessageNoThrow` has NO callback
    (frozen harness gate).

## VALIDATION GATES (run before ANY commit touching these areas)
- `node --check extension/background.js extension/content-flow-dom.js`
- `node scripts/test-f2v-asset-picker-modal.js` (frozen harness, 22 cases)
- `python -m pytest tests/unit/test_manual_lane_reroute.py
  tests/unit/test_make_video_binding.py tests/unit/test_agent_video.py
  tests/api/test_generate_validation.py
  tests/ui/test_extension_side_panel_ui_contract.py -q` (85 tests)
- Dashboard changes: `cd dashboard && npm run build` must be clean, then the
  agent serves `dashboard/dist` (restart agent after backend edits — it has NO
  --reload).
- Live-payload rule: never claim a dashboard lane works without firing the
  VERBATIM frontend payload (BOSMAX_DEBUG OPERATOR_EXECUTE_PAYLOAD from the
  browser console) at the endpoint.

## LIVE-PROVEN ARTIFACTS (2026-07-02, one night)
IMG jpg 0.52MB · I2V mp4 1.51MB (2 refs) · T2V mp4 2.15MB · F2V multiple mp4s
including the operator's own frontend clicks — all fully automatic
end-to-end. 2× Omni Flash 16:9 proposal approved and fired (settings fidelity
proven at the negotiation level).

## OPEN ITEMS (the ONLY things left — do not invent others)
1. Count=2 full-auto retrieval live confirm: unit-locked
   (`test_retrieval_collects_user_count_videos`); the live confirm run hit
   Google's rate limiter. ONE re-run after cool-down completes it.
2. Google rate limiter awareness: many generations in a row → 403 "reCAPTCHA
   evaluation failed / PUBLIC_ERROR_UNUSUAL_ACTIVITY" (pre-approve, 0
   credits). Cool down 1–2h; do NOT hammer retries.
3. Second Omni video from job g_385ad916534f is still in Flow project
   b33fe1c7 (recoverable via /api/flow/harvest-video after the first is
   excluded, or manually from the Flow UI).
4. Pre-existing failing unit suites (batch_planner / result_handler /
   product_catalog — DB/fixture issues, unrelated to generation) — separate
   task, do not mix with generation work.
5. T2V post-approve model verification: the text-only generation tool name is
   not yet in `_GEN_TOOLS`, so T2V jobs report model UNVERIFIED (flagged, not
   failed). Add the tool name after one captured approved-SSE.

## FORBIDDEN (unchanged + reinforced)
- No repairs inside frozen DOM-lane code (content-flow-dom DOM-driving lanes,
  f2v-flow-queue-runner) except deletion or a crash blocking the API lane.
- No live Google Flow debugging loops; recovery endpoints only
  (reload-extension / reload-flow-tab, body `{}`, Content-Type json).
- No credit-spending generation without explicit user approval.
- No "DONE"/video claims without the retrieved file's bytes verified.
- Don't fix what is not broken; if all gates above pass, the generation
  system IS working — look elsewhere for the bug.

## Historical Verified Checkpoints (kept for archaeology)
- Architecture-reset checkpoint: `26e327e11a48c30ccbbb350f3042f041f0c7df34`
- Harness commit: `81e78719e4f5281d77986dfe9c091681de31b954`
- ADR-007 landing (DOM wiring dead): PR #160 merge `fdb9128`
- Production settings fidelity + library: PR #167 merge `2c7a229`
