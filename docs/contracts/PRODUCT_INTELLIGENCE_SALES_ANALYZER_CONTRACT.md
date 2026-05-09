# Product Intelligence Sales Analyzer Contract

## Scope

The Products / Sales Analyzer module is the system of record for product-side creative readiness.
It exists to normalize source data before any operator or generation workflow consumes a product.

## Canonical Product Fields

Every product detail response must expose or preserve these fields:

- `id`
- `product_id`
- `source`
- `source_url`
- `raw_product_title`
- `product_display_name`
- `product_short_name`
- `brand`
- `category`
- `subcategory`
- `type`
- `price`
- `currency`
- `commission_amount`
- `commission_rate`
- `image_url`
- `local_image_path`
- `image_asset_status`
- `mapping_source`
- `mapping_confidence`
- `mapping_review_status`
- `prompt_readiness_status`
- `prompt_missing_fields`
- `created_at`
- `updated_at`

## Source Rules

Allowed `source` values:

- `FASTMOSS`
- `TIKTOKSHOP`
- `MANUAL`
- `IMPORTED`

Compatibility rule:

- legacy `MANUAL_PROJECT` rows must be normalized to `MANUAL` during migration or serialization.

## Analyzer Responsibilities

The module must:

- list and search products through `GET /api/products` and `GET /api/products/search`
- return enriched detail through `GET /api/products/{product_id}`
- expose mapping via `GET /api/products/{product_id}/mapping`
- expose physics DNA via `GET /api/products/{product_id}/physics`
- create manual products via `POST /api/products/manual`
- patch normalized product metadata via `PATCH /api/products/{product_id}`
- register TikTok Shop URLs via `POST /api/products/import-tiktokshop`
- never fabricate scraped TikTok Shop price, commission, image, or title data

## TikTok Shop Honesty Rule

If TikTok Shop extraction is not implemented:

- the API must return `TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED`
- the response must declare `manual_entry_required: true`
- the system may create a draft row only when it is clearly marked as a draft and not presented as extracted truth

## Readiness Rules

`prompt_readiness_status` values:

- `READY`
- `NEEDS_REVIEW`
- `MISSING_FIELDS`

Readiness must consider at minimum:

- canonical product naming
- category, subcategory, and type
- image presence via `image_url` or `local_image_path`
- copywriting angle
- claim risk level
- physics class
- section 5 physics prompt

## UI Requirements

The page must show:

- product catalog and filters
- source and readiness state
- product detail panel
- mapping and physics DNA details
- section 4, 5, 6, and 9 readiness helpers
- manual product intake
- TikTok Shop intake with honest fallback behavior

## Non-Goals

This module does not claim:

- first-video generation readiness by itself
- live TikTok Shop scraping
- fake extracted price or commission values
- automatic Google Flow upload proof for products without explicit asset actions
