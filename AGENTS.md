# BOSMAX Flow Kit Agent Contract

This repository is under an architecture reset. All agents must inherit the same operating model.

## Read First
1. `AGENTS.md`
2. `.ai/status/CURRENT_STATE.md`
3. `.ai/contracts/AI_AGENT_OPERATING_CONTRACT.md`
4. `.ai/contracts/CODEX_IMPLEMENTATION_CONTRACT.md`
5. `.ai/contracts/ANTIGRAVITY_UAT_CONTRACT.md`
6. `.ai/contracts/REPORT_REJECTION_RULES.md`
7. `.ai/contracts/RUNTIME_TELEMETRY_LOCKDOWN.md`
8. `docs/agent-delivery-sop.md`
9. `.ai/contracts/GIT_PROOF_REQUIREMENTS.md`
10. The relevant `.ai/architecture/*.md` and `.ai/decisions/*.md` files for the current phase

## Current Strategic Decision
- Architecture reset is confirmed.
- Local harness and preflight gates are mandatory before any live Google Flow work.
- Antigravity is one-shot live UAT only after Codex reports a clean pushed SHA and the preflight gates pass.
- `content-flow-dom.js` is not a tactical dumping ground. Proven mode/config logic stays frozen; unstable upload/runtime/telemetry lanes are rebuilt deliberately.

## Roles
- Codex = implementation, local harness, repo cleanup, static validation, commits, push proof.
- ChatGPT = strategic operator, audit reviewer, prompt author, decision router.
- Claude Code = review and refactor planner unless specifically assigned implementation.
- Cursor = implementation assistant only under these repo contracts.
- GitHub Copilot = IDE assistance only; no architecture override.
- Antigravity = one-shot live UAT only; no patching, no debugging, no loop testing.
- NotebookLM = source-of-truth research and Q&A library.
- Hermes = implementation agent via MCP_DOCKER tools. Read `HERMES.md` before any file operation.
- Gemini Deep Research = external research generator.

## Frozen And Proven Paths
- Video mode selection.
- Frames mode selection.
- `9:16` aspect selection.
- `1x` count selection.
- Veo `3.1 Lite` verification.
- The local static harness gates already accepted by the user:
  - `node --check extension/content-flow-dom.js`
  - `node scripts/test-f2v-asset-picker-modal.js`
- Do not rewrite proven mode/config logic unless the harness proves a regression there.

## Unstable Or Rebuild Paths
- Runtime and build handshake.
- Telemetry schema and build-proof enforcement.
- Selector registry and evidence registry.
- Start-frame upload strategy.
- `content-flow-dom.js` upload acceptance logic.
- Live UAT report quality and rejection gates.

## Forbidden Work
- No live Google Flow UAT before harness and preflight pass.
- No Antigravity debugging.
- No manual screenshot-only proof.
- No `REQUEST_ID=N/A` reports.
- No `build=legacy` reports accepted as valid.
- No tactical fallback chains without tests.
- No upload patching without local harness coverage.
- No mixing proven selectors with failed selectors in the same execution path.
- No Generate click unless explicitly authorized.
- No implementation of CDP upload until the approved Phase 2 prompt is executed.

## Validation Gates
- Docs-only work:
  - `git status --short`
  - `git diff --stat`
  - required file existence checks
  - `markdownlint` if available
- Runtime or extension work:
  - the relevant local harness and static checks must pass before commit
  - never use live Google Flow to compensate for missing local proof
- Live UAT:
  - only after `.ai/contracts/ANTIGRAVITY_UAT_CONTRACT.md` preflight passes

## Report Formats
- Codex final report must include:
  - `STATUS`
  - exact changed files
  - validation commands and pass/fail results
  - full 40-character commit SHA
  - exact push target
  - exact push result
  - `NEXT_DECISION`
- Antigravity UAT report must include:
  - `REQUEST_ID`
  - `COMMIT_SHA`
  - `FIRST_FAIL_STAGE`
  - `FULL_FAIL_MESSAGE`
  - raw telemetry-backed `PASS_STAGES`
  - `ABSENT_STAGES`
  - `NEXT_DECISION`

## Conflict Rule
- If `AGENTS.md`, `.ai/status/CURRENT_STATE.md`, or a phase contract conflicts with the task request, stop and resolve the conflict before coding.
- If a secondary instruction surface disagrees with these contracts, this file and the `.ai/contracts/*` pack win.
