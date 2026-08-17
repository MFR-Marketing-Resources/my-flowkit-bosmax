# BOSMAX Product-Data Loading Contract

Status: enforced on `main` by source contracts, focused frontend tests, and the
verification gate.

Scope: every dashboard surface that reads product truth, a product selector, a
product registry/detail view, or a product-derived reporting label. This is a
read-path contract only. It does not authorize product-truth mutation, provider
calls, generation, or credit spending.

## Canonical read lanes

There are three supported read lanes:

1. **Generation selector lane** — `fetchProductCatalog(limit, purpose)` behind
   `useProductCatalog`. The default is `50` rows and `GENERATION` purpose. The
   shared cache is keyed by purpose and window, deduplicates concurrent requests,
   expires after 30 seconds, and evicts a failed promise.
2. **Registry lane** — `fetchProductRegistry(params)`, always sending
   `view=REGISTRY`, a bounded `limit`, an `offset`, and the complete server-side
   filter/sort query. Registry pages have their own 30-second cache keyed by the
   complete query string and the same in-flight/failed-request behavior.
3. **Exact-detail lane** — `fetchProductDetail(productId)`. A selector projection
   is never treated as the authoritative detail row. Deep links and product detail
   pages use this helper so image/readiness/grounding state is resolved explicitly.

`searchProducts` is the bounded server-search lane for searchable selectors. It
   is not a license to download the full catalog and filter it in the browser.
Taxonomy/strategy registries are metadata lanes and use their own bounded cache;
 they are not product-row catalog substitutes.

## Consumer matrix

The matrix is intentionally explicit. A row marked `canonical` is covered by the
static governance test and the relevant component/API tests. `redirected` means
the source remains for compatibility, but the route is not an active independent
surface. `exception` is an allowlisted bounded auxiliary read, not a selector
pattern to copy.

| Surface / consumer | Read contract | Search / page | Cache / invalidation | Images | Status |
| --- | --- | --- | --- | --- | --- |
| `/operator/hybrid` (`OperatorPage`) | `useProductCatalog(50, GENERATION)` | selector uses server search for long-tail names | shared selector cache; mutation boundaries invalidate | selected preview deferred; one bound detail preview | canonical |
| `/operator/faceless` (`FacelessVideoPage`) | `useProductCatalog(50, GENERATION)` | selector search | shared selector cache | deferred preview | canonical |
| `/operator/montage` (`MontagePage`) | `useProductCatalog(50, GENERATION)` | selector search | shared selector cache | deferred preview | canonical |
| `/approved-packages` | `useProductCatalog(50, GENERATION)` | selector search | shared selector cache | deferred preview | canonical |
| `/assets/avatar-registry` | `useProductCatalog(50, GENERATION)` | selector search | shared selector cache | deferred preview | canonical |
| `/creative/copy-registry` | `useProductCatalog(50, GENERATION)` | selector search | shared selector cache | deferred preview | canonical |
| `/creative/poster-builder` and guided poster shell | `useProductCatalog(50, GENERATION)` | selector search | shared selector cache | deferred preview | canonical |
| `/prompt-preview` prompt tool hydration | shared `fetchProductCatalog()` plus authority context | selector-specific UI; bounded initial window | shared selector cache | selector preview rules | canonical |
| `/product-registration` — All Products | `fetchProductRegistry`, `PAGE_SIZE=50`, `exclude_reference=true` | server q/facets, offset pagination | registry cache; reads do not invalidate | `LazyThumbnail`, IO root margin 160px + native lazy | canonical |
| `/product-registration?tab=bulk` | strategy taxonomy metadata cache plus bounded batch queue | batch workflow, not a full selector | mutation helper invalidates catalog cache | only workflow-required previews | canonical |
| `/product-registration?tab=single` | legacy `/review-drafts` queue | explicit workflow-only exception; not default mount | no catalog selector cache reuse | draft panel owns media lifecycle | exception; documented follow-up |
| `/products` Product Catalog / Product Intelligence | `fetchProductRegistry`, `PAGE_SIZE_PRODUCTS=20` | server q/facets/sort/offset; exact deep-link fallback | registry cache; all catalog-visible mutations call `invalidateProductCatalogCache()` before reload | table thumbnails IO/native lazy; review drafts behind lazy disclosure | canonical |
| `/product/:id` | `fetchProductDetail(id)` | exact id only | detail read; product patch invalidates shared catalog/registry cache | exact detail media only | canonical |
| `/production-studio` P6 cohort picker | `/api/creative-production/cohort-authority` with `limit=50`, `offset`, optional q | server q + bounded pagination; frozen authority IDs/SHA remain complete | request sequence guard; no product cache mutation | current page only; native lazy; selected rows retained by id | canonical |
| `/assets/product-type-registry` | strategy taxonomy registry | metadata filters only; no product-row catalog | strategy metadata cache | none | canonical metadata lane |
| `/workspace/jobs` | `fetchProductCatalog(500)` label map | no interactive product selector; telemetry is capped at 200 rows | explicit reporting/admin exception; no mutation | none | exception; allowlisted |
| `/workspace/generation-packages` | package endpoint (`limit=100`) | package rows are bounded; product ids are package metadata | package cache/endpoint contract | package-specific | exception; auxiliary package view |
| `/reporting/executive` and `/reporting/operations` | aggregate/reporting endpoints | aggregate coverage or operational metrics; no product-row selector | reporting endpoint contracts | none | no catalog consumer |
| `/operator/t2v`, `/operator/f2v`, `/operator/i2v` | redirect to `/operator/hybrid` | no independent loader | canonical destination owns cache | canonical destination owns images | redirected |
| `/operator/img`, `/assets/img-cockpit`, `/assets/img-fastlane` | redirect to `/creative/poster-builder` | no independent live route | canonical destination owns cache | canonical destination owns images | redirected |
| `/assets/scene-context-registry` | redirect to `/assets/creative-library` | no independent live route | canonical destination owns cache | canonical destination owns images | redirected |

