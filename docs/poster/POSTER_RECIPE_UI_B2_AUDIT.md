# Poster Builder — PR B2 Recipe-First UI: Post-Merge Audit Note

Durable record of what PR B2 delivered and the explicit limits of its
verification. This is a local, self-authored audit note — **not** a CI artifact.

## Identifiers
- PR: [#278](https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/278)
- Head SHA: `eb9b94e9f27d0533955005022f791166a222e27e`
- Merge SHA: `4d14935e4512dafa2569a329a38ee2af7da6d07a`
- Final served bundle (at time of proof): `index-BWvSfFym.js`
- Evidence comment: PR #278 `issuecomment-4915079337`
- Screenshot (local, session scratchpad — not committed): `b2_recipe_first.png`
  (recipe-first viewport). The a11y snapshot excerpt below is the durable text
  artifact.

## What B2 delivered (recipe-first Poster Builder UI)
- `PosterRecipeSelector` — `GET /api/poster/recipes` archetype cards, shown
  **before** copy; copy slots hidden until a recipe is chosen.
- `PosterControlledSettings` — the 7 enum-like fields are SELECT dropdowns
  (never free text); text density constrained to `recipe.allowed_text_density`.
- `PosterRecipeSlotEditor` — copy slots from the selected recipe's zones
  (role / source_field / max_chars / placeholder / counter / over-warning),
  mapped onto canonical `hook/subhook/usp_1..3/cta`.
- `PosterSpecPreview` — renders `poster_spec` + `overlay_spec` with the
  Phase-2 disclaimer.
- Manual Expert enum fields converted to dropdowns; moved behind a collapsed
  `<details>` "Advanced / Legacy modes" disclosure — no longer the primary form.
- Draft `+= poster_recipe_id`; response `+= poster_spec/overlay_spec`
  (nullable-additive). PR A product-image anchor preserved; "✓ Product reference
  image confirmed" banner reuses it.

## Verification (local only)
```
npx vitest run src/pages/PosterBuilderPage.test.tsx   -> Tests 29 passed (25 existing + 4 B2)
scripts/verify-gate.ps1                                -> PASS (mandor, build, vitest, backend smoke) — LOCAL, not CI
npx biome check <13 changed files>                     -> exit 0
GET /api/poster/recipes                                -> 200 (3 recipes)
```

### Browser a11y snapshot excerpt (Chrome DevTools MCP, local :8100)
```
heading "1. Choose a poster recipe"                # BEFORE any copy
button "Product Hero — Night Routine ... SELECTED"
button "Heritage Infographic ..."
button "Product Scale / Portability ..."
"✓ Product reference image confirmed ..."
heading "2. Poster settings — Controlled options only ..."
combobox OBJECTIVE / POSTER TYPE / VISUAL ROUTE / HUMAN PRESENCE / FRAME RATIO / LANGUAGE / TEXT DENSITY (all SELECT)
  TEXT DENSITY options = [Low, Medium]             # recipe-constrained
heading "3. Recipe copy slots"
textbox HEADLINE 0/48 · SUBHEADLINE 0/72 · CHIP_1/2/3 0/36 · CTA 0/24
DisclosureTriangle "ADVANCED / LEGACY MODES (AUTO · GUIDED · MANUAL EXPERT)"
draft JSON -> "poster_recipe_id": "product_hero_night_routine"
```

## Explicit limits (do not overclaim)
- **No CI** ran on the head commit; all gates are LOCAL process control only.
- Browser proof is **verified locally by Claude; not independently attached as a
  CI/PR-checks artifact** (the a11y snapshot text above and the PR comment are the
  durable artifacts).
- **No live credit-spend render was run → LIVE PRODUCT VISUAL MATCH NOT
  VERIFIED.** No claim is made that a generated poster visually matches the
  product.
- `overlay_spec` is a **deterministic layout foundation only** — this is **not
  production-quality poster output**. A real HTML/SVG/canvas compositor is
  **Phase 2 and pending owner approval** (not started).

## Next (blocked on approval)
Phase 2 = deterministic compositor/renderer for crisp Malay headline / chips /
CTA / footer from `overlay_spec`. Architecture planning only after explicit owner
approval; no compositor coding until then.
