# BOSMAX RPA Click Operator - Workflow & MVP Spec

## Status

Planning baseline approved for documentation.

This document is a secondary/reference specification for AI agents or developers who will later implement the BOSMAX Playwright RPA Click Operator. It must be read before any implementation mission.

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

## Workflow Map

| Phase | Mandatory | Initial RPA role | Required state before next phase | Evidence surface |
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

Authorize **Round A and Round B** as the first implementation package:

- Round A: selector/state normalization only.
- Round B: Hybrid Production-Prep Click Operator for Steps 1-4.

Before Round B validation, manually prepare one Hybrid-ready test product with one approved Copy Set and authorized EXTEND/duration configuration.

Do not authorize Step 5 live generation, Copy Set candidate generation, auto-approval, retries, or batch/daily repeats until the bounded MVP evidence is accepted.
