# PR155 Implementation Contract — Extension Runtime Unit

repo: `farisdatosheikh/my-flowkit-bosmax`
contract branch: `audit/pr155-extension-runtime-forensic`
source audit commit: `4b23af629125a389812852dfdd81463c15303ebe`
source clarification commit: `49534a40c009372bdc2468c163f11ce95f05830f`
main sha: `0f8ec23425171473a029cc5184c1a57b2f59638c`
feature sha: `66d6bf7faf38b7da5156e338f7fb451271d7fa03`
merge-base: `cd7c898cc3cbc15d31adc0724220933927a9cbdf`
status: `temporary implementation contract, not production documentation`
owner: `ChatGPT`
executor: `Claude Code`
review reference: `Codex forensic audit + clarification memo`

---

## 0. Contract Status

This contract is the execution law for PR155.

Claude Code may implement only under this contract.

This contract does **not** authorize merge.
This contract does **not** authorize live generation.
This contract does **not** authorize credit-spending actions.
This contract does **not** authorize edits outside the approved scope.

Implementation status allowed by this contract:

```text
CONDITIONAL IMPLEMENTATION ONLY
```

Merge status:

```text
HOLD
```

---

## 1. Mission

Create the PR155 extension runtime unit by resolving the coupled extension changes from:

```text
origin/feat/gfv2-runner-upload-settings-prompt
```

onto:

```text
origin/main
```

This is the extension-only carve-out from the larger PR146 tracker.

PR146 must **not** be merged directly.

The implementation must preserve:

1. FEATURE API-first / GFV2 runtime structure.
2. MAIN stale-context recovery hardening.
3. MAIN detached `RESOLVE_LOCAL_ASSET` ACK/result contract.
4. MAIN asset-picker harness behavior unchanged.
5. F2V safety gates.
6. Exact approved file scope only.

---

## 2. Non-Negotiable Engineering Rules

```text
- Surgical changes only.
- No broad rewrites.
- No formatter sweep.
- No whole-file blind checkout of conflicted files.
- No guessing on runtime semantics.
- No test weakening.
- No dashboard/backend/docs/product-registration scope.
- No generation.
- No credit spending.
- No live browser automation during implementation unless separately approved.
```

Claude Code must stop and report if the implementation cannot satisfy this contract exactly.

---

## 3. Approved Scope

Only these files may be changed in the implementation branch:

```text
extension/background.js
extension/content-flow-dom.js
extension/manifest.json
extension/side_panel.js
extension/side_panel.html
extension/popup.js
extension/popup.html
extension/f2v-flow-queue-runner.js
extension/gfv2-readiness.js
extension/content.js
extension/injected.js
```

No other files are approved.

---

## 4. Forbidden Scope

Do not modify:

```text
extension/selector-registry.js
agent/*
dashboard/*
docs/*
.ai/*
.claudeignore
HERMES.md
Fastmoss/product-registration files
tests/api/*
tests/unit/*
tests/ui/*
scripts/test-f2v-asset-picker-modal.js
scripts/test-f2v-cdp-file-chooser-poc.js
scripts/test-f2v-playwright-persistent-context.js
```

Important:

- `.ai/*` audit/contract files are reference-only artifacts on the audit branch.
- They must **not** be included in the final PR155 implementation branch.
- The final PR155 implementation branch should contain extension code only.

---

## 5. Required Reference Artifacts

Before implementing, Claude Code must read these audit artifacts from:

```text
branch: audit/pr155-extension-runtime-forensic
```

Required files:

```text
.ai/audit/PR155_CODEX_FORENSIC_AUDIT.md
.ai/audit/PR155_BLIND_SPOTS_AND_DECISION_TABLE.md
.ai/audit/PR155_CODEX_CLARIFICATION_MEMO.md
.ai/contracts/PR155_IMPLEMENTATION_CONTRACT.md
```

Claude Code must verify the expected reference commits:

```text
audit commit: 4b23af629125a389812852dfdd81463c15303ebe
clarification commit: 49534a40c009372bdc2468c163f11ce95f05830f
```

If these files cannot be read, stop and report.

---

## 6. Implementation Branch

Use a fresh implementation branch from latest `origin/main`:

```text
feat/extension-runtime-unit
```

If the branch already exists, do not overwrite blindly. Stop and report branch state.

Do not implement on:

```text
audit/pr155-extension-runtime-forensic
prep/*
origin/feat/gfv2-runner-upload-settings-prompt
main
```

