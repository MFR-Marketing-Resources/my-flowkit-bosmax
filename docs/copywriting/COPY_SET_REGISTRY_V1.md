# Copywriting Set Registry V1

A dedicated, product-scoped page to register/manage **copywriting sets** (Angle →
Hook → Subhook → USP×3 → CTA), AI-generated on demand, reused across the builders.

## Why

Operators wanted one place to: pick a product → press **Generate** → AI (DeepSeek)
fills complete copywriting sets → CRUD → the approved sets feed Poster Builder,
image/poster, and video generation (T2V/F2V/Hybrid/I2V). The functionality mostly
existed already (the `copy_set` feature) but was **buried** (AI-assist inside
Poster Builder, `CopySelectionPanel` inside the Operator video flow) with no
discoverable registry and no delete. This adds the missing surface **without a
parallel database** — it reuses `copy_set` end-to-end.

Model decision: **assembled-set** (one `copy_set` row = one full "MAPPING" row),
not a separate component bank. Every downstream consumer already expects this.

## What shipped

- **Backend:** one new route `DELETE /api/copy-sets/{copy_set_id}` →
  `copy_set_service.delete_copy_set` → `crud.delete_copy_set` (hard delete; 404 if
  missing). `reject` remains the soft option, so the lifecycle now has full CRUD.
- **Frontend client** (`dashboard/src/api/copySets.ts`): `generateCopySetBatch`
  (POST `/api/copy-sets/generate-batch`) and `deleteCopySet` (DELETE) + batch TS
  types in `types/index.ts`.
- **New page** `dashboard/src/pages/CopySetRegistryPage.tsx` at
  `/creative/copy-registry`:
  - `SearchableProductSelect` (product-scoped). On product change it only **reads**
    (`listCopySetsForProduct`) — **no AI on select**.
  - **"Generate 5 sets (AI)"** → `generateCopySetBatch({product_id, requested_count: 5})`
    (backend default 5, range 3–10). Press again for +5. Sets arrive as
    `COPY_REVIEW_REQUIRED` (never auto-approved). 409 → friendly "AI lane not
    configured" message; rows stay visible.
  - **"Add 1 (no AI)"** → `generateCopySet` (deterministic landbank/signal, zero
    tokens).
  - `DataTable<CopySet>` with status `Badge`, client-side status filter, and row
    actions: **Edit** (modal → `patchCopySet`), **Approve** (`approveCopySet`,
    phrase auto-injected), **Reject** (note → `rejectCopySet`), **Delete**
    (`ConfirmActionModal` type-to-confirm → `deleteCopySet`).

## Reuse (no reinvention)

- AI generate-N: `POST /api/copy-sets/generate-batch` → `ai_copy_assist_service`
  → `ai_copy_provider_adapter.generate_candidate` (DeepSeek `text_assist`),
  fail-closed 409 if the lane is unconfigured, `scan_copy_safety` filter, dedupe +
  `copy_generation_batch` ledger.
- Lifecycle: `PATCH` / `approve` (phrase `APPROVE_COPY_SET`, blocks unsafe/incomplete
  at 422) / `reject` / `regenerate` / `GET /product/{id}`.
- Shared UI: `components/ui/*` (Section/FormField/HelperText/Badge/DataTable/
  ConfirmActionModal); `SearchableProductSelect`.

## Downstream (already wired — no new work)

Approved sets auto-appear in Poster Builder recommendations, and bind into the
video compiler via `copy_binding_service.resolve_compiler_copy_intelligence`
(operator selects the `copy_set_id` in `CopySelectionPanel` on the Operator page).
The registry's job is to **produce + approve** sets; consumption already exists.

## Guardrails

Reuse `copy_set` (no parallel DB) · AI spend is **click-only, never on product
select**, and fail-closed if the lane is unconfigured · approve stays phrase-gated
and unsafe-blocked · no product mutation · no image/video generation from this page.

## Verify

```
python -m pytest tests/api/test_copy_sets_api.py tests/unit/test_copy_set_service.py -q
cd dashboard && npm test && npm run build
npx tsx scripts/mandor-check.ts
```
Runtime (`:8100`, after rebuild + restart): `DELETE /api/copy-sets/{id}` in OpenAPI;
`/creative/copy-registry` picks a product, **Generate 5** creates review-required
sets (real DeepSeek, explicit click), Edit/Approve/Reject/Delete work, Delete needs
the phrase; an approved set then appears in Poster Builder recommendations.
