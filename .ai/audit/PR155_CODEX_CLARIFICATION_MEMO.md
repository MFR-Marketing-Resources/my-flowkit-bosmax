# PR155 Codex Clarification Memo

repo: `farisdatosheikh/my-flowkit-bosmax`
audit branch: `audit/pr155-extension-runtime-forensic`
parent audit commit sha: `4b23af629125a389812852dfdd81463c15303ebe`
main sha: `0f8ec23425171473a029cc5184c1a57b2f59638c`
feature sha: `66d6bf7faf38b7da5156e338f7fb451271d7fa03`
merge-base: `cd7c898cc3cbc15d31adc0724220933927a9cbdf`
date/time: `2026-07-01T02:33:30.6428124+08:00`
auditor: `Codex`
scope: `Second-round clarification memo for PR155 extension runtime unit`
status: `temporary audit artifact, not production documentation`

## 1. BG7 exact conceptual merge strategy

BG7 Strategy:
- structural base:
  - FEATURE `handleExecuteFlowJob` and FEATURE `handleGfv2Job` remain the structural base.
  - reason: they own the GFV2 lane, API-first runtime assumptions, `GET_RUNTIME_SELF_TEST`, strict target recovery, and runner integration. MAIN does not.
- RESOLVE_LOCAL_ASSET placement:
  - keep one top-level fetch implementation function: `resolveLocalAssetViaBackgroundProxy(msg)`.
  - place the detached ACK/result runtime message branch in `chrome.runtime.onMessage`, outside `handleExecuteFlowJob`, outside `handleGfv2Job`, and outside generic `handleMessage`.
  - keep the branch ahead of the generic `respondAsync(sendResponse, async () => handleMessage(...))` fallback.
- auto-open/create-project recovery placement:
  - preserve MAIN-style auto-open/create-project recovery only for the non-GFV2 path.
  - use it as a helper/fallback inside generic execution or generic readiness, not inside `handleGfv2Job`.
  - do not run it before GFV2 execution if `isGfv2Lane(job)` is true.
  - do not let GFV2 readiness failure fall through into generic auto-open recovery; GFV2 keeps its own surface acquisition rules.
- double-execution guard:
  - `handleExecuteFlowJob` must branch in this order:
    - if `isGfv2Lane(job)`: return `handleGfv2Job(job)`
    - else generic path
  - `RESOLVE_LOCAL_ASSET` must have exactly one runtime message branch that sends the immediate ACK and later emits the detached result.
  - generic `handleMessage` must not also own the same caller-visible `RESOLVE_LOCAL_ASSET` path.
  - the special-case listener must `sendResponse(ack)` and `return false` immediately, then do async fetch in `setTimeout(..., 0)`.
- must-preserve symbols:
  - FEATURE base:
    - `handleExecuteFlowJob`
    - `handleGfv2Job`
    - `captureGoogleFlowV2Readiness`
    - `handleRuntimeSelfTest`
    - `buildBackgroundStatusResponse`
    - `sendTabMessageSafe`
    - `respondAsync`
    - `ensureFlowDomScript`
    - `pingFlowDomScript`
  - MAIN graft:
    - `isRecoverableFlowDomBridgeError`
    - `reloadAndReinjectFlowDomContext`
    - `ensureFreshFlowDomContext`
    - detached `RESOLVE_LOCAL_ASSET` listener branch
    - detached `RESOLVE_LOCAL_ASSET_RESULT` sender
    - `resolveLocalAssetViaBackgroundProxy(msg)` as the single fetch implementation
- no-go patterns:
  - putting `RESOLVE_LOCAL_ASSET` inside `handleExecuteFlowJob`
  - letting both `handleMessage(msg.type === "RESOLVE_LOCAL_ASSET")` and `chrome.runtime.onMessage` special-case branch serve the same content caller
  - letting GFV2 lane fall through into generic recovery after partial execution
  - grafting `ensureFreshFlowDomContext` without `reloadAndReinjectFlowDomContext` and `isRecoverableFlowDomBridgeError`
  - broad “MAIN over FEATURE” replacement of `background.js`
