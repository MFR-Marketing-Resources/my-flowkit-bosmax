# BOSMAX RPA Click Operator - Workflow & MVP Spec

## Status

**Planning baseline — NOT approved for implementation.** (G0 amendment M1.)

"Planning baseline" means this document may be read, cited, and amended. It does **not** authorize
any coding, Playwright work, or round to begin. Authorization comes only from the owner via
`docs/bosmax-rpa-g0-governance-gate.md` (the G0 gate). At the time of this amendment, **Round A is
BLOCKED** and no round is authorized.

This document is a secondary/reference specification for AI agents or developers who will later implement the BOSMAX Playwright RPA Click Operator. It must be read before any implementation mission.

**Governing authority (G0 amendment M9).** This document is subordinate to, and must be read with:

- `AGENTS.md` (repo-wide agent contract)
- `.ai/decisions/ADR-007-abandon-dom-wiring-api-first-rebuild.md` (generation is API-first; DOM
  generation lanes are dead and delete-only)
- `.ai/contracts/*` (operating, telemetry-lockdown, and report-rejection rules)
- `docs/bosmax-rpa-g0-governance-gate.md` (G0 gate — authority, proof, and blockers)

**On conflict, `AGENTS.md` and `.ai/contracts/*` OVERRIDE this document.** A conflict must be
recorded and routed to the owner, never silently resolved. See the G0 Amendments section at the end
of this document for the binding amendments accepted by the owner.

## Purpose

BOSMAX needs a Playwright-based RPA Click Operator that behaves like a disciplined human operator inside the existing BOSMAX dashboard.

The operator should:

- Open existing BOSMAX pages.
- Follow visible section order.
- Select existing dropdowns/options.
- Click existing buttons.
- Wait for existing UI/job states.
- Capture evidence.
- Repeat bounded daily routine workflows.

The goal is to reduce repetitive user button-clicking while preserving the existing BOSMAX generation architecture.

## Owner Intent Lock

This project is not a new generation engine.

Existing BOSMAX image/video generation modules are already complete and API-backed. Playwright must not replace, bypass, or rewrite them. Playwright is only allowed to operate the dashboard UI like a user.

Workspace Jobs, Results, and Library are evidence surfaces after RPA actions. They are not the primary MVP unless a specific workflow requires read-only evidence capture.

## Non-Goals

Do not:

- Rebuild image/video generation modules.
- Replace existing API-backed functions.
- Call backend generation APIs directly from the RPA.
- Add new Google Flow DOM-driving logic.
- Redesign the production pipeline.
- Rewrite database architecture.
- Bypass existing credit confirmations.
- Bypass existing Copy Set review/approval gates.
- Auto-approve AI-generated copy.
- Trigger live generation without explicit owner authorization.
- Turn this into a broad autonomous platform before the bounded RPA workflow is proven.

## Protected Areas

Do not touch unless separately authorized:

- API-first generation path.
- Google Flow transport.
- Existing video/image modules.
- Retrieval and artifact library.
- Frozen DOM lanes.
- Existing Copy Set review and approval gates.
- Existing Hybrid readiness gates.
- Hybrid fallback confirmation behavior.
- Production Queue credit confirmation behavior.

## Evidence Baseline

> **O5 REFRESH — 2026-07-17. The Round 1-3 findings below are HISTORICAL.** They are retained for
> provenance, not as current fact. Amendment O5 requires this baseline to be re-verified before any
> new round is authorized; the re-verification is recorded in **"Current Baseline (verified
> 2026-07-17)"** immediately after it. Where the two disagree, the current baseline wins.

Round 1 source-level review found:

- BOSMAX has ordered workflow pages and job/status surfaces.
- Selector coverage is insufficient for stable Playwright RPA.
- Stable test IDs and explicit states are needed.

Round 2 runtime review found:

- Dashboard launched at `http://127.0.0.1:5173`.
- Backend launched at `http://127.0.0.1:8100`.
- Hybrid rendered ordered Steps 1-5.
- Step 4 was disabled because Copywriting readiness was `NOT_READY` and Approved Copy Sets was `0`.
- Step 5 did not render a clickable generation control because EXTEND/duration prerequisites were not satisfied.
- Workspace Jobs rendered telemetry with request IDs, statuses, stage history, errors, and remarks.
- Production Queue rendered fail-closed empty state with no production runs.
- No live generation, dry-run, approval, database mutation, or credit-burning action was performed.

