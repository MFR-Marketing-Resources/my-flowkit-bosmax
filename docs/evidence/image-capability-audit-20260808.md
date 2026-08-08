# Image/Poster Capability Audit — 2026-08-08

## Scope

This is the Phase 1A static/no-spend audit for the shared image generation lane.
It covers the current canonical runtime and the source contract for Poster Builder,
IMG Fastlane, IMG Cockpit and IMG. No Google Flow image operation was submitted.

## Runtime baseline (read-only)

| Evidence | Value |
| --- | --- |
| Source delivery baseline | `origin/main` / `c2a05b4b489b3425fd96b725e27850045c7f82d3` |
| Served backend SHA | `c2a05b4b489b3425fd96b725e27850045c7f82d3` |
| Served branch identity | detached `HEAD` |
| Backend PID | `21032` |
| Frontend bundle | `index-DCwaPLfi.js` |
| Effective database | `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db` |
| Database integrity | `PRAGMA integrity_check = ok` |
| Product count | `901` |
| `/api/flow/generate` | present |
| `/api/flow/generate-image` | present |
| `/api/flow/generate-image-oneshot` | present |
| `/api/operator/runtime-storage-status` | `FLOW_AGENT_DIR_OVERRIDE_ACTIVE`; DB is canonical Desktop DB |

The served runtime is a detached pre-change process. It is evidence for the
baseline only; it is not evidence that this branch is deployed. The runtime must
not be restarted before an accepted merge SHA is available.

## Phase 1A result

### SUPPORTED

- The API-first transport has a single `/api/flow/generate` entry point for IMG.
- The image request maps the configured `NANO_BANANA_PRO` and `NANO_BANANA_2`
  keys to provider identifiers through `agent/models.json` and fails closed for
  unknown/pending identifiers.
- The transport accepts an ordered `imageInputs` list with reference input type.
- The response parser can materialize provider media names and image URLs.
- Creative Campaign now rejects hidden retries and requires a declared maximum
  provider-operation count before the live submit path.

### UNPROVEN

- A generic `imageInputs` list does not prove that Google Flow/Nano Banana
  recognizes semantic roles such as canonical product, label crop, logo crop or
  cutout.
- Payload acceptance does not prove multi-reference fusion, product editing,
  label/logo fidelity, geometry fidelity or real-world scale preservation.
- `NANO_BANANA_2` is an internal BOSMAX mapping (`NARWHAL` in the current source),
  not proof that the provider exposes every advertised Nano Banana capability.
- The current image response contract exposes media identity, but a provider
  operation ID was not statically proven. The worker records this as
  `UNPROVEN_PROVIDER_OPERATION_ID` rather than manufacturing an ID.
- Provider output count is not proven until a bounded live artifact run returns
  and is inspected.

### BLOCKED

- Phase 1B live benchmark is blocked until the owner authorizes a bounded credit
  budget. The feature flag and live authorization flag remain off by default.
- Creative Campaign is blocked when the Product Reference Pack is not approved,
  when a bound reference is not approved, or when the pack has no canonical
  product reference.

## Product Reference Pack contract

The pack is created without provider spend when a product is registered or when
the creative route first resolves a product. It binds immutable canonical image
bytes, deterministic label/logo crop candidates, and an existing exact cutout
when available to `product_id`. Candidate crops are never auto-approved.

Physical scale is evidence-only:

- `physical_width_mm`
- `physical_height_mm`
- `physical_depth_mm`
- `volume_ml`
- `scale_evidence_source`
- `scale_confidence`

If authored physical evidence is absent, scale remains `UNVERIFIED`; pixel
bounding boxes are never converted into physical dimensions.

Reference-pack approval and generated-output approval are separate states:

1. `REFERENCE_PACK_APPROVED`
2. `GENERATED_OUTPUT_MACHINE_CHECKED`
3. `GENERATED_OUTPUT_HUMAN_APPROVED`

Machine QA only flags identity, label, logo, geometry and scale findings. It does
not approve a generated poster.

## Phase 1B bounded benchmark proposal — authorization required

| Parameter | Proposed value |
| --- | --- |
| Provider/model | Google Flow image transport / `NANO_BANANA_2` (`NARWHAL` mapping) |
| Test product | `6483d624-a03d-4933-9bba-6ca2e5f7b6fd` — Minyak Warisan Cap Burung 25ml |
| Requested outputs | `3` controlled variants |
| Maximum provider operations | `3` |
| Maximum retry operations | `0` |
| Hidden retries | forbidden |
| Estimated credit exposure | `UNVERIFIED` until the provider/account exposes pricing |
| Approval required before submit | explicit owner authorization for this exact bound |

The benchmark must capture every returned artifact, every provider operation ID
when available, transport batch correlation when an operation ID is absent, the
compiled prompt fingerprint, reference-role order, machine QA result and a human
review decision. Creative Campaign persists one `image_generation_operation` row
per bounded provider submit before artifact download; its local provenance id is
separate from `provider_operation_id`. A missing provider operation ID is an
observation gap, not a success claim.

## Decision

Phase 1A is complete. The implementation may proceed behind the feature flag.
Phase 1B and any production-default change remain pending explicit bounded credit
authorization and artifact-based acceptance.