---

## 7. Core Architecture Decision

Use FEATURE as the structural base for:

```text
extension/background.js
extension/content-flow-dom.js
```

Then graft only the audited MAIN seams.

Do not use MAIN as a whole-file replacement.
Do not use FEATURE as a whole-file replacement.
Do not keep both blindly.

Correct mental model:

```text
FEATURE runtime structure + MAIN safety/spec grafts
```

---

## 8. Background.js Contract

### 8.1 FEATURE Structural Base Must Remain

Preserve FEATURE symbols and structure:

```text
handleExecuteFlowJob
handleGfv2Job
captureGoogleFlowV2Readiness
handleRuntimeSelfTest
buildBackgroundStatusResponse
sendTabMessageSafe
respondAsync
ensureFlowDomScript
pingFlowDomScript
GET_RUNTIME_SELF_TEST
GFV2_PROMPT_ACCEPTED
STOP_BEFORE_GENERATE
API-first runtime transport
PR #149 broken Flow target recovery markers, including BROKEN_TARGET_REJECTED
```

### 8.2 MAIN Stale Recovery Must Be Grafted

Preserve and graft MAIN stale-context recovery:

```text
isRecoverableFlowDomBridgeError
reloadAndReinjectFlowDomContext
ensureFreshFlowDomContext
```

`ensureFreshFlowDomContext` does **not** get superseded by FEATURE `ensureFlowDomScript`.

Feature stayed on base behavior; MAIN added new hardening.

The correct resolution is:

```text
Keep ensureFlowDomScript / pingFlowDomScript
AND graft ensureFreshFlowDomContext recovery semantics
```

### 8.3 CHECK_FLOW_COMPOSER_READY

`CHECK_FLOW_COMPOSER_READY` must use fresh-context recovery semantics and must not regress to stale receiver failures.

Must preserve:

```text
ensureFreshFlowDomContext
activeFlowTab / freshContext usage where required
fresh-project recovery semantics
no EDITOR_TAB_LOST regression
```

### 8.4 BG7 Exact Strategy

BG7 is the highest-risk background merge point.

Required strategy:

```text
FEATURE handleExecuteFlowJob + FEATURE handleGfv2Job remain the structural base.
```

`RESOLVE_LOCAL_ASSET` placement:

```text
- Keep one top-level fetch implementation function:
  resolveLocalAssetViaBackgroundProxy(msg)

- Place the detached RESOLVE_LOCAL_ASSET runtime message branch in chrome.runtime.onMessage.

- This branch must live outside:
  handleExecuteFlowJob
  handleGfv2Job
  generic handleMessage

- This branch must appear before the generic respondAsync(sendResponse, async () => handleMessage(...)) fallback.
```

Auto-open/create-project recovery:

```text
- Preserve MAIN-style auto-open/create-project recovery only for non-GFV2 path.
- Use it as helper/fallback inside generic execution or generic readiness.
- Do not run it before GFV2 execution when isGfv2Lane(job) is true.
- Do not let GFV2 readiness failure fall through into generic auto-open recovery.
- GFV2 keeps its own surface acquisition rules.
```

Double-execution guard:

```text
handleExecuteFlowJob must branch in this order:

1. if isGfv2Lane(job): return handleGfv2Job(job)
2. else generic path
```

`RESOLVE_LOCAL_ASSET` must have exactly one caller-visible runtime message branch.

The special-case branch must:

```text
1. sendResponse(ack)
2. return false immediately
3. perform async fetch in setTimeout(..., 0)
4. emit detached RESOLVE_LOCAL_ASSET_RESULT to the originating tab/frame
```

### 8.5 Background No-Go Patterns

Do not:

```text
- put RESOLVE_LOCAL_ASSET inside handleExecuteFlowJob
- put RESOLVE_LOCAL_ASSET inside handleGfv2Job
- let handleMessage and chrome.runtime.onMessage both serve the same caller-visible RESOLVE_LOCAL_ASSET path
- let GFV2 fall through into generic recovery after partial execution
- graft ensureFreshFlowDomContext without reloadAndReinjectFlowDomContext
- graft ensureFreshFlowDomContext without isRecoverableFlowDomBridgeError
- replace background.js wholesale with MAIN
- replace background.js wholesale with FEATURE
```

---

## 9. Content-flow-dom.js Contract

### 9.1 FEATURE Runtime Fields Must Remain

