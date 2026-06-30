# PR155 Codex Forensic Audit

repo: `farisdatosheikh/my-flowkit-bosmax`
audit branch: `audit/pr155-extension-runtime-forensic`
audit commit sha: `Recorded in Git metadata after commit; see final delivery proof`
main sha: `0f8ec23425171473a029cc5184c1a57b2f59638c`
feature sha: `66d6bf7faf38b7da5156e338f7fb451271d7fa03`
merge-base: `cd7c898cc3cbc15d31adc0724220933927a9cbdf`
date/time: `2026-07-01T02:17:58.0761566+08:00`
auditor: `Codex`
scope: `Read-only forensic audit for planned PR #155 extension runtime unit`
status: `temporary audit artifact, not production documentation`

## Executive Decision Summary

- merge recommendation: `HOLD`
- implementation recommendation: `CONDITIONAL`
- top blockers:
  - `background.js` is missing MAIN stale-content recovery (`ensureFreshFlowDomContext`, `reloadAndReinjectFlowDomContext`, `isRecoverableFlowDomBridgeError`) while FEATURE adds new routing and self-test layers around the same bridge.
  - `content-flow-dom.js` FEATURE branch is not aligned to the current harness/spec for detached asset proxy ACK/result handling.
  - FEATURE branch reduced the harness instead of satisfying MAIN's expanded contract.
- required decisions:
  - adopt MAIN asset-proxy ACK/result contract unchanged as the authoritative CFD4 spec.
  - graft MAIN stale-content recovery into FEATURE runtime without collapsing the GFV2 lane into generic recovery logic.
  - keep MAIN harness unchanged and require FEATURE code to adapt to it.

## Verified Refs

- `git fetch origin` completed successfully.
- `git rev-parse origin/main` => `0f8ec23425171473a029cc5184c1a57b2f59638c`
- `git rev-parse origin/feat/gfv2-runner-upload-settings-prompt` => `66d6bf7faf38b7da5156e338f7fb451271d7fa03`
- `git merge-base origin/main origin/feat/gfv2-runner-upload-settings-prompt` => `cd7c898cc3cbc15d31adc0724220933927a9cbdf`
- `git ls-remote origin refs/heads/main` => `0f8ec23425171473a029cc5184c1a57b2f59638c`
- `git ls-remote origin refs/heads/feat/gfv2-runner-upload-settings-prompt` => `66d6bf7faf38b7da5156e338f7fb451271d7fa03`

## Scope Verification

### Approved files changed on FEATURE since merge-base

- `extension/background.js`
- `extension/content-flow-dom.js`
- `extension/content.js`
- `extension/f2v-flow-queue-runner.js`
- `extension/gfv2-readiness.js`
- `extension/injected.js`
- `extension/manifest.json`
- `extension/popup.html`
- `extension/popup.js`
- `extension/side_panel.html`
- `extension/side_panel.js`

### Conflicted overlap with MAIN

- `extension/background.js`
- `extension/content-flow-dom.js`
- `extension/manifest.json`
- `extension/popup.html`
- `extension/popup.js`
- `extension/side_panel.html`
- `extension/side_panel.js`

### FEATURE-only changed files

- `extension/content.js`
- `extension/f2v-flow-queue-runner.js`
- `extension/gfv2-readiness.js`
- `extension/injected.js`

### Safe net-new files

- `extension/f2v-flow-queue-runner.js`
- `extension/gfv2-readiness.js`

### Required runtime files for PR155 correctness

- `extension/background.js`
- `extension/content-flow-dom.js`
- `extension/manifest.json`
- `extension/content.js`
- `extension/injected.js`
- `extension/f2v-flow-queue-runner.js`
- `extension/gfv2-readiness.js`

### Approved but not core-execution-critical

- `extension/popup.html`
- `extension/popup.js`
- `extension/side_panel.html`
- `extension/side_panel.js`

These four files participate in runtime diagnostics and operator surfaces, but they are not the execution-critical seam for BG7/CFD4.

### Excluded files

- `extension/selector-registry.js`
- `agent/*`
- `dashboard/*`
- `docs/*`
- `.ai/*`
- `.claudeignore`
- `HERMES.md`
- `Fastmoss/product-registration files`
- `tests/api/*`
- `tests/unit/*`
- `tests/ui/*`
- `scripts/test-f2v-cdp-file-chooser-poc.js`
- `scripts/test-f2v-playwright-persistent-context.js`

