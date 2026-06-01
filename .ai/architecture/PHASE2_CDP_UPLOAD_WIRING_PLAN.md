# Phase 2 CDP Upload — Wiring Plan (evidence-grounded)

**Status:** Phase 2 approved by operator. This documents the exact remaining work after a
full code trace. **Finding: every CDP building block already exists — the only gap is
runner orchestration, and proving it is live-only (chrome.debugger cannot be JSDOM-tested).**

## What already exists (cited)

| Piece | Location | State |
|---|---|---|
| `debugger` permission | `extension/manifest.json:6` | ✅ present |
| CDP arm + feed (`Page.setInterceptFileChooserDialog` → `Page.fileChooserOpened` → `DOM.setFileInputFiles`) | `extension/background.js:265` `beginCdpFileChooserProof(tabId, filePath, expectedFileName, slotLabel)` | ✅ complete |
| CDP wait | `extension/background.js:390` `waitForCdpFileChooserProof(tabId)` | ✅ complete |
| CDP message entry points | `background.js:2117` `FLOWKIT_CDP_BEGIN_FILE_CHOOSER_POC`, `:2126` `FLOWKIT_CDP_WAIT_FILE_CHOOSER_POC` | ✅ |
| Asset → **disk path** materialization | `agent/api/flow.py:385` `/api/flow/upload-image-base64` → returns `local_file_path` (temp staging) | ✅ exists |
| Runner already gets a CDP dep | `background.js:2310` passes `opts.cdpCoordinateClick` into the runner | ✅ pattern established |
| Runner upload step (the gap) | `extension/f2v-flow-queue-runner.js:2546` Step 11 uses DOM `_clickUploadMedia` | ❌ never calls CDP |

## Why the UAT failed (root cause, confirmed)
`F2V_SOP_START_CLICKED` (role=div) PASSED, then `_clickUploadMedia` found **no DOM "Upload
media" control** (14 main-page candidates). The Start-slot click opens a **native OS file
chooser** — there is no in-DOM button to click. `DOM.setFileInputFiles` needs a real disk
path. → `ERR_F2V_UPLOAD_MEDIA_NOT_FOUND`. This is exactly the failure `UPLOAD_STRATEGY_CDP.md`
predicts.

## The ordering constraint (the crux)
CDP interception MUST be **armed before the click that opens the chooser**. Since the
**Start-slot click is the chooser trigger**, the sequence must become:

```
resolve asset → disk path (POST /api/flow/upload-image-base64 → local_file_path)
→ beginCdpFileChooserProof(tabId, filePath, fileName, 'Start')   [ARM]
→ click the Start slot (the existing _clickStart target)          [OPENS CHOOSER]
→ waitForCdpFileChooserProof(tabId)                               [CDP FEEDS FILE]
→ verify Start-slot preview
```

This **reorders the proven `F2V_SOP_START_CLICKED` step** (arm must precede it). That is why
this cannot be a silent edit — it touches a frozen path and is validated live-only.

## Proposed implementation (scoped, opt-in, preserves proven path)
1. **Runner** (`f2v-flow-queue-runner.js`): add an opt-in branch gated on
   `opts.cdpFileChooserUpload`. When present, arm-before-Start: call the dep to
   `arm(tabId, slot, assetSource)`, click Start, `await` the dep's `wait(tabId)`, emit
   `F2V_SOP_UPLOAD_CLICKED` (`strategy=cdp_file_chooser`) + `F2V_SOP_UPLOAD_WAIT_DONE`.
   When absent → **unchanged** DOM `_clickUploadMedia` path (proven path frozen, default).
2. **Background** (`handleExecuteFlowJob`): provide `cdpFileChooserUpload` dep that
   (a) resolves `job.startAsset/productId/startImageMediaId` → disk path via the local
   agent, (b) `beginCdpFileChooserProof`, (c) returns control so runner clicks Start,
   (d) `waitForCdpFileChooserProof`. Detach always in finally.
3. **Telemetry:** new sub-stages `F2V_SOP_CDP_FILE_CHOOSER_ARMED`,
   `F2V_SOP_CDP_FILE_CHOOSER_FED` for raw proof in the UAT report.

## Validation reality
- `node --check` + frozen harness (8/8) — verifiable here. ✅ (the opt-in branch keeps them green)
- The actual CDP attach/feed — **live-only**; proven by a UAT run reporting
  `F2V_SOP_CDP_FILE_CHOOSER_ARMED/FED` + `DOM.setFileInputFiles` success. This IS the POC
  proof the Phase 2 prompt asks for ("report exact debugger attach/detach and file-chooser proof").

## Decision needed
The reorder + live-only validation means this is the boundary where the architecture reset
says: build the opt-in wiring, keep the proven path default, and validate via a single live
UAT — not by iterating live. Operator to choose: implement the opt-in wiring now (live-validated
next UAT), or hand this plan to Codex for the build.
