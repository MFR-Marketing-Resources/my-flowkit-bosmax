# CODEX PHASE 2: CDP Upload Proof Of Concept (evidence-grounded)

> ⚠️ GATED: This prompt is execution-ready but **must not be run until the operator
> explicitly approves entering Phase 2** (`UPLOAD_STRATEGY_CDP.md` §Scope Boundary:
> "No CDP implementation is authorized until the Phase 2 prompt is approved").

ROLE
- You are Codex acting as MV3 background-orchestrator engineer.

READ FIRST
- `AGENTS.md`
- `.ai/status/CURRENT_STATE.md`
- `.ai/architecture/UPLOAD_STRATEGY_CDP.md`
- `.ai/contracts/CODEX_IMPLEMENTATION_CONTRACT.md`
- `docs/google-flow/F2V_FRAMES_VIDEO_STEP_BY_STEP_MANUAL_v1.md`

## LIVE EVIDENCE THAT TRIGGERS THIS PHASE (one-shot UAT, 2026-06-01)
- REQUEST_ID: `live-ac56b95e-942e-4d4e-bdc6-82f643f61b5b`
- COMMIT_SHA: `d1f31677590664849a0b129f777143dd2ce19d65` (HEAD `0b132d1`)
- Build verified live (not legacy): `flowkit-f2v-runner-audit-2026-05-28b`
- **PASS through 19 stages** — settings → panel-close → prompt → Start are PROVEN GREEN:
  - `F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT` = `{"action":"pill_closed_pass1","editor_ce":["true"]}` ✅
  - `F2V_SOP_PROMPT_INSERTED` (inserted_length=1982) ✅
  - `F2V_SOP_START_CLICKED` role=`div` ✅
- **FIRST_FAIL_STAGE:** `F2V_SOP_UPLOAD_CLICKED` → `ERR_F2V_UPLOAD_MEDIA_NOT_FOUND`
- Failure detail: after the Start slot click (role=div), the scan for a DOM control
  labelled "Upload media"/"Upload"/"Upload from device" found **nothing**; it surfaced 14
  main-page candidates ("New project", "Flow Help Center", …) — i.e. **no in-DOM upload
  menu/button exists at that point**. Strong signal: the Start-slot click opens a **native
  OS file chooser** (hidden `<input type=file>`), which a content-script DOM scan can never
  click. This is exactly the failure `UPLOAD_STRATEGY_CDP.md` predicts.

## OBJECTIVE
- Build the approved CDP upload proof of concept in the extension production path so the
  Start/End frame upload completes without DOM file-object manipulation.

## STEP 0 — CONFIRM THE FAILURE MODE FIRST (cheap, do before building)
- Instrument: attach `chrome.debugger` to the Flow tab, `Page.enable`, then programmatically
  click the **Start slot** (the same element that produced `F2V_SOP_START_CLICKED role=div`).
- Observe whether a `Page.fileChooserOpened` event fires.
  - **If yes** → confirmed native file chooser → proceed with the CDP plan below.
  - **If no** → the Start-slot `div` is the wrong target / an intermediate "Upload media"
    menu item is required first. STOP and report; do NOT build CDP on a wrong assumption.
- Record this as `FILE_CHOOSER_PROBE` in the final report.

## CDP PLAN (only if Step 0 confirms native chooser)
1. **Manifest:** add the `"debugger"` permission (and document the new permission in the PR).
2. **Background service worker owns CDP** (content script CANNOT use chrome.debugger):
   - `chrome.debugger.attach({tabId}, "1.3")`
   - `Page.enable`, then `Page.setInterceptFileChooserDialog({ enabled: true })`
   - On `Page.fileChooserOpened` → resolve the local asset and feed it via
     `DOM.setFileInputFiles({ files:[absPath], backendNodeId })` (use the event's backendNodeId).
   - Always `chrome.debugger.detach` in a finally-block; report attach/detach timing.
3. **Content script role (per UPLOAD_STRATEGY_CDP.md — do NOT exceed):**
   - Trigger the visible Start-slot control to OPEN the chooser.
   - Observe modal/slot state; verify Start-slot preview after the file lands.
   - **No `input.files` assignment, no DataTransfer drag-drop simulation.**
4. **Background ↔ content bridge:** this is the `resolveLocalAssetViaBackgroundProxy` lane.
   A spec for it is preserved in `git stash@{0}` ("PRESERVE: divergent phase1c/2 asset-picker
   test spec") — `git stash show -p stash@{0}` to recover the intended test contract and
   wire the harness to it.

## DO NOT
- Do not reopen tactical DOM upload fallbacks as the primary strategy.
- Do not use Antigravity as the validation harness.
- Do not click Generate unless explicitly authorized.
- Do not touch the proven, live-validated paths (Video/Frames/9:16/1x/Veo verify, panel
  close, prompt insert, Start click) — they are frozen and green.

## REQUIRED WORK
1. Keep the work scoped to the approved CDP lane.
2. Preserve proven mode/config/prompt/start paths.
3. **Add local harness proof before any live UAT handoff** — extend
   `scripts/test-f2v-asset-picker-modal.js` (recover the stashed contract) to cover the
   background-proxy resolve + file-chooser interception path, deterministically (JSDOM/mocks).
4. Report exact debugger attach/detach and file-chooser proof.

## FINAL REPORT
- `STATUS`
- `FILE_CHOOSER_PROBE` (Step 0 result: native chooser yes/no + evidence)
- `FILES_CHANGED`
- `VALIDATION_RESULTS` (incl. `node --check` + the extended harness, all green)
- `COMMIT_SHA` (full 40-char)
- `PUSH_STATUS`
- `NEXT_DECISION`
