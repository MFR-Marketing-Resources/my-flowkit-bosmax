# Image and poster pipeline audit

## Image generation door

- Same `make_video.start_generate` with mode IMG — **VERIFIED_CODE** (ADR-007 one door).
- IMG not blocked by `_VIDEO_LANE_JOB` — video and image jobs can be submitted concurrently in code — **VERIFIED_CODE**; provider/account behavior **NOT_VERIFIED**.

## Bulk avatar images

- `bulk_generation_run` kind AVATAR_IMAGE, parallel workers 2–3 — **VERIFIED_TEST** (unit), live Flow **NOT_VERIFIED** unless operator smoke (skill: verify-bulk-agent-runtime).

## Poster pipeline

- Readiness: `poster_readiness_service` — **VERIFIED_TEST**
- Prompt draft: `POST /api/poster/prompt-draft` — **VERIFIED_TEST**
- Copy recommendations: `POST /api/poster/copy-recommendations` — **VERIFIED_TEST**
- Live image in poster module: disabled / handoff — **VERIFIED_CODE** (UI contract)
- Poster bulk 200/day orchestrator: **MISSING**

## Competition for locks

Video lock does not apply to IMG; bulk IMG + production video queue could interleave in one agent process — **NOT_VERIFIED** for credit/rate-limit safety.