### Selector Registry Verdict

- `extension/selector-registry.js` is unchanged between merge-base and FEATURE.
- `extension/selector-registry.js` is unchanged between MAIN and FEATURE.
- exclusion verdict: `KEEP EXCLUDED`

## Background.js Findings

### Stale recovery

MAIN has a three-part stale-bridge recovery seam:

- `isRecoverableFlowDomBridgeError`
- `reloadAndReinjectFlowDomContext`
- `ensureFreshFlowDomContext`

FEATURE does not contain those symbols. FEATURE still does ad hoc `ensureFlowDomScript` plus `pingFlowDomScript` plus one retry in scattered call sites. That is weaker than MAIN because it does not reload the tab when the content script context is invalidated.

Verdict:

- `ensureFreshFlowDomContext` should be grafted into FEATURE.
- it can safely coexist with `ensureFlowDomScript` and `pingFlowDomScript` because it is a wrapper over them, not a replacement transport.
- the correct merge shape is to centralize stale recovery through `ensureFreshFlowDomContext` for generic tab-execution paths, not to sprinkle more ad hoc reinjection retries.

### GFV2 routing

FEATURE adds:

- `handleGfv2Job`
- `captureGoogleFlowV2Readiness`
- `handleRuntimeSelfTest`
- `GET_RUNTIME_SELF_TEST`
- imported `f2v-flow-queue-runner.js`
- imported `gfv2-readiness.js`

This lane is materially coupled to FEATURE-only runtime fields and diagnostic handlers. Replacing FEATURE background logic with MAIN would destroy the GFV2 lane.

Verdict:

- preserve FEATURE GFV2 lane.
- do not let generic stale recovery or generic auto-open recovery wrap the GFV2 early-return lane.
- `handleExecuteFlowJob` must continue to branch to `handleGfv2Job(job)` before generic target recovery.

### BG7 structural risk

The unresolved structural problem is real. MAIN and FEATURE place related logic in different scopes:

- MAIN has detached `RESOLVE_LOCAL_ASSET` ACK/result listener handling in `chrome.runtime.onMessage`.
- FEATURE has direct `RESOLVE_LOCAL_ASSET` handling in `handleMessage`.
- FEATURE adds new `GET_RUNTIME_SELF_TEST`, bootstrap, runner, and strict target recovery layers around the same background worker.

Conceptual resolution:

- keep a single fetch implementation function: `resolveLocalAssetViaBackgroundProxy(msg)`.
- keep the detached ACK/result branch in `chrome.runtime.onMessage`, not in the generic `handleMessage` path.
- keep the direct helper callable from internal/background code without going through runtime messaging.
- ensure the special-case `onMessage` branch returns `false` after the immediate ACK so it cannot fall through into generic `respondAsync(handleMessage(...))`.

If the merge is done by naive marker stitching, two failure classes are likely:

- duplicate execution: one fetch through the special-case ACK branch and another through generic `handleMessage`.
- scope breakage: moving ACK variables or result sender code into the wrong function and referencing `sender`, `frameId`, or `proxyRequestId` outside their live scope.

### RESOLVE_LOCAL_ASSET

MAIN behavior:

- immediate ACK with `accepted: true` and `proxy_request_id`
- async fetch in background
- detached result sent back as `RESOLVE_LOCAL_ASSET_RESULT` to the originating tab/frame

FEATURE behavior:

- direct `sendRuntimeMessageWithResponse({ type: 'RESOLVE_LOCAL_ASSET' })` path in content script
- direct return path in background `handleMessage`
- no detached ACK/result contract in content helper

Verdict:

- MAIN contract is the correct one for PR155.
- background `RESOLVE_LOCAL_ASSET` listener branch should live in `chrome.runtime.onMessage`, ahead of generic `respondAsync`.
- content-side helper should consume detached `RESOLVE_LOCAL_ASSET_RESULT`, not rely on one synchronous response body.

### Auto-open/create-project recovery

MAIN generic execution path auto-opens a Flow project if no Flow tab exists.
FEATURE adds stronger, mode-aware target binding, plus self-test recovery budgeting.

Verdict:

- preserve MAIN auto-open/create-project recovery as fallback for non-GFV2 generic execution.
- preserve FEATURE strict self-test recovery budgeting so one self-test does not fan out into repeated project opens.
- do not apply generic auto-open recovery inside the GFV2 early-return lane; FEATURE already has its own surface-acquisition contract.

