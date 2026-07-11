# BOSMAX Batch Creative Production Orchestrator — Implementation Contract

**Status:** IMPLEMENTATION AUTHORITY  
**Version:** 1.0.0  
**Architecture authority:** `.ai/architecture/BATCH_CREATIVE_PRODUCTION_ORCHESTRATOR_ARCHITECTURE_LOCK.md`  
**Evidence authority:** `docs/research/batch-production-orchestrator/`  
**Evidence merge SHA:** `e3384b6dfcecdd295e91513bbe620fa6c99a1dd1`  

## 1. Assignment

The assigned implementation agent acts with senior accountability as:

- senior system architect;
- senior full-stack engineer;
- database migration owner;
- durable queue and idempotency engineer;
- frontend workflow owner;
- QA and regression auditor;
- Git and pull-request delivery owner.

This is one coherent implementation mission.

The agent must not reduce it into a sequence of user-led tactical patches. It must investigate the repository, identify the complete affected surface, plan the implementation, execute it, test it, and deliver an auditable pull request.

## 2. Real system problem

BOSMAX currently has several partially overlapping batch, prompt, production, image, poster, queue, and artifact paths, but no single durable production authority for high-volume creative operations.

The new module must allow an operator to plan and govern up to 200 video items and 200 image/poster items as a daily capacity objective while preventing silent creative duplication, false concurrency, duplicate credit spending, unrecoverable queue state, and misleading UI status.

The implementation must preserve the proven ADR-007 generation path and build a governance/orchestration layer around it.

## 3. Goal

Deliver a production-ready Batch Creative Production Orchestrator that:

1. creates durable combined video and image/poster production plans;
2. calculates safe unique creative capacity before compilation or generation;
3. expands plans into waves, batches, and durable production items;
4. preserves copy, avatar, scene, product, prompt, and output lineage;
5. schedules items through verified execution lanes;
6. supports dry-run validation before any credit-spending action;
7. prevents duplicate submissions and duplicate credit burn;
8. survives process restart with correct pause, resume, retry, and reconciliation behaviour;
9. exposes truthful operator progress and output QA;
10. integrates with existing proven BOSMAX services rather than creating competing generation paths.

## 4. Mission

Implement the architecture defined in:

`.ai/architecture/BATCH_CREATIVE_PRODUCTION_ORCHESTRATOR_ARCHITECTURE_LOCK.md`

The agent must work from the real repository state and must independently discover:

- all affected backend routes;
- services and queue loops;
- schema and CRUD surfaces;
- frontend API clients and pages;
- prompt and copywriting dependencies;
- image, poster, creative asset, and generated artifact flows;
- legacy batch dependencies;
- failure and restart blind spots;
- tests and fixtures requiring migration;
- downstream regressions.

Do not depend on a narrow file list as the implementation plan. The research pack's affected-surface inventory is a starting point, not permission to ignore hidden dependencies.

## 5. Read-first authority

Before making any change, read and obey:

1. `AGENTS.md`
2. `.ai/status/CURRENT_STATE.md`
3. `.ai/ENGINEERING_LOCKDOWN.md`
4. `.ai/contracts/AI_AGENT_OPERATING_CONTRACT.md`
5. `.ai/contracts/CODEX_IMPLEMENTATION_CONTRACT.md`
6. `.ai/contracts/GIT_PROOF_REQUIREMENTS.md`
7. `.ai/contracts/REPORT_REJECTION_RULES.md`
8. `.ai/contracts/RUNTIME_TELEMETRY_LOCKDOWN.md`
9. `.ai/contracts/ANTIGRAVITY_UAT_CONTRACT.md`
10. `.ai/architecture/BATCH_CREATIVE_PRODUCTION_ORCHESTRATOR_ARCHITECTURE_LOCK.md`
11. ADR-007 and ADR-008
12. `docs/research/batch-production-orchestrator/README.md`
13. All reports and evidence matrices in that research directory
14. `docs/agent-delivery-sop.md`
15. `docs/VERIFICATION_GATE.md`

Conflict order is defined by `AGENTS.md` and the architecture lock.

## 6. Current wrong behaviours to eliminate

The implementation must address these verified or accepted gaps:

- no unified daily production plan authority;
- separate WGP, production run, bulk generation, legacy batch, and poster concepts;
- video execution serial without a first-class lane scheduler;
- image concurrency code not represented as verified provider capacity;
- process-memory pause/cancel state that is not restart-safe;
- no durable generation-attempt and idempotency model sufficient for reconciliation;
- no max-unique-capacity preflight;
- incomplete cross-batch creative DNA governance;
- no unified poster bulk production flow;
- ambiguous distinction between queued, submitted, generated, retrieved, and QA-approved;
- legacy batch path capable of confusing operator and architecture ownership.

