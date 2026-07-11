# ADR-009 — Native Google Flow Video Extend (capability-gated, API-first)

Status: ACCEPTED (implementation landed behind a runtime kill-switch; live proof pending)
Date: 2026-07-11
Supersedes/relates: ADR-007 (API-first generation), ADR-008 (canonical prompt compiler),
`extend_route_planner` route authority, `full_storyboard_extend_planner`.

## Context

BOSMAX could plan multi-block storyboards and generate independent 8s blocks, but had
NO runtime support for **native** Google Flow Extend (a temporally continuous
continuation of a prior clip). The route `GOOGLE_FLOW_VEO_EXTEND` was declared but
`AUTHORITY_MISSING` because no captured Flow/aisandbox runtime evidence existed.

Three chat-controlled manual captures on the operator's own Flow project closed that
gap (see `.ai/experiments/aisandbox_extend_discovery/`):

- `extend_live_manual_live_20260711_094742.jsonl` — the Extend submit request (rec 608),
  its SYNCHRONOUS response with the child id (rec 631), and the poll body.
- `concat_completion_smoke_20260711_100555.jsonl` — per-block retrieval + scene/workflow
  structure; the 16s combined output does NOT persist as a media object.
- `download_project_smoke_20260711_102244.jsonl` — "Download Project" is a client-side
  ZIP of per-workflow media (NOT the combined export, no server call, no credit).

## Verified contract (build to THIS, not to inference)

- SUBMIT: `POST /v1/video:batchAsyncGenerateVideoExtendVideo`
  - `requests[].videoInput = {mediaId: <parent OPERATION id>, startFrameIndex, endFrameIndex}`
  - `requests[].videoModelKey = "veo_3_1_extension_lite"`, `useV2ModelConfig = true`
  - `requests[].textInput.structuredPrompt` = the FULL structured block prompt (NOT a
    compact "extend this video" phrase; continuity is carried by `videoInput`)
  - `mediaGenerationContext = {batchId, audioFailurePreference:"BLOCK_SILENCED_VIDEOS",
    sceneContext:{sceneId, position}}`
  - SUBMIT RESPONSE is synchronous: child op id = `media[0].name`
    (== `workflows[0].metadata.primaryMediaId`).
- POLL: `POST /v1/video:batchCheckAsyncVideoGenerationStatus` body
  `{media:[{name:<child>, projectId}]}` (NOT the `{operations:[…]}` generate-lane shape).
- RETRIEVE: existing `get_media(child)`; per-block signed `flow-content.google` URLs.
- DURATION: uniform 8s blocks (the AUTHORIZED `GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS` workbook),
  NOT the public-API `8+7n` model. Final 16s = concatenation of blocks.

## Decisions

1. **Two authority axes, kept separate.** Route authority (block-duration math) vs
   capability authority (RUNTIME transport proven by capture). Native-extend transport
   capabilities are `AUTHORIZED`; the route flag `GOOGLE_FLOW_VEO_EXTEND` stays
   `AUTHORITY_MISSING`. Proving a capability never flips a route.
2. **Direct-RPC lane, not the agent one-door.** `make_video.start_generate` drives the
   flowCreationAgent conversational lane; native extend is a NEW direct-RPC service
   (`google_flow_native_extend_runtime`) + thin `/extend-video` and `/extend-run` routes.
   `make_video` is untouched.
3. **Fail closed, DRY_RUN default.** A live credit-spending submit needs BOTH
   `NATIVE_EXTEND_ENABLED=1` AND per-call `confirm_live_credit_burn=True`. Unknown model,
   missing parent/project/scene, capability missing, contract drift, and duplicate
   in-flight submission all fail closed with explicit machine-readable codes.
4. **`GOOGLE_FLOW_FINAL_CONCAT_EXPORT` stays `AUTHORITY_MISSING`.** `runVideoFxConcatenation`
   exists, but its terminal status contract + persisted combined-media identity were NOT
   captured. The Download Project ZIP is NEVER substituted for the combined export.
5. **Durable lineage with 4 distinct id columns.** `extend_lineage` keeps parent/child
   OPERATION id and primaryMediaId separate (the extend binding uses the OPERATION id;
   block-1 op `b6371e69` != media `69051c7b`). `idempotency_key` UNIQUE blocks duplicate
   credit spend; the row survives the 48h artifact purge and enables safe resume.

## Consequences

- New: `google_flow_native_extend_runtime.py`, capability registry + 4 error/exception
  helpers in `extend_route_planner.py`, `extend_lineage` table + crud, `EXTEND_VIDEO_MODELS`
  + one RPC endpoint, two thin API routes, a frontend route-distinction module, sanitized
  fixtures, and 27 tests. All existing single-block/independent/F2V/I2V/T2V/upscale paths
  are untouched (add siblings, never mutate).
- Pending: a BOSMAX-driven LIVE native-extend proof (credit-consuming, operator approval)
  and the final-concat terminal contract. Until then the verdict is
  `READY_FOR_LIVE_NATIVE_EXTEND_PROOF`, not `DONE_NATIVE_EXTEND_PROVEN`.
