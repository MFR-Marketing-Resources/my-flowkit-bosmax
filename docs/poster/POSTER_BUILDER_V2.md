# Poster Builder V2 — Poster-Native Copy + Deterministic Compositor

End-to-end redesign (POSTER_BUILDER_V2): the Poster Builder now guides an
operator with zero copywriting/design knowledge from product → AI-assisted
poster-native copy → clean scene generation → deterministic text compositing →
QA → durable save in the Creative Library.

## Operator flow

1. **Product** — readiness gate (unchanged).
2. **Objective** — 6 archetype recipes; "Cadangkan untuk saya ✦" ranks them for
   the product (deterministic signals + optional grounded AI rerank).
3. **Angle & Copy (AI)** — recommended selling angles → 3 poster-native copy
   directions (grounded; provider-agnostic `text_assist` lane; deterministic
   fallbacks when unconfigured) → edit / regenerate ONE field → approve as a
   reusable, versioned **Poster Copy Set**.
4. **Visual settings** — controlled dropdowns (unchanged) + flow-mirror.
5. **Prompt package** — recipe path now emits a **CLEAN SCENE** prompt: the
   image engine must render product + scene with the product's own label
   preserved and ZERO marketing typography (negative prompt reinforces).
6. **Generate scene** — the proven one-door IMG lane, confirm-modal gated.
7. **Compose (deterministic, credit-free)** — Chromium compositor draws the
   marketing text/chips/CTA/disclaimer from the render manifest; shrink-to-fit;
   product-safe region enforced; deterministic QA (overflow / overlap /
   missing-element / dimensions) with BLOCK/WARN findings.
8. **Save** — exact previewed bytes (sha256-verified) registered as a
   `creative_asset` (PRODUCT_POSTER governance) + durable `poster_deliverable`
   row (manifest + copy-set ref + QA) for reconstruction after the 48h
   artifact purge.

## Domain contracts

- **poster_copy_set** (new table): poster-NATIVE fields
  (objective/archetype/angle/primary_message/support_message/proof_points/
  offer[reserved]/cta/disclaimer/tone/language/variants/field_provenance/
  ai_model/prompt_version), statuses `POSTER_COPY_*`, explicit approval phrase
  `APPROVE_POSTER_COPY_SET`, version-on-edit-of-approved (parent →
  SUPERSEDED). **Fully separate from the video `copy_set` table** — poster copy
  can never enter video selection/compilation (tested invariant).
- **POSTER_TEMPLATE_TOKENS.yaml** (new authority): font tokens, component
  styles (chip pill / CTA button / disclaimer), fit policy, per-recipe
  `product_safe_region` + palette. Recipes stay the zone-map authority;
  tokens make them production templates. lru-cached → restart to deploy.
- **poster-render-manifest-v1**: the single compositor input — exact strings,
  resolved tokens, product layer (strategy + safe region), provenance
  (copy set id/version, recipe, template version, models). Persisted on the
  deliverable for reconstruction and preview/save identity.
- **poster_deliverable** (new table): manifest + background + output path +
  sha256 + QA + creative_asset link; `POSTER_DRAFT → POSTER_COMPOSED →
  POSTER_SAVED`.

## Composition strategy (V1 decision)

`REFERENCE_CONDITIONED` for all archetypes: the proven subjectAsset reference
lane + product-truth lock anchors the product in the generated scene. Exact
pixel-level product preservation (`DETERMINISTIC_COMPOSITE`) is reserved in the
manifest enum but NOT implemented — the repo has no cutout/matting capability
and adding one was not justified for V1. Product identity in generated scenes
therefore remains reference-conditioned, honestly labelled, and subject to
human review.

## OFFER policy (V1 decision)

Non-price promotional creative only. `OFFER_PRICE_CLAIM_UNSUPPORTED` BLOCKS
numeric price/discount/voucher copy on the OFFER archetype until a real
OfferSpec + offer-truth source exists (`offer_json` column reserved).

## Runtime

Compositor: `scripts/poster-compositor-render.js` (Playwright/Chromium,
offline, credit-free, watchdog + structured exit codes) driven by
`poster_compositor_service` (semaphore=2, 45s timeout, structured errors).
Probe: `GET /api/poster/compositor/probe`. Fonts: system stack (BM is
Latin-script; no bundling/licensing needed). Fixtures:
`python scripts/generate_poster_fixtures.py` renders all 6 archetypes and
records machine-checkable reports (committed).

## Validation

- `python -m pytest tests/unit/test_poster_*.py tests/api/test_poster_*.py tests/ui/test_poster_*.py -q`
- `cd dashboard && npm run build && npx vitest run`
- `npx tsx scripts/mandor-check.ts`
- `scripts/verify-gate.ps1`