## 7. Expected target behaviour

### 7.1 Production planning

The operator can create a production plan with:

- product or campaign scope;
- target video quantity;
- target image/poster quantity;
- operating window;
- variation allocation;
- approved copy, avatar, scene, style, layout, and product pools;
- execution and credit policies.

The system persists the plan before compilation.

### 7.2 Capacity preflight

The system calculates:

- eligible approved pools;
- exact unique combination capacity;
- effects of controlled reuse;
- quota pressure;
- duplicate history exclusions;
- missing input and approval blockers;
- requested versus available safe capacity.

A shortfall blocks approval and returns a precise remediation report.

### 7.3 Content matrix

The system produces a previewable matrix of planned production items before spending credits.

Each row exposes material creative dimensions, duplicate status, lineage, and readiness.

### 7.4 Compilation and approval

Prompt compilation remains separate from live execution.

The operator can bulk approve eligible items. Blocked or unapproved items cannot enter live production.

### 7.5 Waves, batches, and scheduling

The operator can organize plan items into waves and review batches.

Batch quantity does not define concurrency.

The scheduler assigns approved items to eligible verified execution lanes according to media type, health, capacity, interval, cooldown, and operator policy.

### 7.6 Live execution

Before live execution:

- all payloads pass dry-run validation;
- credit spending requires explicit confirmation;
- attempts receive durable idempotency identities;
- lane ownership is acquired durably;
- the existing hardened generation door is used.

### 7.7 Monitoring and recovery

The operator can see plan, wave, item, attempt, lane, retrieval, and QA status.

Pause, resume, cancellation, and retry remain effective after backend restart.

When submission outcome is uncertain, the system reconciles provider and local state before considering resubmission.

### 7.8 QA and replacement

Retrieved assets enter QA.

The operator can approve, reject, or request a replacement. Replacement creates explicit lineage and does not erase the rejected attempt or asset history.

## 8. Required implementation capabilities

The implementation must provide, end to end:

### 8.1 Durable data model

Add or extend schema to represent the capabilities locked in the architecture:

- production plans;
- waves;
- production batches or equivalent review grouping;
- production items;
- generation attempts;
- execution lanes;
- creative DNA and capacity-preflight snapshots;
- output QA and replacement lineage;
- durable control and lease state.

The agent must choose repository-consistent table and migration design and document the reasoning.

Requirements:

- safe migration from existing databases;
- idempotent migrations where repository conventions require it;
- indexes for queue selection, state reconciliation, lineage, and dedupe;
- explicit uniqueness constraints where they enforce idempotency;
- no silent destructive migration;
- rollback or recovery notes for material schema changes.

### 8.2 Service architecture

Implement clear services for:

- plan creation and mutation;
- capacity preflight;
- item planning and creative DNA;
- approval;
- wave and batch allocation;
- lane registration and health;
- scheduling and durable leasing;
- dry-run validation;
- attempt creation and execution;
- provider-state reconciliation;
- retrieval and registration recovery;
- QA and replacement.

Do not create a monolithic service that duplicates existing prompt compiler, generation, or asset services.

### 8.3 API surface

Provide typed request and response contracts for all required operator actions.

APIs must:

- validate state transitions;
- fail closed on missing approvals or capacity;
- return stable error codes;
- distinguish dry run from live execution;
- require explicit live credit confirmation;
- expose progress and blockers;
- protect against duplicate action requests;
- preserve compatibility for existing unaffected workflows.

### 8.4 Frontend operator module

Build a coherent operator workflow rather than isolated controls.

Required functional areas:

- production-plan list and detail;
- plan configuration;
- pool and allocation selection;
- capacity-preflight report;
- content-matrix preview;
- duplicate and quota review;
- compilation and bulk approval;
- wave/batch assignment;
- execution policy and dry run;
- live confirmation;
- production control tower;
- lane health;
- failure and retry management;
- output QA and replacement.

The UI must be responsive, accessible under repository standards, and truthful about states.

### 8.5 Creative diversity and dedupe

Implement exact duplicate and creative DNA safeguards across the relevant product/campaign history.

At minimum:

- exact prompt duplicate;
- exact copy/dialogue identity;
- exact creative DNA duplicate;
- avatar-scene-hook combination duplication;
- configurable semantic or similarity warning where existing mechanisms support it;
- quota warnings;
- controlled reuse exceptions with operator-visible reason.

Do not present near-duplicate heuristics as certainty.

### 8.6 Scheduler and execution lanes

Implement lane-aware scheduling without enabling unsafe concurrency.

Initial rules:

- video lane capacity defaults to one inflight item per verified lane;
- unverified lanes cannot receive live items;
- image capacity must be configuration- and proof-aware;
- lane leases must be durable and expire/reconcile safely;
- intervals and cooldowns are enforced per policy;
- paused or disabled lanes do not accept new work;
- in-flight work is reconciled after restart.

### 8.7 Failure recovery and idempotency

Provide deterministic handling for every scenario in the evidence failure-recovery matrix.

Particularly prove:

- duplicate operator submit cannot create two attempts;
- lost response after provider acceptance does not cause blind resubmission;
- process restart preserves intended pause/cancel state;
- generated-but-unretrieved jobs can resume retrieval;
- retrieved-but-unregistered artifacts can resume registration;
- retry policy distinguishes validation retry, retrieval retry, and new generation retry;
- partial wave success does not corrupt aggregate counts;
- replacement items preserve lineage.

### 8.8 Legacy batch transition

Do not build the new orchestrator on top of the legacy batch path as its primary authority.

The implementation must:

- identify remaining consumers;
- prevent new operator confusion;
- freeze or clearly deprecate the legacy route/UI;
- bridge or migrate only required information;
- retain compatibility until removal is proven safe;
- document remaining retirement work.

Do not delete legacy tables or code without data and regression proof.

## 9. Guardrails

### 9.1 Protected generation system

Do not rewrite or bypass:

- `/api/flow/execute-flow-job` and the hardened one-door generation path;
- `make_video.start_generate` behaviour except where a proven integration defect requires a surgical compatible change;
- model and duration validation;
- media resolution and upload protections;
- negotiation brain;
- telemetry bridge;
- retrieval and collect-all-N protections;
- generated artifact access;
- manual generation workflows.

Any change to a protected path requires:

- explicit justification;
- focused regression tests;
- existing mandatory gate results;
- no unrelated refactor.

### 9.2 No false concurrency

Do not claim or implement multiple safe video jobs on one unverified lane.

Do not use multiple async tasks, tabs, projects, or sessions as proof of independent capacity.

### 9.3 No live credits during normal implementation

All implementation and automated tests must be credit-free.

Live Google Flow testing requires explicit user authorization under the existing UAT contract.

### 9.4 No broad rewrite

Preserve existing proven behaviour. Make cohesive changes only where required by this mission.

No formatter noise, opportunistic cleanup, unrelated refactor, or speculative framework replacement.

### 9.5 No hidden fallback

Do not silently downgrade models, durations, copy governance, asset requirements, or duplicate policy to make a run pass.

### 9.6 No fake completion

A compiled frontend, passing unit tests, or an attractive UI alone does not constitute completion.

## 10. Scope exclusions

Unless a proven dependency requires a narrow adjustment, this mission does not include:

- changing BOSMAX product claims or marketing policy;
- rewriting the canonical prompt compiler;
- replacing Google Flow provider integration;
- restoring dead DOM-driving lanes;
- conducting an actual 200+200 live stress run;
- enabling unverified multi-account or multi-tab concurrency;
- deleting all legacy batch code in one unproven cutover;
- redesigning unrelated dashboard modules.

## 11. Required discovery phase

Before coding, the agent must produce an internal implementation map covering:

- current main SHA;
- affected schema and migration chain;
- existing APIs and callers;
- reusable services;
- protected paths;
- obsolete or conflicting paths;
- test and fixture impact;
- implementation sequence;
- major risks and mitigations.

This discovery is part of execution, not a request for the user to supply file-level instructions.

If the evidence pack is incomplete or stale relative to current main, the agent must investigate and resolve the delta.

## 12. Test and proof requirements

### 12.1 Unit tests

Cover at minimum:

- state transition legality;
- capacity-preflight calculations;
- creative DNA normalization and exact dedupe;
- controlled reuse;
- lane eligibility and scheduling;
- interval/cooldown policy;
- lease acquisition and expiry;
- idempotency;
- retry classification;
- aggregate progress;
- legacy compatibility boundaries.

### 12.2 API tests

Cover:

- plan CRUD and validation;
- capacity blockers;
- compilation and approval gates;
- wave assignment;
- dry-run versus live confirmation;
- duplicate requests;
- pause/resume/cancel;
- retry/reconciliation;
- QA and replacement;
- stable error responses.

### 12.3 Database and migration tests

Prove:

- clean database migration;
- migration from representative existing schema;
- required indexes and constraints;
- no data loss;
- restart/reopen behaviour;
- idempotent migration execution if applicable.

### 12.4 Frontend tests

Cover:

- plan creation;
- blocked preflight;
- content-matrix display;
- bulk actions;
- truthful state badges;
- dry-run/live confirmation separation;
- pause/resume/cancel controls;
- failure and retry presentation;
- QA and replacement;
- responsive and empty/error states.

