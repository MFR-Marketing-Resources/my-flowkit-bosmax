# Product Mapping And Flow Naming Contract

## Canonical Mapping Fields

Every resolved product mapping must expose these fields:

- `product_id`
- `raw_product_title`
- `product_short_name`
- `category`
- `subcategory`
- `type`
- `product_type`
- `silo`
- `trigger_id`
- `formula`
- `mode_recommendations`
- `copywriting_angle`
- `claim_risk_level`
- `mapping_source`
- `mapping_confidence`

## Mapping Source Priority

Source priority is strict and deterministic:

1. Advanced override taxonomy supplied by the user.
2. FastMoss product data plus normalized keyword rules.
3. Manual product name plus normalized keyword rules.
4. Existing stored product taxonomy.
5. Fallback unresolved mapping.

`mapping_source` values:

- `FASTMOSS`: a FastMoss-backed product resolved the mapping.
- `MANUAL`: a manual product name or advanced override resolved the mapping.
- `FALLBACK`: no rule or usable stored taxonomy resolved the mapping.

## Fallback Rules

- Never default non-health products to `STEALTH`, `health_supp_stealth_01`, or `EGO_01`.
- If no rule matches, unresolved fields stay blank and `mapping_confidence` becomes `NEEDS_REVIEW`.
- Fallback responses must expose `missing_fields` so the operator can show exactly what needs review.
- Product type, silo, trigger, and formula are derived from canonical taxonomy profiles, not hard-coded UI defaults.

## Manual Override Rules

- Primary operator flow is: select product, inspect resolved mapping, generate.
- Category, subcategory, and type overrides are available only under `Advanced Override`.
- Manual product entry must use the same resolver as FastMoss products.
- Persisted manual products store canonical taxonomy on the product row so later resolutions do not require repeated user input.
- Overrides must visibly recompute product type, silo, trigger, and formula from the resulting taxonomy.

## Canonical Google Flow Labels

Primary UI labels must use these canonical names:

- `Images`
- `Ingredients`
- `Frames`
- `Text to Video`

Mode mapping:

- `IMG` / edit-image paths -> `Images`
- `GENERATE_VIDEO` / start-image video path -> `Ingredients`
- `GENERATE_VIDEO_REFS` / reference-image video path -> `Ingredients` or `Frames` only when that route is intentionally used as the frame-style path in this repo
- `TRUE_F2V` / explicit start-end frame path -> `Frames`
- direct text-to-video UI placeholder -> `Text to Video`

## Forbidden Labels

These labels must not appear in the primary operator or dashboard UI:

- `Generate Videos (I2V Start Image)`
- `Generate Videos (Ingredients / Refs)`
- `T2V via IMG+VID`
- `GEN VIDEO FROM REFS`
- arbitrary `STEALTH` defaults for non-health products

## Acceptance Criteria

- Product selection auto-resolves category, subcategory, and type.
- Product type, silo, trigger ID, and formula auto-fill from the resolved mapping.
- Manual overrides are hidden behind `Advanced Override`.
- FastMoss and manual products both resolve through the same mapping service.
- Dashboard and operator labels use `Images`, `Ingredients`, `Frames`, and `Text to Video`.
- Text to Video is rendered as `Generate Text to Video — NOT WIRED` until a native queue path exists.
- The contract file, mapping rules file, and mapping service remain the SSOT for this behavior.