### Double execution / duplicate message risk

Keeping both MAIN recovery and FEATURE GFV2 logic is safe only if:

- `isGfv2Lane(job)` returns before generic target recovery.
- `RESOLVE_LOCAL_ASSET` is handled by exactly one runtime message special case.
- self-test consumes only one project-open recovery allowance.

Otherwise the branch will double-open projects, double-fetch assets, or double-send runtime results.

### ReferenceError / scope risks

High-risk merge mistakes:

- graft `ensureFreshFlowDomContext` without also grafting `isRecoverableFlowDomBridgeError` and `reloadAndReinjectFlowDomContext`.
- move MAIN detached result sender logic into a scope that does not own `sender?.tab?.id` or `sender?.frameId`.
- keep both generic `handleMessage(... RESOLVE_LOCAL_ASSET ...)` and the special-case `onMessage` ACK branch active for the same caller.

## Content-flow-dom.js Findings

### CFD4 / asset proxy

MAIN content-flow-dom exposes `resolveLocalAssetViaBackgroundProxy(...)` and exports it in `window.__FLOWKIT_TEST_HOOKS__`. It uses:

- immediate ACK validation
- detached `RESOLVE_LOCAL_ASSET_RESULT` listener
- timeout handling with `ERR_PROXY_MESSAGE_TIMEOUT`

FEATURE removed that helper from exported test hooks and replaced the upload lane with a single `sendRuntimeMessageWithResponse({ type: 'RESOLVE_LOCAL_ASSET' })` request.

Independent proof:

- MAIN harness against MAIN code: `PASS All 22 asset picker fixture cases`
- FEATURE branch harness against FEATURE code: `PASS All 8 asset picker fixture cases`
- MAIN harness against FEATURE code: `13 failing case(s)`

The failed cases include:

- missing exported hook `findElementByText`
- missing exported hook `isSelectedControl`
- missing exported hook `getRequiredAssetSlots`
- missing exported hook `sendRuntimeMessageNoThrow`
- missing exported hook `resolveLocalAssetViaBackgroundProxy`
- F2V model and Start-slot safety regressions
- wrong error specificity for aspect/count failures

Verdict:

- CFD4 should use MAIN `resolveLocalAssetViaBackgroundProxy`.
- FEATURE `sendRuntimeMessageWithResponse` path is incompatible with the current harness/spec.
- edit the FEATURE code to satisfy the MAIN harness; do not weaken the harness.

### Mode mismatch

There are two different layers here:

- preselection/readiness diagnostics
- actual execution safety

MAIN already allows a narrow non-fatal readiness exception when the editor surface is otherwise healthy and only the hidden settings state causes a mode diagnostic mismatch.
Execution-time `verifyFlowMode` remains hard-fail for real safety violations.

Verdict:

- keep hard-fail semantics for execution-time F2V safety.
- keep the narrow readiness-only soft exception for hidden pre-upload model/settings visibility if the editor surface is otherwise ready.
- do not broaden the non-fatal exception beyond readiness diagnostics.

### Start upload-slot gate

MAIN `verifyFlowMode` explicitly requires visible `Start` slot for F2V and returns `ERR_START_FRAME_REQUIRED_MISSING`.
FEATURE `verifyFlowMode` no longer enforces that Start-slot requirement the same way, and MAIN harness against FEATURE proves the regression.

Verdict:

- Start upload-slot gate must remain mandatory.
- PR155 must preserve explicit Start-slot error behavior.

### Readiness fields

FEATURE carries the fields the PR split depends on:

- `ui_contract_v2`
- `editor_capability_ready`
- `pre_generate_ready`
- `__GFV2_READINESS__`
- `GFV2_OBSERVE_STATE`
- `GFV2_DISCOVER_SETTINGS`
- `GFV2_APPLY_SETTINGS`

MAIN does not carry these FEATURE seams.

Verdict:

- preserve FEATURE readiness fields and handlers.
- graft MAIN asset-proxy and stale-recovery-compatible logic into FEATURE, not the reverse.

### CAPTCHA handlers

FEATURE adds:

- `GET_CAPTCHA`
- `FLOWKIT_CAPTCHA_PING`
- main-world bridge injection through `content.js` and `injected.js`