### 12.5 Integration tests

Use fakes or harnesses to prove:

- scheduler to existing generation door payload mapping;
- attempt/job/artifact lineage;
- restart recovery;
- uncertain submission reconciliation;
- generated-but-unretrieved recovery;
- retrieved-but-unregistered recovery;
- partial batch completion;
- exact duplicate prevention across historical items.

### 12.6 Repository verification gate

Run all required repository gates, including `scripts/verify-gate.ps1` for dashboard/backend work.

Report every command and exact result. Pre-existing failures must be reproduced against the base SHA before being classified as unrelated.

## 13. Runtime proof requirements

Normal implementation must stop before credit-spending live proof unless explicitly authorized.

The implementation must prepare:

- a runtime-proof plan;
- exact scenarios;
- expected telemetry stages;
- credit estimate;
- stop conditions;
- rollback and reconciliation steps.

If live proof is authorized later, it must follow the Antigravity/runtime telemetry contracts and cannot be replaced by screenshots or narrative claims.

## 14. Git delivery requirements

The agent must:

1. start from the actual current `main`;
2. create a dedicated implementation branch;
3. keep commits coherent and free of unrelated changes;
4. run required validation before push;
5. push the exact branch;
6. open a pull request;
7. include full 40-character head SHA;
8. include exact changed files and diff stat;
9. include test commands and results;
10. inspect remote PR diff and status;
11. address review findings within the mission;
12. keep the PR merge-ready;
13. not merge without explicit authorization unless the initiating prompt explicitly grants merge authority;
14. after authorized merge, report merge SHA and run post-merge validation on current `main`.

## 15. Pull-request contract

The PR description must include:

- business problem;
- architecture implemented;
- schema and migration summary;
- legacy-path treatment;
- protected-path changes, if any;
- UI workflow;
- idempotency and recovery proof;
- dedupe and capacity-preflight proof;
- tests and gates;
- known gaps;
- live-runtime status;
- rollback considerations;
- screenshots or browser evidence for UI, supplemental to automated proof;
- exact head SHA.

## 16. Completion criteria

The mission may be reported `READY_FOR_REVIEW` only when:

- architecture-lock capabilities are implemented end to end;
- migrations are safe and tested;
- frontend and backend are integrated;
- exact duplicate and capacity blockers work;
- durable attempt and lane state exists;
- restart recovery is proven without live credits;
- protected manual generation remains functional under tests/harness;
- required verification gate passes or every failure is correctly baseline-proven;
- branch is pushed;
- PR exists and is inspected remotely;
- no critical hidden gap remains.

The mission may be reported `DONE` only after:

- PR review is resolved;
- merge is explicitly authorized and completed;
- merge SHA is recorded;
- post-merge validation on `main` passes;
- remaining live-runtime proof is clearly separated and not falsely claimed.

## 17. Required final report

The final report must contain:

- `STATUS`
- `REPOSITORY`
- `BASE_MAIN_SHA`
- `BRANCH`
- `HEAD_SHA`
- `PR_URL`
- `ARCHITECTURE_SUMMARY`
- `SCHEMA_AND_MIGRATIONS`
- `LEGACY_BATCH_TREATMENT`
- `CHANGED_FILES`
- `DIFF_STAT`
- `TEST_COMMANDS_AND_RESULTS`
- `VERIFY_GATE_RESULT`
- `UI_BROWSER_PROOF`
- `IDEMPOTENCY_AND_RECOVERY_PROOF`
- `DEDUPE_AND_CAPACITY_PROOF`
- `PROTECTED_PATH_REGRESSION_PROOF`
- `CI_STATUS`
- `REVIEW_FINDINGS_AND_RESOLUTION`
- `LIVE_CREDIT_SPENT`
- `RUNTIME_PROOF_STATUS`
- `KNOWN_GAPS`
- `MERGE_STATUS`
- `MERGE_SHA` when merged
- `POST_MERGE_VALIDATION`
- `NEXT_DECISION`

## 18. Reject conditions

Reject the implementation or report if any of the following is true:

- a competing generation path is introduced;
- unverified concurrency is enabled or claimed safe;
- durable state is replaced by process memory;
- credit spending occurs without explicit authorization;
- duplicate retry can spend credits twice;
- UI reports false lifecycle status;
- capacity shortfall silently produces duplicates;
- legacy and new production paths remain ambiguous to operators;
- migrations lack representative proof;
- protected-path regressions are hidden;
- tests are selectively omitted without explanation;
- a pushed or merged claim lacks exact remote SHA;
- the agent stops after planning or partial scaffolding;
- `DONE` is claimed before merge and post-merge proof.
