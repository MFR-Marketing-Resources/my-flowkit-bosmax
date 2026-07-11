# BOSMAX Batch Creative Production Orchestrator — Architecture Lock

**Status:** APPROVED ARCHITECTURE AUTHORITY  
**Version:** 1.0.0  
**Authority date:** 2026-07-11  
**Evidence base merge SHA:** `e3384b6dfcecdd295e91513bbe620fa6c99a1dd1`  
**Evidence pack:** `docs/research/batch-production-orchestrator/`  

## 1. Authority and conflict order

This document is the approved target architecture for the BOSMAX Batch Creative Production Orchestrator.

It is subordinate to:

1. `AGENTS.md`
2. `.ai/status/CURRENT_STATE.md`
3. Existing `.ai/contracts/*`
4. Existing locked ADRs, especially ADR-007 and ADR-008
5. `.ai/ENGINEERING_LOCKDOWN.md`

The forensic evidence pack is secondary evidence. This architecture lock converts the accepted evidence into approved design decisions.

If implementation discovers a conflict with a higher authority surface, implementation must stop at that conflict, document it, and seek an authority decision. It must not silently reinterpret or override locked behaviour.

## 2. Business objective

BOSMAX must support high-volume creative operations with an aspirational capacity target of up to:

- 200 video production items per operating day; and
- 200 image or poster production items per operating day.

This is a **capacity objective**, not a guaranteed service-level agreement.

No implementation may claim that 200 videos or 200 posters per day is achievable until provider-safe throughput is proven at runtime under the actual account, engine, model, duration, retrieval, credit, and operating-window conditions.

The initial planning window is **12 operating hours**. The system must also model 8-hour and 24-hour scenarios. It must not hardcode any one operating window into the domain model.

## 3. Current-state problem being solved

The repository currently contains multiple partially overlapping production concepts:

- workspace generation package batch prompts;
- production runs;
- bulk generation runs;
- legacy batch and batch-variant paths;
- image and poster authoring paths;
- creative asset and generated artifact records.

These paths do not currently form one durable production authority capable of planning, validating, approving, executing, recovering, and auditing a combined high-volume video and poster operation.

The current verified video production behaviour is serial and single-flight. Image worker concurrency exists in code but is not provider-verified. Existing pause and cancel control includes process-memory state that is not sufficient for restart-safe long-running operations.

## 4. Non-negotiable architecture principles

### 4.1 Planning and execution remain separate

The system must separate:

- creative planning;
- prompt compilation;
- approval;
- production scheduling;
- live execution;
- retrieval;
- output QA.

Creating a plan or compiling prompts must never spend provider credits.

### 4.2 ADR-007 generation door remains protected

All live generation must continue through the hardened API-first generation path established by ADR-007.

The orchestrator is a scheduler and governance layer. It must not create a competing generation implementation, restore dead DOM-driving generation, or bypass the existing model, duration, asset-resolution, negotiation, telemetry, retrieval, or artifact-registration controls.

### 4.3 Durable database state is mandatory

Any state required to resume, retry, cancel, recover, prevent duplicate spending, or explain production history must be database-backed.

Process-memory dictionaries may be used only as runtime accelerators. They cannot be the authority for pause, cancellation, attempt ownership, idempotency, or recovery.

### 4.4 Concurrency is lane-based, not task-based

Async tasks, browser tabs, Flow projects, or worker counts do not by themselves establish safe concurrency.

The domain abstraction is **Execution Lane**.

Each lane has a verified capacity and health state. Initial video capacity is:

```text
max_inflight_video_jobs = 1 per VERIFIED execution lane
```

No second video lane may be activated merely because code supports parallel tasks. A lane must be independently runtime-proven.

Image concurrency must remain configurable but fail closed to a safe default until runtime proof establishes the account/provider ceiling.

### 4.5 Idempotency and credit safety are first-class requirements

Every live submission attempt must have a durable idempotency identity.

The system must be able to distinguish:

- not submitted;
- submission initiated;
- provider accepted but response uncertain;
- provider job known;
- generated but unretrieved;
- retrieved but not registered;
- registered;
- QA rejected;
- replacement requested.

A retry must not automatically mean a new credit-spending submission.

### 4.6 Capacity preflight must fail closed

Before a production plan can be approved, the system must calculate whether approved copy, avatar, scene, product, layout, and other governed pools can satisfy the requested quantity under duplicate and quota rules.

If the requested quantity exceeds safe unique capacity, the plan must be blocked with a capacity-shortfall report. It must never silently repeat combinations to hit a numeric target.

## 5. Locked domain model

The implementation must provide the following domain concepts. Exact physical table decomposition may be adjusted when justified by repository conventions, but the capabilities and relationships are mandatory.

### 5.1 Production Plan

The top-level business operation.

Required responsibilities:

- product or campaign scope;
- target video count;
- target image/poster count;
- operating window;
- allocation strategy;
- credit and execution policy;
- capacity-preflight snapshot;
- aggregate status and progress;
- approval identity and timestamps.

