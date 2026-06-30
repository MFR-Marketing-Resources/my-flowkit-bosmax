# PR155 Blind Spots And Decision Table

repo: `farisdatosheikh/my-flowkit-bosmax`
audit branch: `audit/pr155-extension-runtime-forensic`
audit commit sha: `Recorded in Git metadata after commit; see final delivery proof`
main sha: `0f8ec23425171473a029cc5184c1a57b2f59638c`
feature sha: `66d6bf7faf38b7da5156e338f7fb451271d7fa03`
merge-base: `cd7c898cc3cbc15d31adc0724220933927a9cbdf`
date/time: `2026-07-01T02:17:58.0761566+08:00`
auditor: `Codex`
status: `temporary audit artifact, not production documentation`

## Blind Spots

- `graphify-out/` is absent, so dependency mapping is manual rather than graph-export-backed.
- the local branch `prep/extension-runtime-unit-supervised` is in unresolved merge state. File-system reads from that worktree are not authoritative for audit decisions.
- no live Google Flow tab was exercised by contract. Runtime claims here are code-and-harness backed, not live UAT backed.
- the side-panel and popup overlap may tempt scope creep into operator UX instead of the execution seam. They are approved, but not the core PR155 blocker seam.
- FEATURE introduces stricter handshake behavior than the earlier `legacy-compatible` decision. That policy decision must be explicitly reaffirmed or reverted during implementation.

## Decision Table

| decision item | recommended choice | evidence | risk if wrong | confidence |
| --- | --- | --- | --- | --- |
| Structural base for `background.js` | FEATURE base plus MAIN stale-recovery graft | FEATURE contains GFV2 lane, self-test, runner import, strict target recovery; MAIN contains stale-context recovery absent in FEATURE | copying MAIN over FEATURE deletes GFV2 lane; copying FEATURE as-is keeps stale bridge weakness | High |
| Structural base for `content-flow-dom.js` | FEATURE base plus MAIN CFD4 proxy graft | FEATURE owns `ui_contract_v2`, `__GFV2_READINESS__`, CAPTCHA bridge; MAIN harness proves proxy/spec behaviors | copying MAIN over FEATURE drops GFV2 fields; leaving FEATURE as-is fails current spec | High |
| `ensureFreshFlowDomContext` | graft into FEATURE | MAIN has reload-and-reinject recovery, FEATURE lacks it | stale content bridge remains unresolved, causing invalidated content-script failures | High |
| `ensureFlowDomScript` vs `ensureFreshFlowDomContext` | keep both, with `ensureFreshFlowDomContext` as wrapper | MAIN implementation already composes them safely | removing base helpers breaks wrapper; duplicating retries at call sites keeps drift | High |
| BG7 `RESOLVE_LOCAL_ASSET` structure | keep special-case ACK/result branch in `chrome.runtime.onMessage` | MAIN harness asserts detached ACK/result protocol | generic handler path can double-execute or fail callback timing | High |
| Background fetch implementation count | one implementation function only | MAIN centralizes fetch in `resolveLocalAssetViaBackgroundProxy(msg)` | dual fetch paths can send duplicate downloads or conflicting replies | High |
| MAIN auto-open/create-project recovery | preserve as fallback outside GFV2 lane | MAIN generic execution uses it; FEATURE self-test and GFV2 have narrower recovery rules | removing it regresses non-GFV2 usability; applying it inside GFV2 can double-open tabs | Medium-High |
| GFV2 lane ordering | keep FEATURE early return before generic recovery | FEATURE `handleExecuteFlowJob` already branches early to `handleGfv2Job(job)` | generic recovery can mutate surface before GFV2 runner and break mode assumptions | High |
| CFD4 content-side asset resolve | use MAIN `resolveLocalAssetViaBackgroundProxy` | MAIN harness against FEATURE code fails 13 cases, including missing proxy helper exports | synchronous response path will continue to diverge from test spec and detached runtime behavior | High |
| Start-slot gate | keep mandatory for F2V | MAIN harness requires explicit Start-slot failure; MAIN `verifyFlowMode` encodes it | PR155 can falsely pass on broken F2V surface and spend time on wrong stage | High |
| F2V wrong-model rejection | preserve MAIN specificity | MAIN harness requires rejection of explicit Nano Banana or wrong Veo variants | unsafe image-mode or wrong-model execution can pass preflight | High |
| F2V aspect/count rejection | preserve MAIN explicit errors | MAIN harness requires `ERR_ASPECT_9_16_NOT_SELECTED` and `ERR_COUNT_1X_NOT_SELECTED` | ambiguous `FLOW_MODE_MISMATCH` weakens operator diagnosis and safety contract | High |
| Build handshake policy | preserve strict match when IDs exist, preserve `legacy-compatible` fallback when runtime is otherwise healthy | MAIN behavior matches stated prior decision; FEATURE hard-fails missing build ID | too lenient hides drift; too strict rejects healthy bridge contrary to contract | Medium |
| `gfv2-readiness.js` load order | keep before `content-flow-dom.js` in manifest | FEATURE manifest explicitly adds `gfv2-readiness.js` before `content-flow-dom.js` | late load breaks `__GFV2_READINESS__` consumers and weakens editor diagnostics | High |
| CAPTCHA bridge files | keep `content.js`, `injected.js`, and manifest entries together | FEATURE-only diff wires main-world bridge and action capture | partial merge breaks GET_CAPTCHA/FLOWKIT_CAPTCHA_PING path | High |
| Harness authority | keep MAIN harness unchanged | MAIN passes 22 cases; FEATURE reduced harness to 8 cases; MAIN-on-FEATURE fails 13 cases | editing tests to fit feature drift would delete the objective spec | High |

## Recommended Stop Rules For Implementation

- stop if merge editing reaches `extension/selector-registry.js`
- stop if implementation needs non-approved test rewrites
- stop if `background.js` ends up with both generic and ACK-path `RESOLVE_LOCAL_ASSET` execution for the same caller
- stop if `content-flow-dom.js` loses `ui_contract_v2`, `__GFV2_READINESS__`, or CAPTCHA bridge handlers
- stop if MAIN harness still fails after proxy/stale-recovery graft work