Preserve FEATURE fields and handlers:

```text
ui_contract_v2
gfv2
editor_capability_ready
pre_generate_ready
__GFV2_READINESS__
GFV2_OBSERVE_STATE
GFV2_DISCOVER_SETTINGS
GFV2_APPLY_SETTINGS
GET_CAPTCHA
FLOWKIT_CAPTCHA_PING
capture/readiness diagnostics
configurable model / scoped model visibility behavior
```

### 9.2 MAIN Safety/Spec Behaviors Must Remain

Preserve MAIN behaviors:

```text
resolveLocalAssetViaBackgroundProxy(...)
F2V Start upload-slot safety gate
mode mismatch hard-fail behavior for F2V safety
port-error-safe runtime message behavior
legacy-compatible background build fallback where applicable
settings launcher detection
asset-picker harness test hooks
```

### 9.3 CFD4 Exact RESOLVE_LOCAL_ASSET Contract

The correct caller in `content-flow-dom.js` is:

```text
resolveLocalAssetViaBackgroundProxy(...)
```

Do not expose FEATURE generic `sendRuntimeMessageWithResponse(...)` as the visible CFD4 asset-proxy path.

Required request:

```text
type: RESOLVE_LOCAL_ASSET
assetId
filename
request_id
proxy_request_id
```

Required immediate ACK from background:

```text
{ ok: true, accepted: true, proxy_request_id }
```

Content must verify:

```text
accepted === true
proxy_request_id matches exactly
```

Required detached result from background:

```text
type: RESOLVE_LOCAL_ASSET_RESULT
proxy_request_id
ok
```

Success result shape:

```text
{
  type: "RESOLVE_LOCAL_ASSET_RESULT",
  proxy_request_id,
  ok: true,
  dataUrl,
  mimeType,
  filename
}
```

Failure result shape:

```text
{
  type: "RESOLVE_LOCAL_ASSET_RESULT",
  proxy_request_id,
  ok: false,
  error,
  detail,
  filename?
}
```

Content-side timeout error:

```text
ERR_PROXY_MESSAGE_TIMEOUT
```

The helper must remain exported in:

```text
window.__FLOWKIT_TEST_HOOKS__
```

Required test hook exports include:

```text
findElementByText
isSelectedControl
getRequiredAssetSlots
sendRuntimeMessageNoThrow
resolveLocalAssetViaBackgroundProxy
```

### 9.4 CFD4 No-Go Patterns

Do not:

```text
- treat ACK body as final file payload
- delete RESOLVE_LOCAL_ASSET_RESULT
- collapse detached proxy flow into single-response semantics
- hide resolveLocalAssetViaBackgroundProxy from __FLOWKIT_TEST_HOOKS__
- weaken detached proxy timeout into generic runtime timeout
- edit the harness to pass drifted behavior
```

### 9.5 Mode Mismatch

Mode mismatch for F2V safety must remain hard-fail.

Preserve outcomes such as:

```text
FLOW_MODE_MISMATCH
FAIL_MODE_MISMATCH
```

Feature non-fatal mismatch data may be kept only as diagnostic metadata.

Do not allow a mode-mismatched F2V job to proceed as non-fatal.

### 9.6 Start Upload-Slot Gate

The F2V Start upload-slot safety gate is mandatory.

Preserve:

```text
ERR_START_FRAME_REQUIRED_MISSING
```

Feature `composerPresent` check may be additive only.

Correct behavior:

```text
Start-slot gate remains mandatory
composerPresent check remains additive
```

Do not replace Start-slot safety with composer presence.

### 9.7 Config Pill / Settings Launcher

Hand-merge config detection.

Preserve:

```text
FEATURE normalizeFlowConfigPillText / V2-aware config chip detection
MAIN looksLikeSettingsLauncher detection
```

Avoid duplicate const declarations, especially duplicate:

```text
const looksLikeConfigChip
```

### 9.8 Background Build Handshake

Preserve:

```text
backgroundBuildId defined before usage
legacy-compatible fallback where safe
feature build handshake compatibility
```

Avoid duplicate const declarations in the same scope.

---

## 10. Manifest Contract

Manifest must preserve load order:

```text
content.js
selector-registry.js
gfv2-readiness.js
content-flow-dom.js
```

`gfv2-readiness.js` must load before `content-flow-dom.js`.

Preserve manifest main-world injection of:

```text
injected.js
```

