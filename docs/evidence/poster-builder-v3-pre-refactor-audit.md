# Poster Builder V3 — Pre-refactor Audit

Date: 2026-08-08
Branch: `codex/poster-builder-v3-a-hybrid-20260808`
Audit base: `5ff969cf78fa2e1a6f621ceb9be87b3519a88c93`
Scope: PR-A hybrid Creative Campaign architecture only

## Boundary and safety

- The worktree is isolated from the owner checkout and was created from the
  current `origin/main` SHA above.
- The owner checkout was dirty before this work began; its changes were not
  reset, cleaned, stashed, overwritten, or pulled across.
- No provider operation, database mutation, live benchmark, or credit spend was
  performed for this audit.
- The Creative Campaign feature flag remains governed by the existing backend
  flag and its production-default switch remains false.
- Exact Commerce and its deterministic product-truth save gate are out of scope
  for weakening or replacement.

## Graph/dependency evidence

No `graphify-out/` directory exists at this base. The dependency graph below is
therefore a manual source map derived from imports, route calls, and the focused
tests; it is not presented as a generated graph artifact.

```text
Poster Guided workflow
  -> createPosterPromptDraft (copy/readiness preflight)
  -> compileCreativeCampaignPrompt
       -> resolve_image_creative_context
       -> Product Reference Pack resolver
       -> image_prompt_compiler (nine sections)
  -> POST /api/flow/generate
       -> _apply_img_product_truth_gate
       -> make_video.start_generate
       -> Google Flow transport
       -> generated artifact/media id
  -> current Campaign save path: saveImgOutputToLibrary(raw media)

Exact Poster path
  -> POST /api/poster/compose
       -> PosterDeliverableService.compose_poster
       -> poster_template_service/build_render_manifest
       -> poster_compositor_service / Chromium renderer
       -> PosterDeliverableService.save_to_library
       -> exact product-truth and hash gates
```

The PR-A target is to make the Campaign path converge on the second path after
provider generation, while retaining the provider-generated key visual as
background lineage and never treating it as the final poster by itself.

## Current Poster Builder Campaign flow (observed in source)

`dashboard/src/poster/guided/usePosterGuidedWorkflow.ts` currently:

1. Builds an approved-copy-bound poster prompt draft.
2. Calls `compileCreativeCampaignPrompt` with `output_intent: COMPLETE_POSTER`.
   The request includes the actual headline, support line, proof points, and
   CTA in `copy_layout`.
3. Submits `/api/flow/generate` with:
   - `visual_lane_id: POSTER_BUILDER_CREATIVE_CAMPAIGN`;
   - `creative_mode: CREATIVE_CAMPAIGN`;
   - `image_model: NANO_BANANA_2`;
   - `output_intent: COMPLETE_POSTER`;
   - the Product Reference Pack id and bounded operation fields.
4. Stores the returned media id as `generatedSceneMediaId`.
5. Campaign `compose()` only advances the UI and does not call `composePoster`.
6. Campaign `save()` calls `saveImgOutputToLibrary` with the raw provider media
   under `PRODUCT_POSTER`.

## Current backend/provider boundary

`agent/api/flow.py` has the shared `/api/flow/generate` door and the
`_apply_img_product_truth_gate`. For Campaign it server-resolves product roles
from the Product Reference Pack before transport. The live gate already bounds
confirmation, variant count, retry count, compiler version, and provider
operation budget. The gap is semantic: it does not currently require the
Poster Builder Campaign request to be a clean key visual, nor does the client
route the result through the deterministic poster deliverable boundary.

`agent/services/image_prompt_compiler.py` already supports
`CLEAN_KEY_VISUAL` and suppresses marketing copy for that intent. It also emits
the nine canonical image sections, product identity constraints, physical-scale
evidence status, and the warning that generated output needs separate machine
and human review.

## Current save/composition governance

`agent/services/poster_deliverable_service.py` is the authoritative exact
poster boundary. It resolves the real product/copy set, builds one manifest,
renders with the local Chromium compositor, computes a hash, and on save
re-reads the exact bytes, checks QA, copy approval, hash identity, and product
lineage before creating the Creative Library asset. This gate must remain
intact.

The Campaign raw-save path bypasses that deliverable boundary. It therefore
cannot prove that a complete poster was deterministically composed, and it
mislabels a provider result as the terminal poster asset even though provider
identity/geometry/scale remain unverified.

## PR-A correction contract

PR-A will make these changes only:

- Compile and submit `CLEAN_KEY_VISUAL` for Poster Builder Creative Campaign.
- Do not place marketing copy in the provider prompt; send only typed copy-space
  direction/line-budget metadata needed for the clean visual.
- Use the final Campaign model selection `NANO_BANANA_PRO`; retain Nano Banana 2
  as preview/diagnostic-only where the existing model registry requires it.
- After a returned KV, call the existing deterministic `composePoster` path and
  create a `poster_deliverable` whose background lineage is the KV media id.
- Save only the composed deliverable through the existing exact hash/QA gate.
- Give Campaign assets explicit reference-conditioned review governance:
  `CAMPAIGN_POSTER_REFERENCE_CONDITIONED`, `PENDING_HUMAN_REVIEW`,
  `approved_for_poster=false`, and unverified identity/scale status. This must
  not alter Exact Commerce governance.
- Add focused zero-spend tests for prompt exclusion, model/intent contract,
  compose-before-save ordering, raw-KV save rejection, and provenance.

## Explicit non-goals

- No extension or transport rewrite without evidence that approved references
  fail to reach the provider.
- No provider capability claim beyond `SUPPORTED` transport contract or
  `UNPROVEN` generated behavior until the later bounded benchmark.
- No production-default feature-flag flip.
- No hidden retries, unbounded variants, DB backfill, or live UAT in PR-A.