### Explicit exceptions

The two `exception` rows are deliberate and bounded:

- `WorkspaceJobsPage` resolves labels for a capped telemetry/reporting window. Its
  `500` window is an allowlisted admin/reporting read and must not be reused for an
  interactive selector. If the reporting window grows, paginate the telemetry
  endpoint and resolve labels by page.
- The legacy single-registration workflow reads its review-draft queue only when
  an operator explicitly opens that tab. It is not part of the default All Products
  mount. A future draft-volume change must paginate that workflow before removing
  this exception.

The P6 cohort authority was previously an outlier: it returned the full frozen
cohort to the browser. It now keeps the complete authority identity (`product_ids`,
count, SHA) server-side in the response while returning a searchable 50-row browser
page. This makes the interactive picker bounded without changing the frozen
authority used by plan validation.

## Backend projection contract

`GET /api/products?view=REGISTRY` is the list/read projection. It must:

- apply filters, sort, total/facets, and offset/limit on the server;
- return only the requested page;
- use `_build_catalog_projection` and the provider-free registry projection;
- avoid full provider/enrichment work for rows outside the page;
- keep exact detail (`GET /api/products/{id}`) separate from list browsing; and
- serve local cached product images only from the image endpoint.

The list lane must remain provider-free and must never spend credits. Any change
to this contract requires a targeted backend test proving the registry path does
not call the full enricher.

## Images and object URLs

Product-row images are a second-stage concern. A consumer must first bound the row
payload, then defer image assignment near the viewport, and finally use native
`loading="lazy"`/`decoding="async"` where an image is rendered. Missing, failed,
and unavailable images remain truthful states; a remote URL is not silently
treated as a cached local asset.

Object URLs created for upload previews must be revoked on replacement and
unmount. Existing upload panels already own this lifecycle; this contract does
not justify speculative image rewrites without a reproducible leak or stale
preview defect.

## Cache correctness

Reads may use a warm entry. Product-truth mutations must invalidate before the
following read. In particular, `/products` mutation handlers must not call a bare
`loadProducts()` as their only refresh because registry pages are separately
cached. Ordinary search/filter/page reads must not invalidate the cache.

The shared helper is the only place that constructs catalog list URLs. New page
code must not introduce raw `/api/products?...` catalog fetches. A new consumer
must be added to this document and to the governance test in the same change.

## Permanent regression gates

The following are hard contracts:

- `tests/ui/test_product_data_loading_governance.py` — source-level consumer,
  exception, helper, backend projection, and bounded P6 contracts;
- API/client tests — cache key, dedupe, TTL, failed-promise eviction,
  registry pagination, exact-detail routing, and P6 query forwarding;
- focused Vitest tests — lazy thumbnails, selectors, P6 pagination, and mutation
  invalidation boundaries;
- `scripts/test-product-data-loading-network.mjs --fixture` — deterministic
  Playwright request/response capture covering shared selector reuse, registry
  paging/search, lazy review drafts, exact detail, mutation invalidation, and
  provider/giant-payload rejection; and
- live post-merge browser validation against the canonical runtime, where the
  same hard request/payload assertions are applied to the deployed app. Timing is
  recorded as an observation and is never the sole pass criterion.

The verification gate runs the governance test and the fixture network suite. The
live runtime suite is a separate post-merge proof because CI has no canonical
runtime authority or Product Truth permission.

## Developer note

When adding a product consumer, start with the lane that matches the UI contract:

```ts
useProductCatalog(50, "GENERATION"); // bounded selector
fetchProductRegistry({ limit: 20, offset: 0, q }); // server registry
fetchProductDetail(productId); // exact grounding/detail
```

Do not fetch `limit=500` for a selector, do not client-filter a giant response,
and do not treat an image URL as proof that the image is locally cached. Add the
route/component to this matrix, add a focused request-contract test, and run the
verification gate before opening the PR.