These are feature-only support files and are runtime-coupled through `manifest.json`.

Verdict:

- `content.js`, `injected.js`, and `manifest.json` stay in PR155.
- if `manifest.json` loses the `gfv2-readiness.js` load order or main-world `injected.js` hook, runtime behavior regresses.

### Build handshake

MAIN content-flow-dom preserves `legacy-compatible` handshake fallback when background runtime is healthy but build ID is missing.
FEATURE tightened this into a hard failure if `backgroundBuildId` is empty.

That diverges from the prior safety decision provided in the task.

Verdict:

- preserve FEATURE build-match strictness when IDs exist.
- preserve MAIN `legacy-compatible` fallback when the bridge is otherwise healthy.
- do not reject a healthy bridge solely because background omitted build ID if the compatibility contract explicitly allows it.

### Duplicate const / definition-before-use risks

- no syntax-level duplicate binding failure was found by `node --check`.
- the real risk is merge-shape, not parser failure.

High-risk semantic merge mistakes:

- preserving FEATURE helper calls while deleting the helper exports MAIN harness expects.
- restoring the proxy helper but leaving the synchronous `sendRuntimeMessageWithResponse` upload path in place, creating split behavior by caller.

### Feature enriched fields at risk if MAIN is copied over FEATURE

If MAIN content-flow-dom is copied wholesale over FEATURE, PR155 loses:

- `ui_contract_v2`
- `editor_capability_ready`
- `pre_generate_ready`
- `__GFV2_READINESS__` integration
- `GET_CAPTCHA`
- `FLOWKIT_CAPTCHA_PING`
- settings-launcher discovery and GFV2 settings handlers

Verdict:

- MAIN should donate specific contract behaviors.
- FEATURE remains the structural base for `content-flow-dom.js`.

## Harness as Spec

### Is the harness already on MAIN?

- yes

### Did MAIN expand it materially?

- yes
- diff from merge-base to MAIN: `422 insertions, 3 deletions`

### What behavior it specifies

- direct Start-slot fallback upload acceptance
- asset-picker modal upload via file input
- asset-picker modal upload via dropzone
- open shadow-root modal targeting
- weak acceptance rejection
- timeout behavior
- composer/generate targeting
- diagnostic ping header/build stamping
- nested interactive control resolution
- selected-state detection on interactive descendants
- required slot calculation
- F2V model rejection and specificity
- F2V aspect/count rejection specificity
- Start-slot mandatory enforcement
- one-way runtime telemetry without callback lane
- detached background proxy ACK/result contract
- detached background proxy timeout contract
- detached background proxy failure round-trip contract

### Does it encode ACK-pattern / proxy behavior?

- yes
- the harness explicitly requires immediate ACK plus later `RESOLVE_LOCAL_ASSET_RESULT`.

### Does it encode Start-slot safety?

- yes

### Does it encode telemetry one-way behavior?

- yes

### Should PR155 be required to pass this harness unchanged?

- yes

### If FEATURE fails MAIN harness, should code adapt to MAIN rather than editing the harness?

- yes

Independent proof:

- MAIN harness against MAIN code: pass
- MAIN harness against FEATURE code: fail with 13 cases
- FEATURE-only reduced harness: pass with 8 cases

That is evidence that FEATURE code regressed against the active spec, not evidence that MAIN harness is wrong.

## Validation Contract Recommendation

### Static gates

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

### Harness gate

- `node scripts/test-f2v-asset-picker-modal.js`

Implementation note:

- in this audit, `jsdom` was available only through the existing root `node_modules`, so clean worktree harness runs used `NODE_PATH=C:\Users\USER\Desktop\_ref_flowkit\node_modules`.
- that is an environment detail, not a reason to relax the gate.

### Live zero-credit bind-check plan

- load unpacked extension build intended for PR155 only
- run extension self-test only
- run zero-credit bind-check only
- verify Flow tab binding on a real editor tab
- verify content script readiness
- verify stale-tab recovery
- verify GFV2 readiness fields
- verify no `EDITOR_TAB_LOST` regression
- do not click Generate
- do not approve/render
- do not hit `/api/flow/generate`
- do not spend credits

## Recommended PR155 Implementation Contract Inputs

Use these as the exact implementation guardrails for the later Claude Code contract:

