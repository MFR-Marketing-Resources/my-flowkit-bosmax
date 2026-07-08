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
- **ADR-007 is in force (2026-07-02): generation is API-FIRST.** The Chrome
  extension is authenticated transport only. The DOM-clicking generation lane
  is DEAD and frozen — never repaired, only deleted.
- All four modes (IMG/T2V/I2V/F2V) run through ONE hardened lane
  (`/api/flow/execute-flow-job` -> `make_video.start_generate`) and were
  live-proven end-to-end (PRs #160-#167). Read `.ai/status/CURRENT_STATE.md`
  for the locked list and its validation gates BEFORE touching anything.
- Local harness and preflight gates are mandatory before any live Google Flow work.
- Antigravity is one-shot live UAT only after Codex reports a clean pushed SHA and the preflight gates pass.

## Roles
- Codex = implementation, local harness, repo cleanup, static validation, commits, push proof.
- ChatGPT = strategic operator, audit reviewer, prompt author, decision router.
- Claude Code = review and refactor planner unless specifically assigned implementation.
- Cursor = implementation assistant only under these repo contracts.
- GitHub Copilot = IDE assistance only; no architecture override.
- Antigravity = one-shot live UAT only; no patching, no debugging, no loop testing.
- NotebookLM = source-of-truth research and Q&A library.
- Gemini Deep Research = external research generator.

## Frozen And Proven Paths
(Per ADR-007 the OLD frozen list — Video/Frames tab selection, 9:16/1x DOM
clicking — described a UI Google deleted; those paths are archaeology, not
protection targets. The CURRENT proven-and-locked list lives in
`.ai/status/CURRENT_STATE.md` and includes:)
- The API-first manual lane (`_run_manual_job_via_generate`) with asset
  resolution, self-heal, project self-provision, and telemetry bridge.
- USER SETTINGS ARE LAW: aspect/count/duration/model plumbed end-to-end;
  unknown model FAILS CLOSED, never silently downgraded.
- The negotiation brain (cap-gate xCount, approve-once, post-approve
  model+duration verify, failure-reply knowledge). Omni Flash internal engine
  alias = `abra` (load-bearing).
- Retrieval: pre-existing-media exclusion, periodic tab reload, collect-all-N.
- The `generated_artifact` library + `/api/flow/artifacts` +
  `/api/flow/retrieved/{media_id}` + dashboard Library gallery.
- The local gates accepted by the user:
  - `node --check extension/content-flow-dom.js`
  - `node scripts/test-f2v-asset-picker-modal.js`
  - the 85-test pytest gate listed in CURRENT_STATE.md
- Do not rewrite ANY locked path unless one of those gates proves a
  regression there. Don't fix what is not broken.

## Unstable Or Rebuild Paths
- Frozen DOM-lane code awaiting DELETION (content-flow-dom DOM-driving lanes,
  f2v-flow-queue-runner) — delete-only; never repair.
- Pre-existing failing unit suites (batch_planner / result_handler /
  product_catalog) — DB/fixture issues unrelated to generation.
- T2V post-approve model verification (text-only generation tool name pending
  one captured approved-SSE).
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
- Dashboard / frontend or backend-service changes:
  - `scripts/verify-gate.ps1` must PASS before a change is reported green. It runs the
    REAL build (`npm run build` = `tsc -b && vite build`), vitest, a backend pytest smoke,
    and mandor-check. A change is NOT green if `DASHBOARD_BUILD` is FAIL — `tsc --noEmit -p`
    alone is NOT sufficient (it missed the PR #265 build regression). See
    `docs/VERIFICATION_GATE.md`. LOCAL ONLY — this gate is not CI; do not claim CI.
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

## Engineering Lockdown

All agents must follow the engineering lockdown rules in:

```text
.ai/ENGINEERING_LOCKDOWN.md
```

These rules are mandatory and additive to this BOSMAX Flow Kit Agent Contract.

If there is any conflict:

1. Preserve existing proven BOSMAX Flow Kit contract behavior.
2. Apply the stricter surgical engineering rule.
3. Stop and ask before broad changes.

Non-negotiable summary:

- Do not fix what is not broken.
- Do not reinvent the wheel.
- Surgical patch only.
- No unrelated files.
- No formatter noise.
- No broad rewrites.
- No runtime claims without runtime evidence.
- No credit-spending generation without explicit user approval.
- Stop if scope expands.
