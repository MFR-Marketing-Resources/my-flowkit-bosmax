# CURRENT_STATE

## Current Repo Head
- Current local and remote `main` head: `2729d9004d4b6bd467102bea46ae75ed0e12ff31`

## Historical Verified Checkpoints
- User-verified architecture-reset checkpoint: `26e327e11a48c30ccbbb350f3042f041f0c7df34`
- User-verified harness commit included: `81e78719e4f5281d77986dfe9c091681de31b954`

## Current Verified State
- Architecture reset is confirmed.
- NotebookLM conclusions are adopted as repo policy:
  - repeated failures were systemic architecture and testing-method failures, not just one bad selector
  - `content-flow-dom.js` accumulated reactive fallbacks, unverified selectors, direct upload tricks, recursive shadow scanning, and mixed telemetry/execution logic
  - Antigravity must stop iterative debugging
  - Codex owns implementation, local harness, repo cleanup, and commits
  - Antigravity is one-shot UAT only after strict preflight
  - Playwright persistent-context harness is required before live UAT
  - CDP file chooser interception is the recommended upload direction
  - runtime and build telemetry lockdown is required
- User-provided local harness pass at the architecture-reset checkpoint:
  - `node --check extension/content-flow-dom.js`
  - `node scripts/test-f2v-asset-picker-modal.js`

## Current Architectural Decision
- Freeze proven mode/config logic.
- Rebuild runtime handshake, telemetry proof, selector evidence, and upload strategy in phased order.
- Do not use live Google Flow as the primary debugging environment.

## Next Phases
1. Phase 1A: runtime and build handshake plus telemetry lockdown
2. Phase 1B: Playwright persistent-context extension harness
3. Phase 1C: selector and evidence registry
4. Phase 2: CDP file chooser upload proof of concept
5. Phase 3: decontaminate `content-flow-dom.js` upload logic
6. Phase 4: one-shot Antigravity UAT only

## Frozen Paths
- Video mode selection
- Frames mode selection
- `9:16` selection
- `1x` selection
- Veo `3.1 Lite` verification
- Existing local harness scripts should remain intact unless a dedicated test task changes them

## Unstable Paths
- Runtime/build handshake
- Telemetry build/version proof
- Start-frame upload path
- Broad selector fallback logic
- Shadow DOM and modal handling inside the upload lane
- Antigravity report quality

## Blocked Work
- Live Google Flow debugging loops
- Antigravity patching or iterative debugging
- CDP implementation before Phase 2 approval
- Generate clicks without explicit authorization

## Allowed Next Work
- Repo-level telemetry lockdown
- Playwright persistent-context harness work
- Selector registry and evidence registry
- Docs/contracts hardening
- UAT prompt packaging
