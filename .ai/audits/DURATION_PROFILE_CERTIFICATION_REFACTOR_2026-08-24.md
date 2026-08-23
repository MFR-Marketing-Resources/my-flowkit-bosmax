# Shared Duration-Profile Certification Audit — 2026-08-24

## Scope and source of truth

This audit follows ADR-007 (API-first Google Flow transport) and ADR-008 (the
canonical prompt compiler). It is based on the clean branch created from
`origin/main` at `24d90c1d3cc0a28d417fadd2324aa80929a4cbfc`. The existing dirty
owner checkout was not changed.

No provider request, live capture, approval mutation, database snapshot insert,
or credit spend was performed by this refactor.

## Canonical route map

| Surface | Compiler/adapter route | Provider transport | Shared profile | Lane-only gate |
| --- | --- | --- | --- | --- |
| Hybrid | `workspace_generation_package_service.py` maps the logical Hybrid surface to `F2V` with `source_mode=HYBRID`; the compiler renders the canonical 9-section blocks | Reference-image API-first route (`reference_frame_2_video` / `r2v` when the direct route is proven) | Provider/model/duration/aspect/audio/profile-version tuple | Avatar registry selection and product-reference custody |
| Faceless | `faceless_lane_service.py` declares internal transport `F2V` and source `HYBRID`; exact-product requests may additionally use the deterministic compositor route before final delivery | Same reference-image API-first route, or the exact compositor finalization after a scene plate | Same profile as any other eligible lane using the same provider route | No-face law, Product Truth, hand/product custody, exact-product QC |
| Montage | `montage_mascot_creative_grammar.py` obtains its blocks from the canonical compiler; `api/montage.py` resolves the product mascot | Same provider route for the selected profile; montage orchestration is downstream of that proof | Same profile by duration/model/transport, never a Montage-specific provider certificate | Product-bound mascot key visual, cadence, mascot lip-sync |
| Production Studio/P6 | Scheduler/queue compiles the same canonical block plans and calls the one-door generator with upstream provenance | Same provider route for the selected profile; P6 does not change provider transport identity | Same profile by duration/model/transport | P6 scheduler/bulk live certification and manifest/queue authority |

The route is never inferred from a lane label alone. `derive_transport_route`
requires the compiler/transport mode and source mode (or an explicit
materialized route); an ambiguous F2V request without a source mode fails
closed with `TRANSPORT_ROUTE_REQUIRED`.

## Existing gate chain

* `agent/services/canonical_prompt_compiler.py` is the only final prompt
  renderer. `resolve_block_plan("GOOGLE_FLOW", duration)` supplies block
  durations from `agent/authority/wps_blocking_authority.json`.
* `agent/services/video_models.py` resolves model/duration orchestration. The
  current registry supports 8s for Veo Lite/Fast/Quality and Omni Flash, 10s
  for Omni Flash, and 16/24s as Lite/Fast/Quality extend totals with 8s atomic
  blocks.
* `agent/services/video_capability_matrix.py` remains the versioned single
  block policy (`video-capability-v1`). Extend route authority remains in
  `agent/services/extend_route_planner.py`; it is not silently replaced by the
  single-shot policy.
* `agent/services/make_video.py` remains the dispatch boundary. The direct
  route still fails closed for `DIRECT_LANE_DISABLED`, missing captured keys
  (`DIRECT_MODEL_KEY_UNPROVEN:<model>`), unsupported direct durations, missing
  references, and ambiguous source modes. A captured direct key now also has to
  match an exact certified shared profile.
* `agent/services/execution_approval_service.py` still owns the official
  review/approve/dispatch workflow. The new normalized
  `execution_profile_context` is included in the frozen execution-envelope
  hash. It carries the profile, lane-adapter digest, Product Truth digest, Copy
  V2 digest, SweetWPS digest, compositor digest, and compiler digest. A stale
  or altered digest produces a different envelope and cannot reuse an approved
  snapshot.
* The `execution_approval_snapshot` table remains unchanged. The service/API
  workflow is the only snapshot lifecycle; this change does not add direct SQL
  snapshot writes or a bypass.

## Shared duration/model profile

`agent/services/video_execution_profile_service.py` derives and validates:

| Profile | Compiler blocks | Current registry/model constraint |
| --- | ---: | --- |
| 8s | `[8]` | Models whose registry includes 8s |
| 10s | `[10]` | Omni Flash only under the current capability matrix |
| 16s | `[8, 8]` | Models with an authorized 8s independent-block extend route |
| 24s | `[8, 8, 8]` | Models with an authorized 8s independent-block extend route |

The digest key includes provider, canonical model key, total duration, prompt
block count and block durations, aspect ratio, audio/dialogue route, provider
transport key provenance, capability matrix version, execution transport,
generation mode, route, and the credits/cost rule. The profile registry is
`agent/models.json:provider_certification_profiles`. It contains only the
existing source-backed 10s Omni reference-route proof
(`HYBRID_REFERENCE_OMNI_10S_CONTRACT_CAPTURE`, `abra_r2v_10s`); the 8s, 16s,
and 24s profile records remain absent. A proof for one digest cannot satisfy
another duration because the duration and block plan are part of the digest.

Lane evaluation is a conjunction of the exact shared profile certification and
the independent lane gate. Therefore a certified 8s profile can be reused by
eligible Hybrid, Faceless, Montage, and P6 lanes, while a blocked Montage mascot
or P6 scheduler still blocks only that lane.

## Current readiness truth

The source-level implementation is ready for provider-free validation. Current
provider proof is **not fully verified** in this branch: only the existing
10s reference-route record is present; the 8s/16s/24s records are absent, and
the repository still has no fabricated direct model key. Consequently no new
live canary or artifact SHA is claimed here.

The remaining live prerequisites are exact-profile provider evidence through the
official capture route, plus the existing lane-specific gates.
`DIRECT_LANE_DISABLED` and `DIRECT_MODEL_KEY_UNPROVEN` remain genuine fail-closed
controls; neither was manually flipped or populated.
