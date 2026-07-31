# Creative Treatment and P6 Integration Closure

**Status:** APPROVED IMPLEMENTATION AUTHORITY
**Version:** 1.0.0
**Authority phase:** P7.5-P6 integration closure
**Base SHA:** `d3343bf83242004575b79f2201e8bdcec980b348`

## 1. Authority

This contract closes only two proven gaps:

1. P6 Production Studio has no Creative Treatment selection or capacity
   authority.
2. P7.5 rejects governed `EXTEND` treatments even though the locked ADR-007
   video-production orchestrator already supports deterministic 16- and
   24-second INITIAL -> EXTEND -> CONCAT execution.

It supersedes only the `SINGLE`-only and no-dashboard boundaries in
`CREATIVE_TREATMENT_AND_CHOREOGRAPHY_MAPPING.md`. All approval, immutable hash,
format grammar, upstream dependency, Variation Group, provider, and credit
boundaries in that contract remain authoritative.

## 2. Canonical representation

One approved Creative Treatment remains one final P6 video candidate. An
`EXTEND` treatment is one immutable master treatment with an ordered,
immutable `segment_plan` derived at treatment creation:

- segment 1 is `INITIAL`;
- segments 2..N are `EXTEND`;
- 16 seconds is exactly 2 x 8-second engine blocks;
- 24 seconds is exactly 3 x 8-second engine blocks;
- each segment binds its scoped action steps, shots, exact dialogue allocation,
  incoming/outgoing continuity state, dependency hashes, planner allocation
  hash, and segment hash;
- the master treatment hash commits to the ordered segment hashes.

Segments are not independently selectable, reusable, approvable, or billable.
P6 capacity is counted by approved master treatments, never by segment count.

The existing SQLite treatment table is rebuilt additively and retention-safely
to widen `generation_mode` from `SINGLE` to `SINGLE|EXTEND` and add
`segment_plan_json`. Existing rows receive `[]` and retain IDs, versions,
statuses, hashes, timestamps, audit history, and immutability protection.

## 3. Deterministic derivation

Treatment creation resolves the existing model registry and full-storyboard
planner. It fails closed unless:

- every declared model supports the requested logical mode and total duration;
- all declared models resolve to the same orchestration shape;
- every shot references valid actions;
- shot durations exactly fill each engine block without crossing a boundary;
- planner block count, duration, operation ordering, dialogue allocation, and
  continuity states match the requested treatment;
- no generic fallback, synthetic authority, or client-authored segment plan is
  accepted.

Revalidation rebuilds the segment plan from current approved dependencies and
compares the master hash. Approved treatment mutation remains forbidden.

## 4. P6 availability and selection authority

`POST /api/creative-production/treatment-availability` is the only Studio
readiness authority. Its request contains product allocations, logical mode,
model, duration, creative-format preference, and optional explicit treatment
IDs. The service:

1. reads approved treatments by product;
2. revalidates each treatment once;
3. filters exact mode, model, duration, and format compatibility;
4. sorts deterministically by treatment ID;
5. allocates unique treatments against per-product requested quantities;
6. returns selected IDs, capacity, supported configurations, exact blockers,
   and remediation.

`AUTO` format is a selection preference, not persisted treatment truth. P6
create-plan invokes the same authority server-side. If IDs are absent it
auto-allocates the deterministic eligible set; if IDs are explicit it
validates them through the same path. Insufficient capacity fails before any
plan row is created.

The plan snapshot persists the exact treatment IDs, projections, availability
snapshot/hash, selection mode, and format preference. The browser is a
projection only: it must refetch on allocation/mode/model/duration/format
change, suppress stale responses, display exact shortages, and disable Create
while authority is unresolved or insufficient.

## 5. Compile and execution lineage

For `EXTEND`, compile creates:

1. one Workspace Execution Package carrying the approved master treatment and
   segment hashes;
2. one linked Workspace Generation Package whose block prompts are rendered by
   the ADR-008 canonical compiler from segment-scoped treatment material;
3. one durable zero-credit video-production job plan whose fingerprint and ID
   are bound into the P6 attempt payload.

The full-storyboard planner result must equal the approved treatment segment
plan. Scheduler dry-run planning may persist the durable job ledger but must
not authorize, submit, poll, retrieve, concatenate, or spend credits. Live
execution reuses that same logical job and remains behind the existing P6
authorization and ADR-007 gates.

The locked video-production orchestrator is not rewritten. Its current
INITIAL -> ordered EXTEND -> CONCAT loop remains the execution authority.

## 6. Explicit exclusions

- no Product Truth, P5.8, Copy Set, Avatar Registry, scene, camera, or creative
  asset schema changes;
- no provider or extension behavior changes;
- no live media generation, Generate click, DeepSeek call, or credit spend;
- no P8 implementation;
- no client-authored treatment authority;
- no independent segment approval or cross-treatment segment reuse.

## 7. Required proof

Delivery requires:

- SQLite migration retention and constraint tests;
- treatment 8/16/24 derivation, stale authority, and format tests;
- P6 availability/capacity/selection tests;
- canonical compiler and WEP/WGP lineage tests;
- scheduler zero-credit durable-job planning tests;
- Production Studio stale-response and Create-disable tests;
- focused backend and frontend suites;
- real dashboard build;
- Biome, dependency cruise, Mandor, and repository verification gate;
- canonical database backup/migration/readback;
- runtime SHA/bundle/storage proof and rendered browser UAT;
- unchanged provider request counters and no new side-effect evidence.
