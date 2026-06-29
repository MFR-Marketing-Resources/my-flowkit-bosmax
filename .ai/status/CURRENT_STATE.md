# CURRENT_STATE

## ⚡ 2026-06-29 — ARCHITECTURE PIVOT (supersedes the DOM-automation plan below)
**Google Flow's UI is now Omni/V2 (a conversational "Agent" box). The old Video/Frames TAB UI is
GONE — so the DOM-clicking automation, the Playwright-harness/CDP-upload phases, and the
`content-flow-dom.js` tab SOP are RETIRED, not broken. Do not fix or resurrect them.**

New reality = **API-first**: extension is transport only (auth + reCAPTCHA + relay + harvest),
the backend is the brain, the UI is thin buttons.

- **THE ONE DOOR:** `POST /api/flow/generate {mode: IMG|T2V|I2V|F2V}` → job; poll
  `GET /api/flow/generate-job/{id}`. Full reference: **`docs/UNIFIED_GENERATE_PIPELINE.md`** (read it).
- **PROVEN end-to-end:** real 2.0 MB mp4 (`e7871bde`) generated from a user's uploaded image
  (I2V) and saved to `output/retrieved/`. Engine + dashboard wiring build-validated.
- **Operating principles (locked):** don't fix what isn't broken · don't reinvent the wheel ·
  surgical patches only (no full rewrite without architecture-change approval) · verify-before-claim
  (no success without the saved file) · one entry point (`/generate`) · ask before credits.
- **TODO:** live-verify each mode once from the button (IMG cheap; T2V/I2V/F2V ~10 credits each —
  ask the owner first); then documentation handoff to Codex/sibling.

Everything below is the historical architecture-reset record. Where it conflicts with this pivot,
**this pivot wins.**

---

## Current Repo Head
- Live `main` head must be verified from Git at runtime using:
  - `git rev-parse HEAD`
  - `git rev-parse origin/main`
  - `git ls-remote origin refs/heads/main`
- This file does not self-declare an immutable current `main` SHA because merging this file creates a new `main` SHA.
- If live Git output conflicts with this file's historical checkpoints, live Git output wins for current-head detection.

## Historical Verified Checkpoints
- User-verified architecture-reset checkpoint: `26e327e11a48c30ccbbb350f3042f041f0c7df34`
- User-verified harness commit included: `81e78719e4f5281d77986dfe9c091681de31b954`
- Round 10 Product-to-Asset Generator merge: `2729d9004d4b6bd467102bea46ae75ed0e12ff31`
- Repo memory/governance commit: `987ef372f08f2079f8bdac5550d6176e7f7d3695`
- Governance reconciliation PR #23 merge: `779ef57b45cf624752d1c9d3df83921298b061b9`

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
