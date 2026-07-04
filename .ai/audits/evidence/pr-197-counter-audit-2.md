# PR #197 — Counter-Audit Evidence Pack

Branch: `fix/product-pipeline-wiring-read-model-v1`

This pack summarizes the runtime / browser / test proof captured while closing the
counter-audit HOLDs on the Product Truth Gateway repair. All runtime proof is
read-only or against a **copy** of the database; the operator's live `:8100`
agent was never modified.

## Semantic fix — DUPLICATE_LINKED preview now agrees with the read model

Before: `agent/services/product_asset_generator_service.py` mapped
`product_state == DUPLICATE_LINKED` to `PRODUCT_NOT_YET_CANONICAL`, contradicting
the read model which resolves a duplicate-linked row to its linked canonical
product.

After: `_resolve_product_seed` trusts the gateway's own signals — when
`resolve_product_state(product_id)` returns `preview_resolvable == True`,
`canonical_status == "CANONICAL"` and a `product_id`, the preview loads THAT
canonical product row as the seed. This also unifies the `reference_id ->
committed canonical` case. Reference-only, ready-for-approval, pending-draft,
blocked and runtime-storage-unverified states remain fail-closed.

## Commands

```bash
# targeted suite (counter-audit list + read-model/diagnostic/catalog extras)
python -m pytest \
  tests/api/test_fastmoss_bulk_api.py tests/api/test_product_asset_generator_api.py \
  tests/unit/test_fastmoss_bulk_promotion_service.py tests/unit/test_product_registration_commit_service.py \
  tests/ui/test_product_registration_ui_contract.py tests/ui/test_products_sales_analyzer_ui_contract.py \
  tests/ui/test_product_asset_generator_ui_contract.py tests/ui/test_prompt_tool_authority_hydration_contract.py \
  tests/unit/test_product_catalog_read_model.py tests/unit/test_product_asset_generator_state_aware_preview.py \
  tests/ui/test_prompt_tool_catalog_fallback_contract.py \
  tests/unit/test_product_catalog.py tests/api/test_fastmoss_product_visibility_api.py \
  tests/ui/test_fastmoss_product_visibility_ui_contract.py \
  tests/api/test_product_catalog_state_api.py tests/api/test_runtime_storage_diagnostic_api.py -q
# => 188 passed

npx tsx scripts/mandor-check.ts        # => PASS_MODULE_STATUS_DOMAIN_RESOLVED domain=workspace
cd dashboard && npm run build          # => clean (tsc -b && vite build)
python scripts/doctor-runtime-storage.py   # => products=508 queue=298, exit 0
```

## Runtime proof (read-only, real 508-product checkout DB)

```
DUPLICATE_LINKED preview seed:
  fastmoss-ref:f99738ce48441410 -> product_state=DUPLICATE_LINKED
    linked_product_id=canonical-simba-cat-food  canonical_status=CANONICAL
    preview_resolvable=True  production_allowed=True
  Product Asset Generator preview(product_id=fastmoss-ref:f99738...) now loads
  canonical-simba-cat-food as the seed (no PRODUCT_NOT_YET_CANONICAL).

reference_id -> canonical fallback:
  fastmoss-ref:baa894e25661fa75 -> APPROVED_CANONICAL product_id=ef9c117e-...

runtime-storage diagnostic (honest counts):
  product_count=508  canonical_product_count=508
  authority_context_count_ceiling=508
  authority_context_count=None  source=NOT_COMPUTED   (default)
  ?include_authority_context_count=true -> authority_context_count=508
    source=bosmax_authority_registry.get_prompt_tool_context   (== product count)

/api/products rows carry catalog_state:
  <uuid> -> catalog_state.product_state=APPROVED_CANONICAL production_allowed=True
  fastmoss-ref:* -> catalog_state.product_state=REFERENCE_ONLY production_allowed=False
```

## Browser proof (parallel agent on a DB copy, host.docker.internal:8123)

- **Products / Sales Analyzer** — populated: `READY: 298`, real product row, Source Lane FASTMOSS.
- **Smart Registration → Bulk FastMoss Convert** — `APPROVED: 203, CLAIM_RISK: 43, DUPLICATE_LINKED: 2, READY_FOR_APPROVAL: 21, Total: 298`; SIMBA row shows "LINKED TO PRODUCT TRUTH → canonical-simba-cat-food".
- **Product Asset Generator** — "Preview is offline-only · No real image generation · No Google Flow execution · No Chrome extension execution", "PRESET GUIDED WORKFLOW — ACTIVE PRESET:", `DRY_RUN_ONLY=TRUE`, product_id-preview-authority / reference-only boundary helper.
- Startup banner logged live: `RUNTIME_STORAGE base_dir=… db=… products=508 queue=298`.
- Console errors are pre-existing/benign (`/api/fastmoss/import-batch/latest` 404; extension WS 403 = AGENT OFFLINE).

## Notes

- MCP Playwright browser is containerized — reach the host via
  `http://host.docker.internal:<port>` (127.0.0.1 gives ERR_CONNECTION_REFUSED).
- No product/queue data deleted, no migration, no generation, no credit spend.
