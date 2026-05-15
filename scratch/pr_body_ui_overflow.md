## Root Cause
- LONG_TOKEN_NO_WRAP
- GRID_CHILD_MISSING_MIN_WIDTH_0
- FLEX_ROW_NO_WRAP
- WARNING_LIST_NOT_STRUCTURED
- PROVENANCE_RENDERED_INLINE
- JSON_BLOCK_NOT_SCROLL_SAFE
- RESPONSIVE_BREAKPOINT_MISSING
- SIDE_PANEL_WIDTH_UNSUPPORTED

## Affected Routes Audited
- `/`
- `/operator/t2v`
- `/operator/f2v`
- `/operator/i2v`
- `/operator/img`
- `/batches`
- `/asset-registry`
- `/product-asset-generator`
- `/products`
- `/projects`
- `/gallery`
- `/logs`
- `/prompt-preview`
- `/settings`
- `/health`
- `/troubleshoot`
- side portal mode via `/operator?portal=side`

## Files Changed
- `dashboard/src/index.css`
- `dashboard/src/App.tsx`
- `dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx`
- `dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx`
- `dashboard/src/components/prompt-preview/PromptPreviewResultPanel.tsx`
- `dashboard/src/pages/PromptPreviewPage.tsx`
- `dashboard/src/pages/ProductsSalesAnalyzerPage.tsx`
- `dashboard/src/components/asset-registry/AssetDetailPanel.tsx`
- `dashboard/src/components/asset-registry/AssetOptionsTable.tsx`
- `dashboard/src/pages/AssetRegistryPage.tsx`
- `dashboard/src/components/workspace/SearchableProductSelect.tsx`
- `dashboard/src/pages/DashboardPage.tsx`
- `tests/ui/test_dashboard_layout_overflow_contract.py`
- `tests/ui/test_prompt_preview_ui_contract.py`
- `tests/ui/test_products_sales_analyzer_ui_contract.py`
- `tests/ui/test_asset_registry_ui_contract.py`
- `tests/ui/test_product_asset_generator_ui_contract.py`
- `tests/ui/test_product_readiness_profile_ui_contract.py`

## CSS / Layout Utilities Added
- Added global wrap-safe utilities for dynamic operator data:
  - `.bosmax-wrap-safe`
  - `.bosmax-pre-wrap-safe`
  - `.bosmax-json-block`
  - `.bosmax-auto-fit-grid`
  - `.bosmax-warning-list`
  - `.bosmax-warning-chip`
  - `.bosmax-provenance-list`
  - `.bosmax-kv-row`
  - `.bosmax-kv-label`
  - `.bosmax-kv-value`
- Propagated `min-w-0` through app shell and critical grid/flex children.
- Replaced fragile narrow layouts with safer auto-fit or larger responsive splits where needed.

## Warning / Provenance Display Changes
- Product Asset Generator warnings now render as stacked wrap-safe chips/list rows.
- Product Asset Generator provenance now renders as structured key/value rows instead of a single inline run-on string.
- Prompt Preview result warnings and provenance now use wrap-safe structured containers.
- Asset Registry warning/provenance surfaces now use wrap-safe structured containers.
- Products / Sales Analyzer key detail rows now use wrap-safe key/value structure and no longer rely on single-line truncation for critical data like shop names and intelligence fields.

## Product Asset Generator Screenshot Issue Addressed
- The original overlap source was in the Product Readiness / Product Asset Generator result and profile cards where long warning strings, provenance strings, prompt text, and product-physics text were rendered inside narrow grids without wrap-safe containers.
- This PR hardens:
  - Product Truth Warnings
  - Preview Constraints
  - Provenance
  - Product Scale Prompt
  - Product Handling
  - Product Physics
  - Cinematic Camera Prompt
  - UGC iPhone Raw Camera Lock
  - Scale Warning
- Cards now expand naturally and long technical strings wrap inside the card instead of bleeding into adjacent columns.

## Validation Output
- `pytest tests/ui/test_dashboard_layout_overflow_contract.py -q` -> `2 passed in 0.55s`
- `pytest tests/ui/test_product_asset_generator_ui_contract.py -q` -> `6 passed in 0.85s`
- `pytest tests/ui/test_product_readiness_profile_ui_contract.py -q` -> `7 passed in 0.90s`
- `pytest tests/ui/test_prompt_preview_ui_contract.py -q` -> `2 passed in 0.54s`
- `pytest tests/ui/test_products_sales_analyzer_ui_contract.py -q` -> `2 passed in 0.59s`
- `pytest tests/ui/test_asset_registry_ui_contract.py -q` -> `2 passed in 0.55s`

## Dashboard Build Output
- `cd dashboard && npm run build` -> PASS
- `vite v8.0.3`
- `built in 3.57s`
- residual warnings only:
  - `PLUGIN_TIMINGS` warning for `rolldown:vite-resolve`
  - Vite chunk-size warning after minification

## Runtime Route Proof
- After `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local-agent.ps1 -ForceRestart`:
  - `GET /health` -> `200`
  - `GET /product-asset-generator` -> `200`
  - `GET /prompt-preview` -> `200`
  - `GET /products` -> `200`
  - `GET /asset-registry` -> `200`
- Note: immediately after restart there was a short startup race where early requests saw `connection closed` / `actively refused`; after service warm-up the route checks stabilized at `200`.

## Browser Visual Proof / Limitation Disclosure
- Browser visual proof did **not** complete.
- Exact limitation:
  - `MCP_DOCKER/browser_eval` with `action=start` returned:
  - `Failed to install @playwright/mcp: Error: spawn /bin/sh ENOENT`
- This PR does **not** claim browser/Playwright visual smoke passed.
- Current proof basis is:
  - source-level UI contract tests
  - dashboard production build
  - runtime route availability
- Manual visual confirmation is still recommended before merge for:
  - `/product-asset-generator`
  - `/prompt-preview`
  - `/products`
  - `/asset-registry`
  - `/operator?portal=side`

## Confirmations
- No backend product intelligence change
- No copywriting change
- No product physics change
- No Google Flow automation
- No Generate click
- No upload patch
- No `content-flow-dom` runtime logic change
- No batch execution
- No package/schema change
- CODING SCOPE: GLOBAL_DASHBOARD_UI_OVERFLOW_RESPONSIVE_AUDIT_ONLY