Do not expand permissions unnecessarily.

---

## 11. Side Panel Contract

Use FEATURE conflict hunks for `side_panel.js` runtime-hardening-v2 constants and label.

Preserve MAIN side-panel hardening that applied cleanly outside conflict hunks.

No UI contract regression.

---

## 12. Harness Contract

The following file is authoritative and must not be changed:

```text
scripts/test-f2v-asset-picker-modal.js
```

Required behavior:

```text
node scripts/test-f2v-asset-picker-modal.js
```

must pass unchanged before PR155 is considered ready for review.

Conflict rule:

```text
If FEATURE behavior conflicts with MAIN harness, MAIN harness wins.
```

Feature harness results are relevant only as context, not as merge authority.

Do not edit the harness to make feature drift pass.

---

## 13. Validation Gates During Implementation

After resolving code, run all static gates below.

### 13.1 JavaScript Syntax Gates

```bash
node --check extension/background.js
node --check extension/content-flow-dom.js
node --check extension/side_panel.js
node --check extension/popup.js
node --check extension/f2v-flow-queue-runner.js
node --check extension/gfv2-readiness.js
node --check extension/content.js
node --check extension/injected.js
node --check extension/selector-registry.js
```

### 13.2 Manifest JSON Parse

```bash
node -e "JSON.parse(require('fs').readFileSync('extension/manifest.json','utf8')); console.log('MANIFEST_JSON_OK')"
```

### 13.3 Main Harness Gate

```bash
node scripts/test-f2v-asset-picker-modal.js
```

This must pass unchanged.

Do not run:

```text
scripts/test-f2v-cdp-file-chooser-poc.js
scripts/test-f2v-playwright-persistent-context.js
```

---

## 14. Live Zero-Credit Bind-Check Requirement

The live bind-check is mandatory before merge but is not authorized during implementation unless separately approved.

Live bind-check constraints:

```text
- zero credits
- no generation
- no approve/render
- no /api/flow/generate
- no paid action
- no full job execution
```

Minimum live checklist after static gates pass:

```text
1. Load unpacked extension.
2. Confirm service worker starts cleanly.
3. Confirm side panel can read background STATUS / runtime diagnostics.
4. Run GET_RUNTIME_SELF_TEST with attempt_open_project=false.
5. Run GET_RUNTIME_SELF_TEST with attempt_open_project=true only if needed.
6. Confirm Flow tab content script injection via FLOWKIT_DIAGNOSTIC_PING.
7. Confirm CHECK_FLOW_COMPOSER_READY returns:
   - ui_contract_v2
   - editor_capability_ready
   - pre_generate_ready
   - background_build_id
   - runtime-ready / build-match or legacy-compatible fallback
8. Confirm stale-tab recovery via ensureFreshFlowDomContext semantics.
9. Confirm GFV2 readiness fields and coherent diagnostics.
10. Confirm RESOLVE_LOCAL_ASSET ACK then detached RESOLVE_LOCAL_ASSET_RESULT with matching proxy_request_id.
11. Confirm no EDITOR_TAB_LOST regression.
12. Confirm no request to /api/flow/generate.
13. Confirm no Generate click.
14. Confirm no approve/render action.
15. Confirm no credits spent.
```

Artifacts to capture later:

```text
service worker console lines
self-test JSON result
CHECK_FLOW_COMPOSER_READY JSON result
GFV2 readiness JSON result
RESOLVE_LOCAL_ASSET ACK payload
RESOLVE_LOCAL_ASSET_RESULT payload
network proof showing no /api/flow/generate
```

---

## 15. No-Go Conditions

Stop and report if any of these occur:

```text
- Any non-approved file becomes modified.
- selector-registry.js changes.
- scripts/test-f2v-asset-picker-modal.js changes.
- agent/dashboard/docs/tests change.
- Background has more than one caller-visible RESOLVE_LOCAL_ASSET path.
- RESOLVE_LOCAL_ASSET_RESULT is removed.
- resolveLocalAssetViaBackgroundProxy is removed or hidden from test hooks.
- GFV2 lane can fall through into generic auto-open recovery after partial execution.
- Start-slot safety gate is removed.
- mode mismatch becomes non-fatal for F2V.
- ensureFreshFlowDomContext is missing.
- __GFV2_READINESS__ / readiness fields / CAPTCHA handlers are missing.
- node --check fails.
- manifest JSON parse fails.
- main asset-picker harness fails.
- Any generation path is triggered.
- Any browser automation or credit-spending workflow is run without approval.
```

