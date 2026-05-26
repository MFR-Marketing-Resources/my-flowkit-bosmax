# MV3 Message Port Lifecycle — Runtime Proof Checklist

**Branch:** `fix/mv3-message-port-lifecycle`
**Patched files:** `extension/background.js`, `extension/content-flow-dom.js`, `extension/content.js`
**Test:** `node scripts/test-mv3-respond-async-timeout.js` — passes locally
**Authority:** `AGENTS.md` → `CHROME_EXTENSION_MV3_DEBUG_CONTRACT.md`

This checklist is **runtime UAT proof** that the static patch eliminates the
`Unchecked runtime.lastError: The message port closed before a response was
received.` console error. Claude Code cannot drive Chrome autonomously
(browser-tier MCP is read-only); the operator runs each scenario and reports
back.

> **Rule:** report each scenario as **PASS** (zero unchecked lastError) or
> **FAIL** (any unchecked lastError, even one). Screenshots optional.

---

## Pre-flight

- [ ] Local agent is up: `curl http://127.0.0.1:8100/health` returns `status: ok`
- [ ] Extension built/loaded fresh from this branch (no stale service worker)
- [ ] Chrome DevTools console visible for **each** target (extension service
      worker, side panel, dashboard iframe page)

To inspect each console:

| Target | How to open DevTools |
|---|---|
| Background service worker | `chrome://extensions/` → Flow Kit → "service worker" link |
| Side panel | Right-click inside the side panel → Inspect |
| Dashboard iframe | Right-click inside the iframe content → Inspect frame |
| Google Flow tab | F12 on `labs.google/fx/tools/flow*` |

---

## Scenario Matrix

### S1 — Side panel boot (cold)
1. Close any open Flow Kit side panel.
2. Click the extension action icon to open the side panel.
3. Watch all four consoles.

**PASS criteria:** zero `Unchecked runtime.lastError` in any console for 30s.

- [ ] Result: PASS / FAIL — note: __________

---

### S2 — `/operator?portal=side` load
1. Side panel open, select **Operator Dashboard** route.
2. Iframe loads `http://127.0.0.1:8100/operator?portal=side`.

**PASS criteria:** zero `Unchecked runtime.lastError` for 30s after iframe ready.

- [ ] Result: PASS / FAIL — note: __________

---

### S3 — F2V route load
1. In the side panel, navigate to the F2V module (dashboard route).
2. URL bar / iframe shows the F2V workspace.

**PASS criteria:** zero `Unchecked runtime.lastError` for 30s after route mount.
This is the exact scenario from the user-reported bug.

- [ ] Result: PASS / FAIL — note: __________

---

### S4 — Local agent offline
1. Stop local agent: `taskkill /F /IM python.exe` (or close the agent process)
2. With agent offline, open the side panel.
3. Confirm UI shows offline state.

**PASS criteria:** UI flips to offline, zero unchecked lastError. The new
`ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT` may appear in service worker logs after
4.5s if anything tries an async background call — that is **structured** and is
NOT an unchecked lastError.

- [ ] Result: PASS / FAIL — note: __________

---

### S5 — Background service worker reload
1. With agent running, side panel open.
2. Go to `chrome://extensions/`, click reload on Flow Kit.
3. Side panel may auto-disconnect; reopen it.

**PASS criteria:** after reload + reopen, zero unchecked lastError for 30s.

- [ ] Result: PASS / FAIL — note: __________

---

### S6 — `CHECK_FLOW_COMPOSER_READY` happy path
1. Open Google Flow tab, log in, get to the editor.
2. From the side panel preflight (or via console:
   `chrome.runtime.sendMessage({type:"CHECK_FLOW_COMPOSER_READY",mode:"F2V"}, console.log)`).

**PASS criteria:** response received within 4.5s; either `{ok:true,...}` or a
structured error. Zero unchecked lastError.

- [ ] Result: PASS / FAIL — note: __________

---

### S7 — Stale Flow tab
1. Open Google Flow tab.
2. While a readiness check is in flight, navigate the Flow tab away (or
   reload it).
3. Trigger another `CHECK_FLOW_COMPOSER_READY` or `RELOAD_FLOW_TAB`.

**PASS criteria:** structured error returned (one of:
`ERR_CONTENT_SCRIPT_STALE`, `ERR_TAB_RELOADED`, `ERR_NO_RECEIVER`,
`ERR_MESSAGE_RESPONSE_TIMEOUT`, or new
`ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT`). Zero unchecked lastError.

- [ ] Result: PASS / FAIL — note: __________

---

### S8 — `EXECUTE_FLOW_JOB` smoke ACK only
> **Do NOT trigger a real Generate.** This scenario validates the immediate
> ACK pattern only.

1. Send a smoke-mode job: from background console:
   ```js
   chrome.runtime.sendMessage({
     type: "EXECUTE_FLOW_JOB",
     job: { request_id: "smoke-test-1", mode: "F2V", smoke_test: true }
   }, (ack) => console.log("ACK:", ack))
   ```
2. Watch console for immediate ACK and later `FLOW_JOB_COMPLETED` /
   `FLOW_JOB_FAILED`.

**PASS criteria:** ACK arrives in < 100ms, `accepted:true`. No unchecked
lastError. Final status message lands later out-of-band.

- [ ] Result: PASS / FAIL — note: __________

---

### S9 — Background hang simulation (negative control)
> Optional. Confirms the timeout fires when a handler hangs.

1. Temporarily hack `handleCheckFlowComposerReady` to never resolve (or use
   the DevTools breakpoint approach).
2. Send `CHECK_FLOW_COMPOSER_READY`.

**PASS criteria:** at ~4.5s, response arrives with
`{ok:false, error:"ERR_BACKGROUND_ASYNC_RESPONSE_TIMEOUT", detail:"respondAsync exceeded 4500ms"}`.
Zero unchecked lastError.

- [ ] Result: PASS / FAIL / SKIPPED — note: __________

---

## Report-back

Paste back the matrix with PASS/FAIL marks. If any scenario FAILs, include:
- The exact unchecked-lastError line from the console
- The sender context (background SW, side panel, Flow tab)
- Any prior console line within 1s