- confidence:
  - `High`

## 2. CFD4 exact RESOLVE_LOCAL_ASSET contract

CFD4 Contract:
- content-flow-dom caller:
  - `resolveLocalAssetViaBackgroundProxy(...)`
- background handler:
  - top-level `chrome.runtime.onMessage` special-case branch for `message.type === "RESOLVE_LOCAL_ASSET"`
  - branch delegates actual fetch to `resolveLocalAssetViaBackgroundProxy(msg)`
- message type:
  - request: `RESOLVE_LOCAL_ASSET`
  - detached result: `RESOLVE_LOCAL_ASSET_RESULT`
- ACK pattern:
  - content sends `RESOLVE_LOCAL_ASSET` with `assetId`, `filename`, `request_id`, `proxy_request_id`
  - background immediately replies with synchronous ACK:
    - `{ ok: true, accepted: true, proxy_request_id }`
  - content verifies `accepted === true` and exact `proxy_request_id` match
- result pattern:
  - background performs async fetch after ACK
  - background emits detached message back to originating tab/frame:
    - `type: "RESOLVE_LOCAL_ASSET_RESULT"`
    - same `proxy_request_id`
    - success or failure payload
  - content waits on runtime message listener for that detached result, not the ACK body
- response shape:
  - ACK:
    - `{ ok: true, accepted: true, proxy_request_id }`
  - success result:
    - `{ type: "RESOLVE_LOCAL_ASSET_RESULT", proxy_request_id, ok: true, dataUrl, mimeType, filename }`
  - failure result:
    - `{ type: "RESOLVE_LOCAL_ASSET_RESULT", proxy_request_id, ok: false, error, detail, filename? }`
  - timeout on content side:
    - `ERR_PROXY_MESSAGE_TIMEOUT`
- harness expectation:
  - MAIN harness explicitly tests:
    - immediate ACK round-trip
    - detached `RESOLVE_LOCAL_ASSET_RESULT` success round-trip
    - detached timeout failure
    - detached failure round-trip from background
  - it also expects the helper to be exported in `window.__FLOWKIT_TEST_HOOKS__`
- allowed wrapper? yes/no:
  - `no`
  - clarification: PR155 should not use FEATURE’s generic `sendRuntimeMessageWithResponse(...)` as the visible CFD4 path. The path should stay the dedicated proxy helper contract, because the harness and detached-result semantics depend on it.
- no-go patterns:
  - treating the ACK body as the final file payload
  - deleting `RESOLVE_LOCAL_ASSET_RESULT`
  - keeping only `sendRuntimeMessageWithResponse({ type: 'RESOLVE_LOCAL_ASSET' })` with single-response semantics
  - hiding the proxy helper from `__FLOWKIT_TEST_HOOKS__`
  - weakening timeout to generic runtime timeout instead of detached proxy timeout
- confidence:
  - `High`

## 3. Harness interpretation

Harness Clarification:
- modify harness? yes/no:
  - `no`
- target main harness? yes/no:
  - `yes`
- feature harness relevance:
  - relevant only as evidence of what FEATURE currently self-tests, not as the governing PR155 spec
  - useful as a regression clue, not as merge authority
- conflict winner:
  - MAIN harness wins
- non-negotiable gate:
  - `node scripts/test-f2v-asset-picker-modal.js` unchanged must pass before PR155 is mergeable
- confidence:
  - `High`

## 4. Live zero-credit bind-check checklist

Live Zero-Credit Bind-Check:
- prerequisites:
  - unpacked extension build from the PR155 implementation branch only
  - local agent running
  - real Google Flow editor tab available
  - Chrome service worker console open
  - no dashboard-triggered job run
  - no `/api/flow/generate`