---

## 16. Implementation Procedure

Claude Code should follow this procedure:

1. Fetch refs.
2. Create a fresh `feat/extension-runtime-unit` branch from `origin/main`.
3. Read required audit artifacts from `audit/pr155-extension-runtime-forensic`.
4. Apply only the 11 approved extension files from feature relative to merge-base.
5. Resolve conflicts according to this contract.
6. Verify exact file scope.
7. Verify no conflict markers remain.
8. Run static validation gates.
9. Produce implementation report.
10. Stop before commit/push/open PR unless separately authorized.

Expected patch application source:

```bash
BASE=$(git merge-base origin/main origin/feat/gfv2-runner-upload-settings-prompt)

git diff "$BASE"..origin/feat/gfv2-runner-upload-settings-prompt -- \
  extension/background.js \
  extension/content-flow-dom.js \
  extension/manifest.json \
  extension/side_panel.js \
  extension/side_panel.html \
  extension/popup.js \
  extension/popup.html \
  extension/f2v-flow-queue-runner.js \
  extension/gfv2-readiness.js \
  extension/content.js \
  extension/injected.js \
  > /tmp/pr155-extension-runtime-unit.patch

git apply --3way --index /tmp/pr155-extension-runtime-unit.patch
```

---

## 17. Required Implementation Report

After implementation, Claude Code must report:

```text
PR155 Implementation Report

Repo state:
- branch:
- origin/main:
- feature:
- merge-base:
- working tree state:

Scope:
- exact changed files:
- approved 11 files only? yes/no
- forbidden files touched? yes/no

Conflict resolution summary:
- background.js:
  - structural base:
  - ensureFreshFlowDomContext:
  - handleExecuteFlowJob / handleGfv2Job:
  - RESOLVE_LOCAL_ASSET branch placement:
  - auto-open/create-project fallback:
  - double-execution guard:
- content-flow-dom.js:
  - resolveLocalAssetViaBackgroundProxy:
  - RESOLVE_LOCAL_ASSET ACK/result:
  - test hooks:
  - Start-slot gate:
  - mode mismatch:
  - readiness fields:
  - CAPTCHA handlers:
  - backgroundBuildId:
- manifest:
  - gfv2-readiness order:
- side_panel:
  - runtime-hardening-v2:

Validation:
- node --check background:
- node --check content-flow-dom:
- node --check side_panel:
- node --check popup:
- node --check f2v-flow-queue-runner:
- node --check gfv2-readiness:
- node --check content:
- node --check injected:
- node --check selector-registry:
- manifest JSON:
- asset-picker harness:

Behavior audit:
- FEATURE base preserved:
- MAIN stale recovery grafted:
- MAIN RESOLVE_LOCAL_ASSET contract restored:
- MAIN harness unchanged:
- F2V safety gates preserved:
- GFV2 readiness preserved:
- no generation triggered:

Diff summary:
- total files:
- additions:
- deletions:
- background.js diff lines:
- content-flow-dom.js diff lines:
- high-risk sections:

Decision:
- resolved state viable? yes/no
- ready for human diff review? yes/no
- ready to commit? no unless separately authorized
- ready for live zero-credit bind-check? yes/no

Safety:
- committed? no unless separately authorized
- pushed? no unless separately authorized
- PR opened? no unless separately authorized
- PR146 merged? no
- generation triggered? no
- credits spent? no
- browser automation run? no
```

---

## 18. Definition of Done

Implementation phase is done only when:

```text
- only approved 11 files are changed
- no forbidden files are touched
- no conflict markers remain
- node --check gates pass
- manifest JSON parse passes
- node scripts/test-f2v-asset-picker-modal.js passes unchanged
- background.js preserves FEATURE base + MAIN stale recovery
- content-flow-dom.js preserves FEATURE readiness + MAIN proxy/safety contract
- manifest load order is correct
- no generation was triggered
- no credits were spent
- implementation report is produced
- Claude Code stops before commit/push/open PR unless separately authorized
```

---

## 19. Final Instruction to Claude Code

Implement only if you can satisfy this contract exactly.

If any required decision is ambiguous, stop and report.

If any validation gate fails, stop and report.

If any forbidden file is modified, stop and report.

Do not optimize beyond the contract.

Do not reopen already-settled decisions.

Do not merge PR146.