A plan may contain both videos and posters.

### 5.2 Wave

A schedulable grouping within a production plan.

Waves permit overlapping stages, for example:

- Wave 1 executing;
- Wave 2 approved and queued;
- Wave 3 compiling;
- Wave 4 awaiting operator resolution.

A wave is not an execution lane.

### 5.3 Batch

A content-governance grouping used for operator review, approval, reporting, and allocation.

A batch may contain multiple production items. Batch size is independent of live concurrency.

### 5.4 Production Item

The durable unit of intended output.

Required item types:

- `VIDEO`
- `IMAGE`
- `POSTER`

A poster is a first-class production item. It may optionally reference a shared creative concept or a paired video item, but it is not required to be a child of a video.

Each item must preserve:

- product and campaign lineage;
- copy-set and angle lineage;
- variation selections;
- prompt-package linkage;
- creative DNA;
- planned media type;
- execution policy;
- current lifecycle state;
- output and QA linkage.

### 5.5 Generation Attempt

Every live or dry-run execution attempt for a production item.

Required responsibilities:

- attempt number;
- idempotency key;
- execution lane;
- provider job ID;
- submission state;
- payload snapshot or immutable reference;
- credit-spend intent and confirmation;
- failure stage and code;
- retrieval status;
- artifact-registration status;
- superseded or replacement relationship;
- timestamps.

### 5.6 Execution Lane

A durable representation of a separately governed runtime capacity unit.

Required attributes include:

- lane identity;
- provider and engine;
- media-type eligibility;
- account/session/profile/project metadata where applicable;
- verified maximum inflight jobs;
- interval and cooldown policy;
- health status;
- enabled/disabled status;
- runtime-proof status and evidence reference;
- last success and failure;
- current ownership or lease.

The design must support one lane initially and future additional verified lanes without redesigning the orchestrator.

### 5.7 Creative DNA and capacity snapshot

Each production item must have a normalized creative identity composed from governed dimensions relevant to that item.

At minimum, where applicable:

- product;
- safe angle or marketing angle;
- copy set;
- hook family and hook;
- dialogue or rendered copy identity;
- avatar or character reference;
- wardrobe or avatar variation;
- scene and scene family;
- visual treatment or layout;
- camera or composition plan;
- product interaction;
- CTA;
- logical mode;
- engine and duration.

The implementation must separate:

- exact duplication;
- near duplication;
- quota overuse;
- explicitly permitted controlled reuse.

## 6. Locked lifecycle model

The implementation may use repository-compatible names, but it must represent these lifecycle stages without collapsing materially different states.

### 6.1 Plan lifecycle

```text
DRAFT
→ PREFLIGHT_BLOCKED | PREFLIGHT_READY
→ PENDING_APPROVAL
→ APPROVED
→ SCHEDULED
→ RUNNING
→ PAUSED
→ COMPLETED | COMPLETED_WITH_FAILURES | CANCELLED | FAILED
```

### 6.2 Item lifecycle

```text
PLANNED
→ COMPILED
→ DEDUPE_BLOCKED | PENDING_APPROVAL
→ APPROVED
→ WAVE_ASSIGNED
→ QUEUED
→ DISPATCHING
→ SUBMITTED
→ GENERATING
→ GENERATED
→ RETRIEVING
→ RETRIEVED
→ QA_PENDING
→ QA_APPROVED | QA_REJECTED
→ REPLACEMENT_PLANNED when required
```

Terminal and exceptional states must include:

- `FAILED`
- `CANCELLED`
- `SUPERSEDED`

### 6.3 Attempt lifecycle

The attempt lifecycle must distinguish pre-credit validation from live submission and post-generation retrieval. It must permit recovery after restart without blindly resubmitting.

## 7. Locked variation strategies

The orchestrator must support at least:

1. `SAME_SCRIPT_DIFF_VISUALS`
2. `SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS`
3. `DIFF_SCRIPT_DIFF_VISUALS`
4. controlled operator-defined allocation matrix

The recommended scalable default is:

```text
SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS
```

This is a default recommendation, not a ban on the other strategies.

Exact-copy reuse must be deliberately bounded and visible to the operator.

## 8. D1–D7 architecture decisions

### D1 — Volume target

**Decision:** 200 video + 200 poster/image is an aspirational capacity objective for the workspace, not a guaranteed per-product or per-account SLA.

Default planning window: 12 hours. The plan must store the actual window.

Model and duration mix remain item-specific and must be included in capacity estimation.

The system must report expected capacity and shortfall rather than promise delivery.

### D2 — Image and video lanes

**Decision:** Execution Lane is the domain abstraction.

Browser tab, project, profile, account, worker, and engine are lane attributes or runtime implementation details. None is automatically an independent lane.

Initial safe defaults:

- video: one inflight job per verified lane;
- image/poster: conservative configurable limit, runtime-proof status visible, no SLA claim.