- steps:
  - 1. Load the unpacked extension and confirm the service worker starts cleanly.
  - 2. Open side panel and confirm it can read background status via `STATUS` / runtime diagnostics.
  - 3. Run background self-test only:
    - `GET_RUNTIME_SELF_TEST`
    - first with `attempt_open_project=false`
    - then only if needed with `attempt_open_project=true`
  - 4. Confirm the Flow tab has content script injected:
    - `FLOWKIT_DIAGNOSTIC_PING`
    - matching `content_build_id`
    - `runtime_ready=true`
  - 5. Confirm `CHECK_FLOW_COMPOSER_READY` returns:
    - `ui_contract_v2`
    - `editor_capability_ready`
    - `pre_generate_ready`
    - `background_build_id`
    - build match / runtime-ready fields
  - 6. Confirm stale-tab recovery:
    - use a deliberately stale or reloaded Flow tab state
    - rerun readiness/self-test
    - confirm recovery goes through `ensureFreshFlowDomContext` semantics and returns healthy diagnostics instead of `ERR_NO_RECEIVER` / stale-context failure
  - 7. Confirm GFV2 readiness fields:
    - `GFV2_OBSERVE_STATE`
    - `captureGoogleFlowV2Readiness`
    - expected diagnostic/evaluation payloads
  - 8. Confirm `RESOLVE_LOCAL_ASSET` detached ACK/result path without generation:
    - trigger only the asset-proxy contract against a known local asset
    - capture synchronous ACK
    - capture detached `RESOLVE_LOCAL_ASSET_RESULT`
    - do not run full job execution
  - 9. Confirm no `EDITOR_TAB_LOST` or target rebound regression in self-test/readiness results.
  - 10. Confirm no network request to `/api/flow/generate`, no Generate click, and no approve/render action occurred.
- expected pass signals:
  - self-test returns `ok: true` or narrow expected non-fatal readiness state only
  - matching background/content build IDs or approved `legacy-compatible` fallback only
  - side panel sees runtime and extension as connected
  - `CHECK_FLOW_COMPOSER_READY` returns required fields
  - stale tab rebinds without permanent receiver-loss error
  - GFV2 readiness payload exists and is internally coherent
  - asset proxy shows ACK then detached result with matching `proxy_request_id`
  - no `EDITOR_TAB_LOST`
  - no generation request
- forbidden actions:
  - Generate click
  - approve/render click
  - `/api/flow/generate`
  - full job execution
  - anything that spends credits
- fail conditions:
  - stale recovery still degrades to raw `ERR_NO_RECEIVER` / invalidated context without recovery
  - missing `ui_contract_v2` / `editor_capability_ready` / `pre_generate_ready`
  - ACK/result path collapses into one response or no detached result
  - `EDITOR_TAB_LOST` regression
  - build mismatch without explicit allowed fallback
  - any generation network call
- logs/artifacts to capture:
  - service worker console lines
  - self-test JSON result
  - `CHECK_FLOW_COMPOSER_READY` JSON result
  - GFV2 readiness JSON result
  - ACK payload and detached `RESOLVE_LOCAL_ASSET_RESULT`
  - network proof showing no `/api/flow/generate`
- confidence:
  - `Medium-High`

## 5. Implementation contract inputs

Implementation Contract Inputs:
- rules:
  - use FEATURE as structural base for `background.js` and `content-flow-dom.js`
  - graft only the audited MAIN seams
  - no broad rewrites
  - no selector-registry edits
  - no test weakening
  - no live validation during implementation
- approved scope:
  - `extension/background.js`
  - `extension/content-flow-dom.js`
  - `extension/manifest.json`
  - `extension/content.js`
  - `extension/injected.js`
  - `extension/f2v-flow-queue-runner.js`
  - `extension/gfv2-readiness.js`
  - `extension/popup.html`
  - `extension/popup.js`
  - `extension/side_panel.html`
  - `extension/side_panel.js`
- forbidden scope:
  - `extension/selector-registry.js`
  - `agent/*`
  - `dashboard/*`
  - `docs/*`
  - `.ai/*` except audit-only artifacts if explicitly requested
  - `.claudeignore`
  - `HERMES.md`
  - `tests/api/*`
  - `tests/unit/*`
  - `tests/ui/*`
  - `scripts/test-f2v-cdp-file-chooser-poc.js`
  - `scripts/test-f2v-playwright-persistent-context.js`
  - `scripts/test-f2v-asset-picker-modal.js`
