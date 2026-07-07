# Poster / Creative Cockpit Settings SSOT V1

Layered on top of the merged Poster Module (docs/poster/POSTER_MODULE_END_TO_END_V1.md,
PRs #253–#255). This adds a **single source of truth** for the poster builder
settings, a **read-only cockpit page**, and a production-ready **Auto mode**.

## Why

Real runtime testing of the #255 Poster Builder surfaced four issues. Root causes:

1. **"API 405" on copy-recommendations was a stale running agent, not a code bug.**
   The frontend POSTs `/api/poster/copy-recommendations`; the backend defines
   exactly `@router.post("/copy-recommendations")` (router `prefix="/poster"`,
   mounted at `/api`). Path + method match on disk. A running agent that predates
   #254/#255 lacks the route, and the SPA catch-all `@app.get("/{full_path:path}")`
   matches the POST path as GET-only → **405**. Fix = rebuild `dashboard/dist` +
   restart the agent. No route code change.
2. **Objective / Poster Type / Language were free-text inputs** with no option
   list anywhere, and copy-draft fields (angle/hook/subhook/usp/cta) were editable
   only in Manual mode.
3. **No canonical settings surface.** The existing "Prompt Preview" page is the
   ADR-008 **frozen** offline video-prompt pipeline ("do NOT repair it") — not a
   builder cockpit. Reviving it would violate ADR-008.
4. **Hidden AI token spend:** `poster_copy_recommendation_service` fired the AI
   lane on `refresh_ai OR not kits`, so auto-load spent tokens for any product
   without copy sets when a provider was configured.

## What shipped

### Backend — builder-settings SSOT
- `GET /api/poster/builder-settings` (`agent/api/poster_prompt.py`) →
  `PosterBuilderSettingsResponse` (`agent/models/poster_builder_settings.py`).
- `agent/services/poster_builder_settings_service.py` owns the canonical
  poster-dimension option lists and **composes existing SSOTs** — it does not
  duplicate them:
  - `flow_mirror` ← `build_image_gen_settings()` (extracted into
    `agent/services/img_asset_factory_service.py`; the `/img-factory/image-gen-settings`
    route now delegates to it, output unchanged).
  - `copy_components` ← copy-signal routes (`DIRECT/STEALTH/REVIEW_REQUIRED`) +
    copy-landbank presence. Copy sets/kits stay product-scoped
    (`GET /api/copy-sets/product/{id}`).
  - `ai_provider` ← `ai_copy_provider_adapter.provider_status()` (masked; no keys).
- Each option's `id` **is the exact string the poster draft submits**
  (`value=id`). The seed defaults equal today's draft defaults, so the
  prompt-draft / copy-recommendation contract stays byte-identical.

### Backend — AI-spend guardrail
- `agent/services/poster_copy_recommendation_service.py`: AI candidate generation
  now fires **only on explicit `refresh_ai=True`**. Products without copy sets
  fall through to deterministic fallback templates — no hidden token/credit spend.

### Frontend
- `dashboard/src/api/posterBuilderSettings.ts` — `usePosterBuilderSettings()`
  hook mirroring `imageGenSettings.ts`, with a `*_FALLBACK` so dropdowns work
  even against a stale/older agent.
- `PosterAutoModePanel.tsx` — Objective/Poster Type/Language are `<select>`s from
  the SSOT; **always-visible** copy-draft fields (angle/hook/subhook/usp1-3/cta);
  a dedicated **AI Copy Assist** section (Generate/Regenerate = explicit
  `refresh_ai=true`; per-candidate **Apply suggestion** fills the visible fields);
  a primary **Generate poster prompt draft** button using the visible fields.
  Copy-draft fields remain usable when recommendations fail.
- `CockpitSettingsPage.tsx` at `/creative/cockpit-settings` — read-only SSOT view
  of every dimension, Flow Mirror, copy components, and AI status, each tagged
  with its source (config / models.json / ai_provider / fallback). It consumes the
  **same** hook the Poster Builder uses, so the two cannot drift. The frozen
  Prompt Preview page is intentionally untouched.

## Behaviour notes
- The Auto-load on product-select still runs (deterministic copy-set + fallback
  kits) but now passes `refresh_ai=false`, which — after the guardrail — never
  calls the AI provider. Only the AI Copy Assist button spends tokens.
- Image generation stays hard-disabled (handoff-only); no product mutation; no
  auto claim clearance.

## Verify
```
python scripts/verify_poster_target_products.py
python -m pytest tests/unit/test_poster_builder_settings_service.py \
  tests/api/test_poster_builder_settings_api.py \
  tests/unit/test_poster_copy_recommendation_service.py -q
cd dashboard && npm test && npm run build
```
Runtime: rebuild `dashboard/dist`, restart the agent, then
`GET /api/poster/builder-settings` returns 200 and the copy-recommendations 405
is gone. Browse `/creative/poster-builder?product_id=<uuid>` (dropdowns, copy
fields, AI assist, image-gen disabled) and `/creative/cockpit-settings`.