### D3 — Legacy batch path

**Decision:** The legacy `batch` and `batch_planner` path must not remain a competing long-term production authority.

Implementation must:

1. inventory any data or UI dependency still requiring it;
2. freeze new feature development on the legacy path;
3. migrate or bridge only necessary records or behaviours;
4. route the new operator workflow to the unified orchestrator;
5. deprecate and retire the legacy path when regression and migration proof is complete.

Do not delete legacy schema or code blindly in the first patch.

### D4 — Multi-lane model

**Decision:** Build lane-aware scheduling, but enable only runtime-verified lanes.

The architecture must not hardcode one lane forever, and must not activate unverified parallel lanes.

### D5 — Dedupe policy

**Decision:** Use separate policies for:

- exact prompt/copy duplicate;
- exact creative DNA duplicate;
- semantic dialogue similarity;
- hook reuse;
- avatar and scene quota;
- visual-output similarity when a reliable method becomes available;
- controlled reuse exceptions.

Initial exact duplicate rules must fail closed. Near-duplicate thresholds must be configurable and visible, not buried as magic constants.

### D6 — Poster model

**Decision:** Poster is a first-class production item under the same Production Plan.

A poster may:

- be independently planned;
- share a creative concept with video;
- be paired with a video as a campaign derivative.

Its prompt compilation, rendered-text governance, execution, and QA policy remain media-specific.

### D7 — Durable orchestrator

**Decision:** Durable orchestration is a required architecture capability.

Pause, resume, cancellation, lane lease, attempt ownership, idempotency, and recovery must not depend solely on process memory.

## 9. Throughput authority

The accepted evidence model uses:

```text
T_job = I_mean + G + P
T_block = (N × T_job) + C
J_h = (N × 3600) / T_block
```

All current capacity figures are theoretical.

Locked conclusions:

- one verified video lane is insufficient for 200 videos in 8 or 12 hours under all documented scenarios;
- nominal 24-hour single-lane capacity is approximately 195 before failure allowance;
- one lane exceeds 200 only under the optimistic 24-hour model;
- multi-lane and image concurrency require runtime proof.

The implementation must expose assumptions used by capacity estimates.

## 10. Operator workflow contract

The final operator flow must support:

1. Create production plan.
2. Select product/campaign and media targets.
3. Select allocation and variation strategies.
4. Select or derive approved copy, avatar, scene, and layout pools.
5. Run unique-capacity and readiness preflight.
6. Resolve blockers or reduce target.
7. Preview the complete content matrix.
8. Compile prompt packages without spending credits.
9. Review duplicate and quota risk.
10. Bulk approve content items.
11. Assign waves and execution policy.
12. Run dry-run payload validation.
13. Confirm live credit spend explicitly.
14. Monitor lane, run, wave, item, and attempt progress.
15. Pause, resume, cancel, and retry safely.
16. Review outputs in QA.
17. Approve, reject, or create replacement items.
18. Export or hand off approved assets.

The UI must show truthful states and must not label queued, submitted, generated, retrieved, or approved items as equivalent.

## 11. Failure and recovery requirements

The system must provide deterministic behaviour for:

- local-agent or backend restart;
- extension or provider disconnect;
- accepted submission with lost response;
- DB write failure after provider acceptance;
- job timeout;
- generated-but-unretrieved output;
- retrieval success followed by registration failure;
- insufficient credits;
- invalid model, duration, or media references;
- lane-busy timeout;
- partial wave or batch completion;
- QA rejection and replacement;
- duplicate operator actions.

Recovery must prefer reconciliation over resubmission.

## 12. Protected behaviour

Implementation must preserve unless an existing required gate proves a regression:

- ADR-007 API-first generation door;
- USER SETTINGS ARE LAW;
- model and duration fail-closed behaviour;
- approved prompt/compiler authority;
- asset-role and media-ID validation;
- negotiation and retrieval protections;
- generated artifact registration and access paths;
- existing manual generation workflows;
- copywriting readiness and approval governance;
- no credit spend without explicit confirmation.

## 13. Runtime proof boundary

The implementation may build lane-aware architecture and simulation support without spending live credits.

Live runtime proof requires separate explicit approval and must be staged:

1. local and dry-run proof;
2. one controlled image concurrency test if authorized;
3. one controlled combined image/video test if authorized;
4. one optional second-lane proof if infrastructure exists and is authorized;
5. measured throughput sampling;
6. no 200/day stress run unless separately authorized with a credit budget.

## 14. Definition of architecture completion

The architecture is implemented only when:

- the durable domain model exists;
- old and new authorities are not ambiguous to the operator;
- capacity preflight is operational;
- item-level lineage and attempts are persisted;
- exact duplicate prevention is enforced;
- dry run and explicit live confirmation remain separated;
- restart recovery is proven locally;
- UI and APIs expose truthful lifecycle states;
- required tests and migration proof pass;
- no protected path regresses;
- remaining provider limitations are clearly reported rather than hidden.