- must-preserve:
  - FEATURE:
    - `handleExecuteFlowJob`
    - `handleGfv2Job`
    - `captureGoogleFlowV2Readiness`
    - `handleRuntimeSelfTest`
    - `sendTabMessageSafe`
    - `buildBackgroundStatusResponse`
    - `ui_contract_v2`
    - `editor_capability_ready`
    - `pre_generate_ready`
    - `__GFV2_READINESS__`
    - `GFV2_OBSERVE_STATE`
    - `GFV2_DISCOVER_SETTINGS`
    - `GFV2_APPLY_SETTINGS`
    - `GET_CAPTCHA`
    - `FLOWKIT_CAPTCHA_PING`
    - manifest load order: `content.js`, `selector-registry.js`, `gfv2-readiness.js`, `content-flow-dom.js`
    - manifest main-world injection of `injected.js`
  - MAIN graft:
    - `isRecoverableFlowDomBridgeError`
    - `reloadAndReinjectFlowDomContext`
    - `ensureFreshFlowDomContext`
    - `resolveLocalAssetViaBackgroundProxy(...)` helper in content script
    - background detached `RESOLVE_LOCAL_ASSET` ACK branch
    - detached `RESOLVE_LOCAL_ASSET_RESULT`
    - harness-exported test hooks:
      - `findElementByText`
      - `isSelectedControl`
      - `getRequiredAssetSlots`
      - `sendRuntimeMessageNoThrow`
      - `resolveLocalAssetViaBackgroundProxy`
  - safety outcomes:
    - `ERR_START_FRAME_REQUIRED_MISSING`
    - `ERR_ASPECT_9_16_NOT_SELECTED`
    - `ERR_COUNT_1X_NOT_SELECTED`
- decisions:
  - FEATURE background/content files are the base
  - MAIN stale recovery is mandatory
  - MAIN detached CFD4 proxy contract is mandatory
  - MAIN harness is authoritative
  - non-GFV2 generic recovery may preserve auto-open/create-project fallback
  - GFV2 must not fall through into generic auto-open recovery
  - `legacy-compatible` background-build fallback remains allowed if runtime is otherwise healthy
- validation:
  - `node --check extension/background.js`
  - `node --check extension/content-flow-dom.js`
  - `node --check extension/side_panel.js`
  - `node --check extension/popup.js`
  - `node --check extension/f2v-flow-queue-runner.js`
  - `node --check extension/gfv2-readiness.js`
  - `node --check extension/content.js`
  - `node --check extension/injected.js`
  - `node --check extension/selector-registry.js`
  - manifest JSON parse
  - `node scripts/test-f2v-asset-picker-modal.js` unchanged
- no-go:
  - dual `RESOLVE_LOCAL_ASSET` execution paths
  - deleting detached `RESOLVE_LOCAL_ASSET_RESULT`
  - replacing FEATURE base wholesale with MAIN
  - deleting GFV2 readiness fields or CAPTCHA bridge
  - editing harness to make feature drift pass
  - touching selector-registry or non-approved tests
- definition of done:
  - only approved files changed
  - static gates pass
  - MAIN harness passes unchanged
  - audit decisions above are reflected in code shape
  - branch is pushed with full SHA proof
  - live zero-credit bind-check is ready to run later, not executed during implementation

## 6. Final recommendation

Can ChatGPT now write the PR #155 Implementation Contract for Claude Code?
- `yes`

If conditional, list the remaining conditions.
- `none beyond preserving the clarified decisions verbatim`

Should Claude Code implement after receiving the contract?
- `conditional`

Main risk that must remain visible:
- `BG7 merge-shape failure: duplicating or misplacing RESOLVE_LOCAL_ASSET handling while grafting stale-recovery into the FEATURE background base`
