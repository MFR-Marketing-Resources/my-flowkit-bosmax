# HANDOFF → Codex: Google Flow media **retrieval** not saving/displaying

**Owner request:** debug + fix why generated **video/image renders in Google Flow but is never pulled back** into `THIS SESSION'S RESULTS`, the **Video Library**, and the **Image Library** — across **every** generation page (T2V, F2V, Hybrid, I2V, IMG, IMG Fastlane, IMG Cockpit, Poster Builder, Production Studio/P6).

**Owner:** farisdatosheikh. **Runtime:** :8100 canonical release, DB `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`.

---

## Problem statement
The media generates fine in Flow (owner visually confirmed a finished video), but nothing is retrieved → **no `generated_artifact` / output row is written**, so results + libraries stay empty. The FE sits at `Stage: checking for finished video (try N)` for minutes and never resolves.

## Already CONFIRMED — do NOT re-investigate or touch (Claude Code owns these; they work)
- **Generation pages + dispatch work.** Hybrid V4 guided shell now reaches Generate end-to-end (was short-wired; fixed in PR #725 + PR #727, live on :8100 as `607ffe5c`). "Prepare final prompt" builds `workspacePackage`; Generate button appears.
- **HYBRID lane is correct (NOT a collapse):** dispatch = `mode=F2V` + `source_lane=HYBRID` (verified in `workspace_generation_package`). The "F2V running" status is only a display mislabel (separate FE fix in flight on branch `fix/gen-result-labels-display`).
- **Fire dispatches + renders:** after the environment fixes below, the fire progressed `Submitting to Flow → negotiating (approve 1 video, Veo 3.1-Lite) → checking for finished video (try N)` with **no CAPTCHA**. So the failure is strictly the **retrieval AFTER a successful render.**

## The failure to fix
- Video renders in Flow, but retrieval never completes / never saves.
- **DB evidence:** after firing MWCB 8s, the only new row is `workspace_execution_package` (mode=F2V, product `6483d624`). **No `generated_artifact`, no request output, no retrieved row** — polled 5+ min. So the "collect finished media → persist artifact" step is not producing anything.

## Where to look (verify these — names from memory/observation, confirm in code)
1. **Retrieval core:** `agent/services/make_video.py` → `start_generate` and the finished-media polling ("checking for finished video", collect-all-N, pre-existing-media exclusion, periodic tab reload). This is the prime suspect — add telemetry to see whether the finished-media detection ever returns, and whether the persist step is reached.
2. **Extension transport (ADR-007: API-first, extension = authenticated transport, DOM lane DEAD):** how the finished media is detected/collected via the aisandbox relay and returned to the runtime. Check the extension's response path for the generated media id/URL.
3. **Persist + serve:** where retrieved media becomes a `generated_artifact` (+ `/api/flow/artifacts`, `/api/flow/retrieved/{media_id}`). Confirm the save is even attempted.
4. **Current-run lifecycle / retry cap:** the "try N" loop — max tries, timeout, and whether it silently stops vs errors. (`current run` lifecycle binding.)
5. **FE display (separate, in flight):** `THIS SESSION'S RESULTS` (ResultsSidebar) + the Video/Image Library pages — branch `fix/gen-result-labels-display` makes them video-aware + relabels. **Display-only — it does NOT unblock retrieval;** an artifact must be saved first.

## Environment gotchas (already hit + resolved during UAT — rule out, don't chase)
- Runtime restart (deploy) drops the extension WebSocket → `offline_reason=EXTENSION_DISCONNECTED`. Fix: reload the Flow Kit extension.
- Reloading the extension does NOT inject the content-script into already-open Flow tabs → `CAPTCHA_FAILED: Cannot access contents of the page`. Fix: refresh `labs.google/fx`. (manifest `host_permissions` for `labs.google/*` are correct.)
- The fire DID get past both — so retrieval failure is downstream of these.

## Repro
1. :8100 → Hybrid → select **Minyak Warisan Cap Burung** (`6483d624`) → Compile preview → **Prepare final prompt** → Confirm fallback → **▶ Generate 1 clip · 8s** → fire.
2. Ensure `labs.google/fx` tab open + warm + extension reloaded/refreshed (see gotchas).
3. Observe: renders in Flow; FE stuck at `checking for finished video (try N)`; `flow_agent.db` has no new artifact; results/library empty.

## Scope
Retrieval → persist → display for **both video AND image**, across **all** generation pages + the **Image Library** and **Video Library**.

## Constraints
Per `AGENTS.md` / `CLAUDE.md`: this is the **live Google Flow loop** — **Claude Code is forbidden from debugging it**, so it is handed to **Codex**. Obey harness/preflight/telemetry gates and the Codex report format (STATUS, changed files, validation results, full 40-char SHA, push target/result, NEXT_DECISION). No `REQUEST_ID=N/A`, no `build=legacy`.
