# ANTIGRAVITY — F2V Frames CDP Upload UAT (v4)

ROLE
- Live UAT engine only. Observe + report. No patch, no debug, no loop, no retry.
- Defects → escalate to Codex. One pass.

PURPOSE
- Prove the Phase 2 CDP file-chooser upload end-to-end: the step the previous UAT failed
  (`F2V_SOP_UPLOAD_CLICKED` → `ERR_F2V_UPLOAD_MEDIA_NOT_FOUND`) now goes through
  `chrome.debugger` file-chooser interception instead of a DOM "Upload media" scan.

PRECONDITION GATE STATUS (verified green at commit time)
- Clean pushed SHA: `1b2fd964f2df598e8c38864a21736b97d5c1d106`
  on branch `fix/mv3-message-port-lifecycle`.
- `node --check` (runner / background / content-flow-dom) ✅
- `py_compile agent/api/flow.py` ✅
- Frozen asset-picker harness 8/8 ✅
- Build id: `flowkit-f2v-runner-audit-2026-05-28b` (unchanged — the NEW stages
  `F2V_SOP_CDP_FILE_CHOOSER_ARMED/_FED` are the proof that the new code is live).

WAJIB SEBELUM RUN
- ⚠️ Operator must reload the unpacked extension to commit `1b2fd96` so Chrome runs the
  new background.js + runner. Confirm by the presence of `F2V_SOP_CDP_FILE_CHOOSER_ARMED`
  in telemetry — if that stage never appears, Chrome is running stale code → STOP, reload.
- Local agent on `127.0.0.1:8100` must be up (the new `/api/flow/materialize-local-file`
  endpoint + `/api/products/{id}/image` must respond).
- The job MUST set **`use_cdp_upload: true`** and carry a resolvable asset
  (`productId` or `startAsset` / `startImageMediaId`) so the background can fetch + materialize it.
- Generate stays gated: set `opts.skipGenerate = true`. No Generate click unless explicitly authorized.

UAT SCOPE — full F2V Frames via CDP upload, STOP before Generate
1. New project → settings (Video → Frames → 9:16 → 1x → Veo 3.1 Lite) → close panel.
2. Insert prompt.
3. CDP upload: runner ARMS interception, clicks the Start slot (opens native chooser),
   CDP feeds the materialized local file via `DOM.setFileInputFiles`.
4. STOP before Generate.

EXPECTED TELEMETRY (CDP upload lane — new stages in bold)
```
… (settings/panel/prompt stages as before, all PASS) …
F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT      PASS
F2V_SOP_PROMPT_INSERTED                   PASS
**F2V_SOP_CDP_FILE_CHOOSER_ARMED**        PASS   (slot=Start file=…)
F2V_SOP_START_CLICKED                     PASS
**F2V_SOP_CDP_FILE_CHOOSER_FED**          PASS   (file=… backendNodeId=…)
F2V_SOP_UPLOAD_CLICKED                    PASS   (strategy=cdp_file_chooser)
F2V_SOP_UPLOAD_WAIT_DONE                  PASS   (strategy=cdp_file_chooser)
F2V_SOP_GENERATE_SUBMITTED                SKIP   (opts.skipGenerate)
```

HARD RULES
- Stop at the FIRST failing stage. No retry, no patch.
- No `REQUEST_ID=N/A`, no `build=legacy`, no screenshot-only proof.
- Capture verbatim: the `F2V_SOP_CDP_FILE_CHOOSER_FED` payload (filePath + backendNodeId)
  and any `chrome.debugger` attach/detach + `DOM.setFileInputFiles` evidence.
- Known CDP failure codes to report as-is if they fire: `ERR_CDP_FILE_CHOOSER_TIMEOUT`,
  `ERR_CDP_FILE_CHOOSER_BACKEND_NODE_MISSING`, `ERR_CDP_DEBUGGER_DETACHED:*`,
  `ERR_CDP_UPLOAD_NO_ASSET`, `ERR_MATERIALIZE_ASSET_FAILED`, `ERR_BACKGROUND_ASSET_FETCH_FAILED`.

REQUIRED OUTPUT
- `REQUEST_ID`
- `COMMIT_SHA` (= `1b2fd964f2df598e8c38864a21736b97d5c1d106`)
- `FIRST_FAIL_STAGE` (or NONE)
- `FULL_FAIL_MESSAGE` (or NONE)
- raw telemetry-backed `PASS_STAGES`
- `ABSENT_STAGES`
- `CDP_FILE_CHOOSER_PROOF` (armed payload + fed payload: filePath, backendNodeId, attach/detach)
- `NEXT_DECISION`

NEXT_DECISION guidance
- All stages PASS through upload → CDP upload POC PROVEN. Recommend: authorize a single
  Generate run, and add End-frame upload (second slot) as the follow-up.
- Any CDP stage FAILs → report the exact error code; escalate to Codex. No second pass.