1. Base `extension/background.js` and `extension/content-flow-dom.js` on FEATURE, not MAIN.
2. Graft MAIN stale-bridge recovery into FEATURE background:
   - `isRecoverableFlowDomBridgeError`
   - `reloadAndReinjectFlowDomContext`
   - `ensureFreshFlowDomContext`
3. Route generic execution/readiness call sites through `ensureFreshFlowDomContext`.
4. Preserve FEATURE early return to `handleGfv2Job(job)` before generic target recovery.
5. Preserve FEATURE `GET_RUNTIME_SELF_TEST`, `captureGoogleFlowV2Readiness`, strict target recovery, and one-shot recovery budgeting.
6. Restore MAIN detached asset-proxy contract unchanged:
   - content helper `resolveLocalAssetViaBackgroundProxy`
   - background immediate ACK branch
   - detached `RESOLVE_LOCAL_ASSET_RESULT`
   - `ERR_PROXY_MESSAGE_TIMEOUT`
7. Remove or supersede FEATURE synchronous `sendRuntimeMessageWithResponse({ type: 'RESOLVE_LOCAL_ASSET' })` path for CFD4.
8. Restore MAIN harness-exported test hooks needed by the current harness.
9. Preserve FEATURE `ui_contract_v2`, `editor_capability_ready`, `pre_generate_ready`, `__GFV2_READINESS__`, CAPTCHA bridge, and `gfv2-readiness.js` load order.
10. Preserve Start-slot mandatory enforcement and explicit F2V error specificity for:
    - `ERR_START_FRAME_REQUIRED_MISSING`
    - `ERR_ASPECT_9_16_NOT_SELECTED`
    - `ERR_COUNT_1X_NOT_SELECTED`
    - wrong F2V model rejection
11. Preserve MAIN `legacy-compatible` handshake fallback if runtime is healthy but background build ID is absent.
12. Keep `scripts/test-f2v-asset-picker-modal.js` unchanged and require it to pass.

## Final Recommendation

- safe to let Claude implement: `conditional`
- conditions before implementation:
  - accept MAIN harness as immutable spec
  - accept FEATURE as structural base for runtime and GFV2 fields
  - accept MAIN stale-recovery and proxy ACK/result graft as mandatory
  - keep PR155 branch free of selector-registry and non-approved test rewrites
  - require static checks plus MAIN harness pass before any live bind-check

## Audit Evidence

- `git fetch origin` => `PASS`
- `git rev-parse origin/main` => `0f8ec23425171473a029cc5184c1a57b2f59638c`
- `git rev-parse origin/feat/gfv2-runner-upload-settings-prompt` => `66d6bf7faf38b7da5156e338f7fb451271d7fa03`
- `git merge-base origin/main origin/feat/gfv2-runner-upload-settings-prompt` => `cd7c898cc3cbc15d31adc0724220933927a9cbdf`
- `node --check extension/background.js` on FEATURE clean ref => `PASS`
- `node --check extension/content-flow-dom.js` on FEATURE clean ref => `PASS`
- `node --check extension/side_panel.js` on FEATURE clean ref => `PASS`
- `node --check extension/popup.js` on FEATURE clean ref => `PASS`
- `node --check extension/f2v-flow-queue-runner.js` on FEATURE clean ref => `PASS`
- `node --check extension/gfv2-readiness.js` on FEATURE clean ref => `PASS`
- `node --check extension/content.js` on FEATURE clean ref => `PASS`
- `node --check extension/injected.js` on FEATURE clean ref => `PASS`
- `node --check extension/selector-registry.js` on FEATURE clean ref => `PASS`
- manifest JSON parse on FEATURE clean ref => `PASS`
- `node scripts/test-f2v-asset-picker-modal.js` on MAIN clean ref => `PASS All 22 asset picker fixture cases`
- `node scripts/test-f2v-asset-picker-modal.js` on FEATURE clean ref => `PASS All 8 asset picker fixture cases`
- MAIN harness text executed against FEATURE `content-flow-dom.js` => `FAIL 13 case(s)`

## Notes

- `graphify-out/` does not exist in this repo snapshot. Dependency mapping for this audit was done manually from Git tree refs and symbol inspection.
- the live workspace at `prep/extension-runtime-unit-supervised` is already in unresolved-merge state for `extension/background.js` and `extension/content-flow-dom.js`. This audit intentionally used clean ref worktrees instead of that contaminated working tree.