Round 3 planning synthesis concluded:

- The correct first operational MVP is not Workspace Jobs monitoring.
- The first RPA MVP should replace real preparation clicks while stopping before live generation.
- Copy Set readiness is a mandatory prerequisite.
- Copy Set generation/approval should not be automated in the first MVP.

## Current Baseline (verified 2026-07-17)

Satisfies amendment **O5**. Every value below was verified read-only at `main =
ce11ece4c42f18bc512d4167ed68e89125cedcbf` (PR #387 merge). No mutation, no queue run, no provider
call was performed to produce it. Values not verified are marked UNKNOWN rather than guessed.

### Delivery state

| Round | State | Merge SHA |
|---|---|---|
| A — selector/state normalization | MERGED + validated | `eef8a0b` (PR #383) |
| B — Hybrid Steps 1-4 UI-click dry-run | MERGED + validated | `2b98714f…` (#385), `1339394e…` (#386) |
| C — evidence/report attachment | MERGED + validated | `ce11ece4…` (#387) |
| D — Production Queue dry-run | **NOT AUTHORIZED, NOT STARTED** | — |

### Runtime (supersedes the `:5173` reading)

| Fact | Historical baseline | Verified 2026-07-17 |
|---|---|---|
| Dashboard origin | `:5173` (Vite dev) | **`:8100`** serves the built bundle; `:5173` -> not running (000). Amendment A binds `:8100`. |
| Backend | `:8100` | `:8100` health 200, `git_head = ce11ece4…`, `git_branch = main`, `source_stale_since_start = false`, `route_count = 409`, 0 missing critical routes |
| Sandbox exception | not recorded | `:8123` (`FLOW_AGENT_DIR` isolated) per the G0 §4 amendment; not running at rest |

### Hybrid workflow (supersedes the Step 4 reading)

| Fact | Historical baseline | Verified 2026-07-17 |
|---|---|---|
| Step 4 | disabled — Copywriting `NOT_READY`, Approved Copy Sets `0` | **Reachable and clicked** in sandbox with an approved Copy Set fixture. Rounds B/C minted durable packages, latest `wep_c2f8a2a5d5cf4e11`. The old reading described a missing fixture, not a missing capability. |
| Step 5 | rendered no clickable generation control | **STILL TRUE.** `action-generate-video` has **0** matches in `dashboard/src`; `workflow-step-5` renders `data-rpa-stop="true"` and exposes no action control. Recorded as G0 **B3**. |
| Step 5 stop proof | not defined | Proven by a **request-count delta of zero** across 14 submission-bearing tables (contract §6), never self-reported |

### Production Queue (supersedes the "empty state" reading)

| Fact | Historical baseline | Verified 2026-07-17 |
|---|---|---|
| `production_run` rows (live) | "fail-closed empty state, no production runs" | **0** — still true |
| `workspace_generation_package` rows (live) | not recorded | 5, **all `production_status = 'NONE'`**; 2 carry a `workspace_execution_package_id` |
| Queue UI RPA readiness | "stable test IDs are needed" | **`ProductionQueuePage.tsx` has 0 `data-testid`.** The REQUIRED queue locators in this document remain **unimplemented**. |
| Credit door | not localised | Exactly one: `POST /api/workspace/production-queue/{run_id}/start` with `confirm_live_credit_burn=true` |

### Risk posture

Rounds A-C touched only prepare-and-stop surfaces. Round D targets the Production Queue, whose live
branch fans out `make_video.start_generate` across **every** queued item — a materially higher risk
class than anything A-C exercised. Round D's boundary is recorded in the G0 gate, not here.

## Workflow Map

**Naming (G0 amendment M15):** the column below is a workflow **Stage**, not a delivery "Phase".
Delivery units in this workstream are **Round A-F** only. "Phase A-E" is retired — it omitted Round F
and collided with the closed *Creative Registry Modernization Phase A-E* workstream.

| Stage | Mandatory | Initial RPA role | Required state before next stage | Evidence surface |
|---|---:|---|---|---|
| Health/preflight | Yes | Safe checker | Dashboard/backend reachable; warnings captured | Health banner, disabled reasons |
| Product selection | Yes | RPA-safe | Immutable product ID selected | Product readiness panel |
| Product truth / grounding | Conditional | Checker first | Required grounding/approval complete | Copy Registry / readiness banner |
| Copy Set candidate generation | If no usable set | Later Prep RPA | Candidate created as review-required | Candidate ID, dedupe/safety result |
| Copy Set approval | Yes for controlled production | Human gate initially | `COPY_APPROVED` | Copy Set ID, approver, timestamp |
| Copy Set selection | Yes | RPA-safe | Approved Copy Set bound to product | Selected Copy Set ID/status |
| Hybrid configuration | Yes | RPA-safe | Valid settings, including EXTEND/duration when required | Step 1 state |
| Load Hybrid Package | Yes | RPA click | Package loaded successfully | Package ID / visible success |
| Generate Final Prompt | Yes | RPA click | Durable final prompt/package state | Prompt/package ID |
| Generate Video | Owner-authorized | Later RPA click | Explicit live authorization | Request/job ID |
| Monitor/report | Yes | RPA-safe | Terminal job/run/item state | Workspace Jobs, Queue, Results/Library |

## Copy Set / AI Assistant Role

Copy Set is both:

- A prerequisite for Hybrid production.
- A later candidate for Prep RPA.

For the first MVP:

- Require one manually approved Copy Set.
- RPA may select and verify the approved Copy Set.
- RPA must stop if no approved Copy Set exists.
- RPA must not use fallback copy as the baseline production path.
- RPA must not generate or approve Copy Sets automatically.

Later Prep RPA may:

- Inspect grounding/readiness.
- Generate Copy Set candidates only with owner authorization.
- Report dedupe and safety results.
- Stop on duplicate, safety, or review warnings.

Approval remains human-gated until a separate owner decision authorizes auto-approval.

## Recommended MVP

Build one bounded **Hybrid Production-Prep Click Operator**.

The MVP must:

1. Open `/operator/hybrid`.
2. Select the owner-designated test product by immutable ID.
3. Verify product/package readiness.
4. Verify one approved Copy Set.
5. Select existing Step 1 settings, including EXTEND and authorized duration when required.
6. Click existing Step 3 `Load HYBRID Package`.
7. Wait for the existing visible package-ready state.
8. Click existing Step 4 `Generate Final Prompt`.
9. Wait for the existing final-prompt/package state.
10. Stop before Step 5 unless the owner separately authorizes one live test.
11. Capture Workspace Jobs/Results evidence using IDs produced by the clicked workflow.

This MVP replaces repetitive preparation clicks while preserving every existing safeguard.

## Minimal Selector / State Patch

Round A should add only selector/state support to existing UI. It must not change business logic.

Required selector/state categories:

- Hybrid root.
- Hybrid Step 1-5 containers.
- Product picker.
- Product option keyed by immutable product ID.
- Copy Set row keyed by Copy Set ID.
- Copy Set status.
- Copy Set approval metadata.
- Copy Set selected-state marker.
- Step 3 action.
- Step 4 action.
- Step 5 action when rendered.
- Per-step state: `NOT_READY`, `READY`, `RUNNING`, `COMPLETED`, `FAILED`, `BLOCKED`.
- Visible prerequisite/error/completion region for each step.
- Durable package ID region.
- Durable request ID region.
- Durable job ID region.
- Durable artifact ID region.
- Production Queue run row.
- Production Queue selected-run state.
- Production Queue item row.
- Production Queue run-scoped controls.
- Workspace Jobs request row.
- Workspace Jobs selected detail and stage history region.

Recommended pattern:

- `data-testid="hybrid-workflow"`
- `data-testid="workflow-step-1"`
- `data-testid="workflow-step-2"`
- `data-testid="workflow-step-3"`
- `data-testid="workflow-step-4"`
- `data-testid="workflow-step-5"`
- `data-state="READY|RUNNING|COMPLETED|FAILED|BLOCKED|NOT_READY"`
- `data-product-id="{productId}"`
- `data-copy-set-id="{copySetId}"`
- `data-testid="action-load-hybrid-package"`
- `data-testid="action-generate-final-prompt"`
- `data-testid="action-generate-video"`
- `data-testid="workflow-job-status"`
- `data-testid="workflow-request-id"`
- `data-testid="workflow-package-id"`
- `data-testid="workflow-error"`
- `data-testid="workflow-completion"`

Exact naming may follow existing project conventions, but the selectors must be stable, unique, and tied to immutable IDs where possible.

## Safe Test Data Needed

Before validating the first click MVP, prepare:

- One designated non-production test product with immutable ID.
- Hybrid product/package readiness.
- One `COPY_APPROVED` Copy Set for that exact product.
- Required product-truth/grounding approvals already completed.
- Approved start-frame/product-anchor state where Hybrid requires it.
- Known EXTEND model and authorized duration configuration.
- Safe workspace where Step 3/4 outputs are identifiable and disposable.
- Expected package/request IDs or a reliable way to capture them after action.

Owner/manual only initially:

- Copy Set approval.
- Product-truth approval.
- Test product/package provisioning.
- Live-generation consent.

Later RPA only with explicit owner authority:

- AI Copy Set candidate generation.
- Safe-test production-run creation.
- Live confirmation.
- Retries.
- Batch/daily repeats.

## Implementation Rounds

| Round | Scope | Proof required | Stop condition | Owner decision |
|---|---|---|---|---|
| A | Selector/state patch only | Rendered locator audit for Copy Set and Hybrid Steps 1-5 | Any business-logic change required | Approve narrow UI patch |
| B | Hybrid Production-Prep Click Operator, Steps 1-4 | Product selected; approved Copy Set selected; package/final-prompt IDs captured | Missing prerequisite or non-terminal state | Approve bounded UI clicks and test workspace |
| C | Evidence attachment | Workspace Jobs/Results correlated to Round B IDs | IDs cannot be correlated | Approve report format |
| D | Production Queue dry-run RPA | One known run/item reaches terminal dry-run state | Empty/ambiguous run controls | Provide dry-run record |
| E | One serial Step 5 live test | Explicit authorization; request/job/artifact evidence | Any unexpected credit/state drift | Per-run live approval |
| F | Prep RPA and bounded daily repeats | Dedupe, review, serial pacing, per-item evidence | Approval/retry policy unclear | Approve prep and batch policy |

## Acceptance Proof

Round A is accepted only when:

- Rendered DOM exposes stable selectors for target workflow elements.
- Each target step exposes a visible state.
- Disabled reasons remain visible.
- No generation logic, API flow, approval logic, or credit safeguard changes are introduced.

Round B is accepted only when:

- RPA selects the intended product by immutable ID.
- RPA verifies approved Copy Set status.
- RPA clicks Step 3 and waits for terminal package-ready state.
- RPA clicks Step 4 and waits for terminal final-prompt/package state.
- RPA stops before Step 5.
- RPA captures package/request/job evidence.
- RPA produces a report with timestamps, selected IDs, statuses, errors if any, and screenshots where relevant.

Step 5 live generation is accepted only after separate owner authorization and proof of:

- Explicit live consent.
- Request/job ID.
- Terminal job state.
- Artifact/result ID.
- No duplicate submission.
- Credit/state behavior understood.

## Stop Conditions

The RPA must stop and report if:

- Dashboard/backend is unreachable.
- Product ID cannot be uniquely selected.
- Product readiness is not satisfied.
- No approved Copy Set exists.
- Copy Set status is not `COPY_APPROVED`.
- Fallback copy is required.
- EXTEND/duration prerequisite is missing.
- A step state is `FAILED` or `BLOCKED`.
- A step does not reach a terminal state.
- A request/job/package ID cannot be captured.
- A retry would risk duplicate work.
- Live generation would be required without explicit authorization.

## Blindspots To Keep Front And Center

- Product readiness does not prove Copy Set readiness.
- Fallback copy is an exception path, not an automation baseline.
- Button enablement is not proof of success.
- RPA must wait for terminal state and durable ID.
- WebSocket state is not sufficient proof; prefer polling-backed visible job/run state.
- Mutable product titles are not stable locators.
- Dry-run does not prove provider execution or artifact retrieval.
- Historical Workspace Jobs rows can be mistaken for current work.
- Retry and candidate generation can create duplicates.
- Copy approval and product readiness can drift between runs.

## Next Owner Decision

> **RETRACTED — superseded by the G0 gate (G0 amendments M1 + M4).**
>
> This section previously read: *"Authorize **Round A and Round B** as the first implementation
> package."* That recommendation is **withdrawn**. It bundled Round A with Round B, which the G0 gate
> now forbids: Round A exists to *discover* that the selector model is incomplete, and bundling would
> let the same mission both find the gaps and improvise around them inside a click mission.
>
> **Binding replacement:**
>
> - **Each round requires a SEPARATE owner decision.** `A+B`, `D+E`, and `E+F` must **never** be bundled.
> - **No round is authorized by this document.** Authorization comes only from the owner via
>   `docs/bosmax-rpa-g0-governance-gate.md`.
> - **Round A is currently BLOCKED** pending the G0 blockers and the unresolved owner-only fields.

Before any Round B validation, a **designated non-production** Hybrid-ready test product with one
approved Copy Set and authorized EXTEND/duration configuration must exist in an **isolated test DB**.
This is a hard prerequisite, not a preparation step (G0 amendment M8) — see
`OWNER_DECISION_REQUIRED: safe non-production product + isolated DB for Round B`.

Do not authorize Step 5 live generation, Copy Set candidate generation, auto-approval, retries, or batch/daily repeats until the bounded MVP evidence is accepted.

---

## G0 Amendments (Binding)

Accepted by the owner from the G0 Decision Ledger
(`docs/bosmax-rpa-g0-governance-gate.md` §12). These amendments **override** any conflicting text
earlier in this document. Ledger IDs are given for traceability.

### A. Runtime target origin — PINNED (M3)

- The canonical RPA target origin is **`http://127.0.0.1:8100`**, the **built** runtime.
- **`http://127.0.0.1:5173` (Vite dev) is NOT an accepted target or proof surface** unless it is
  explicitly launched for a named task **and** the report validates against it explicitly.
- Because `:8100` serves a **built** bundle, a source-only change is invisible there until
  `npm run build` re-runs. Any rendered-selector proof must come from a bundle **rebuilt from the
  commit under review**, and must quote live `git_head` plus `source_stale_since_start=false`.
- The Evidence Baseline in this document recorded the dashboard at `:5173`. That reading is
  **superseded** by this amendment (see also O5 below).

### B. Round A selector/state model — corrections (M5, B1)

The Minimal Selector / State Patch list is amended as follows.

1. **Step 1 setting controls are IN SCOPE and mandatory.** The MVP requires the operator to set
   EXTEND and authorized duration, so each control the MVP must set requires its own selector:
   generation mode (SINGLE/EXTEND), total video duration (EXTEND), block/video duration (SINGLE),
   engine, video model, target language, camera style, character presence, creator persona.
   Each must expose its **current value as a readable attribute** (e.g. `data-value`), not only as
   rendered text — button enablement is not proof that a setting took effect.
2. **The Hybrid fallback-confirmation gate is IN SCOPE.** It is a Protected Area and it **disables
   the Step 4 action while open**, at which point the "continue with fallback" control becomes the
   only enabled control inside the Step 4 container. It requires its own selector and its own state.
   Round B must never click it, and must produce **positive evidence that it did not fire**.
3. **`action-generate-video` inside `workflow-step-5` is REMOVED as an unconditional requirement.**
   Step 5 renders no clickable generation control when EXTEND/duration prerequisites are unmet.
   The selector is **conditional**: required only in a state where the control actually renders.
4. **B1 DECISION — per-step error/completion (owner: option (a)).** The dashboard exposes a
   **single global notice object shared by Steps 3/4/5**, with no step attribution and no freshness
   marker. Per-step error attribution is therefore **not derivable from existing state**.
   **Accepted resolution: tag the existing single global notice, and downgrade the per-step error
   requirement to a GLOBAL STOP.** Any error notice is a **global STOP** for the RPA; it must not be
   attributed to a step and must not be treated as recoverable.
   **State-plumbing is NOT authorized** — Round A must not split, re-scope, or add step attribution
   to the notice. If a future round needs per-step attribution, that is a **new owner decision**.
5. The requirement for "a visible prerequisite/error/completion region for each step" is amended to:
   "a visible prerequisite region per step, plus **one** global notice region treated as a global STOP."

### C. Round A acceptance — build gate added (M6)

Round A is accepted only when, **in addition to** the existing acceptance criteria:

- `scripts/verify-gate.ps1` passes locally — the **real** build (`npm run build` = `tsc -b && vite build`),
  vitest, backend pytest smoke, and mandor-check. **`tsc --noEmit` is NOT sufficient.**
- Every changed file is registered in `docs/MODULE_STATUS.yaml` `owned_paths` and staged before
  mandor-check runs.
- The report **explicitly names which non-HYBRID modes were re-rendered and confirmed unbroken.**
  The Hybrid workflow surface is shared with **T2V, I2V, F2V and IMG**; a Round A patch that is only
  DOM-inspected is **NOT accepted**, because a DOM inspection cannot see a build break.
- The rendered locator audit must be **falsifiable**: each selector asserted in **at least two
  states** (e.g. `NOT_READY` and `READY`). An audit that only ever runs in the one already-observed
  state (Step 4 disabled, Step 5 absent, Queue empty) passes vacuously and is **not accepted**.

### D. Copy Set integrity + prerequisites (M7, M8)

- **Copy Set approval currently has NO server-side actor identity.** The approval actor is recorded
  as a fixed literal, and the approval phrase is a client-side constant. Consequently an RPA approval
  would be **indistinguishable from a human approval** in the record: the rule "RPA must not approve
  Copy Sets" is **unenforceable server-side and forensically unauditable** as built.
- **Round B is READ-ONLY with respect to approval.** It may read, select and verify an approved Copy
  Set. It must never write approval state.
- **A server-side actor/provenance check on Copy Set approval is a hard prerequisite for Round F**
  (AI candidate generation).
- **Safe test data is a hard prerequisite for Round B**, not a preparation nicety: a **designated
  non-production product** with an immutable ID, in an **isolated test DB**. Round B must not run
  against production data in the live DB.
- **Deterministic selection must be defined before Round B**: when more than one approved Copy Set
  exists for a product, the rule for which one the RPA selects must be stated. It is currently
  undefined, and multiple approved sets per product already exist.
- **Approval state is a stale, un-polled client cache.** Mid-run revocation or approval-drop is
  invisible. Round B must re-verify the approved Copy Set immediately before the Step 4 action.

### E. Live Step 5 proof (M14)

Round E is accepted only with **all** of:

1. **Per-run written owner authorization**, quoted in the report. Never standing, never inferred.
2. A **pre-run baseline**: credit balance and job/request/artifact counts.
3. A **post-run delta** against that baseline proving **exactly one** submission.
4. `REQUEST_ID` + `COMMIT_SHA` + a telemetry-backed stage list. `REQUEST_ID=N/A` is auto-rejected.
5. A **duplicate-submission detection method defined in advance** (idempotency key or request-count
   delta) — not asserted after the fact.
6. Explicit reconciliation with `AGENTS.md`'s live-UAT rule; state which rule governs.

**Negative claims require positive evidence.** "The RPA stopped before Step 5" must be proven by a
**generation-request-count delta of zero** against the baseline — never self-reported.

Screenshots are **supporting evidence only, never sole proof** (`AGENTS.md`: no manual
screenshot-only proof).

### F. Accepted optional amendments

- **O1 — state model.** The step state vocabulary adds **`AWAITING_HUMAN_CONFIRMATION`**. Step state
  is **not monotonic**: a Step 3 `COMPLETED` can revert to `NOT_READY` with no operator action (for
  example when a prerequisite is invalidated). The RPA must not assume a reached state is durable and
  must re-verify before acting on it.
- **O3 — Round C report format.** Round C's report format must be pre-cleared against
  `.ai/contracts/REPORT_REJECTION_RULES.md` **before** Round C begins. A report that would be
  auto-rejected (for example `REQUEST_ID=N/A`) is not an acceptable deliverable.
- **O5 — staleness.** The **Evidence Baseline in this document is STALE** and must be treated as
  historical, not current: it records the dashboard at `:5173` (superseded by amendment A) and a
  runtime/DB state that has since changed. It must be re-verified before it is relied on. This
  document must be **re-reviewed whenever the G0 gate is amended**, and before any new round is
  authorized.

### G. Parked

- **O4 — dedupe key strengthening: PARKED until Round F.** The current dedupe is an exact-match
  blind-duplicate guard, which offers near-zero protection for AI candidate generation while still
  reporting a "deduped" signal. This is **not an active prerequisite for Round A**. It **must be
  resolved before Round F** is authorized.

### H. Retained unchanged (D1-D6)

The following are explicitly **retained as written** and are not amended: Owner Intent Lock;
Non-Goals; Protected Areas; the "stop before Step 5" MVP boundary; human-only Copy Set approval with
no auto-approval in the first MVP; the Round A-F decomposition shape. This workstream is **not**
reduced to Workspace Jobs monitoring — the prep-click MVP remains correct.

### I. Unresolved owner-only fields

These block Round A and must be supplied by the owner. They must **not** be invented by any agent.

- `OWNER_DECISION_REQUIRED: BOSMAX auditor human name`
- `OWNER_DECISION_REQUIRED: Round A PR reviewer`
- `OWNER_DECISION_REQUIRED: rollback owner`
- `OWNER_DECISION_REQUIRED: safe non-production product + isolated DB for Round B`
