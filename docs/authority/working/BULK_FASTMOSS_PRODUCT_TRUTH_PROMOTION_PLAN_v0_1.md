# BULK FASTMOSS PRODUCT TRUTH PROMOTION PLAN v0.1

## 1. Document Control

| Field | Value |
| --- | --- |
| `file_id` | `BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN` |
| `version` | `v0.1` |
| `status` | `APPROVED_FOR_IMPLEMENTATION_PLANNING` |
| `related_issue` | `#92 — Feature: Bulk FastMoss product truth promotion in Smart Registration` |
| `implementation_status` | `NO_CODING_INSIDE_THIS_FILE` |
| `repo` | `farisdatosheikh/my-flowkit-bosmax` |
| `decision_source` | `Issue #92 accepted architecture review + user planning authority` |
| `related_plan` | `docs/authority/working/SMART_REGISTRATION_COMPLETION_EDITOR_PLAN_v0_1.md` |

---

## 2. Executive Decision

The next Smart Registration production wave is:

```text
BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION
```

Scaled content generation requires a large canon of committed product truth rows. A typical FastMoss workbook
contains 200–1000 product reference rows. These references carry commercial intelligence (sold count,
commission rate, TikTok product URLs, categories) that is highly valuable for UGC creative generation —
but only after they are evaluated, cleaned, and promoted through a controlled approval gate into canonical
product truth.

Without bulk promotion, each FastMoss reference must be manually registered one at a time through the
existing single-product Smart Registration flow. At 200–1000 rows, this is not operationally viable. The
content generation pipeline is blocked behind product truth availability, and product truth availability is
blocked behind manual single-product intake.

This plan defines the architecture for a bulk FastMoss-to-product-truth pipeline that:

- Syncs FastMoss reference rows into a reviewable draft queue.
- Allows bulk draft generation with claim risk classification applied per row.
- Enforces governance gates: LOW risk rows may be bulk approved; MEDIUM and HIGH risk rows must be individually reviewed or rejected.
- Preserves full FastMoss lineage (reference ID, source URL, raw title, workbook provenance) on every promoted product.
- Integrates as a new tab inside the existing `ProductRegistrationPage` — no new top-level routes required.

---

## 3. Root Gap

### Why Single-Product Smart Registration Is Not Viable at Scale

The current Smart Registration flow requires an operator to:

1. Open the intake form.
2. Paste or type product information for one product.
3. Wait for completion snapshot.
4. Navigate to the review draft panel.
5. Review evidence, missing fields, and claim gate.
6. Approve all required review fields.
7. Enter the confirmation phrase.
8. Commit the product.

This is a single-threaded, 8-step, human-in-the-loop process per product. At 200 FastMoss rows, a full intake
run requires 1600+ manual interactions. At 1000 rows, the number becomes operationally impossible.

Additionally, FastMoss references are currently blocked at the source lane level:

```text
agent/services/registration_commit_service.py (lines 84–91):
  if draft.source_lane in {"FASTMOSS_REFERENCE", "FASTMOSS"}:
      blocked_reasons.append("SOURCE_LANE_NOT_ALLOWED_FOR_OWNED_COMMIT")
```

There is no upgrade path from `FASTMOSS_REFERENCE` → canonical product truth today. The bulk promotion
pipeline creates that upgrade path with appropriate governance.

---

## 4. Current Repo Surface

| Surface | Status | Evidence | Decision |
| --- | --- | --- | --- |
| `agent/models/fastmoss_import.py` — `FastMossImportBatchReport`, `FastMossImportFileReport` | Exists | `agent/models/fastmoss_import.py` lines 7–58 | Reuse as provenance source; do not modify |
| `agent/api/fastmoss_import.py` — import batch routes | Exists | Routes: `POST /import-batch`, `GET /import-batch/latest`, `GET /import-batch/{batch_id}` | Reuse as upstream batch provenance reference |
| `agent/services/fastmoss_product_reference_service.py` — reference ID, lane constants, `reference_only=True` enforcement | Exists | Lines 10–124: `FASTMOSS_REFERENCE_LANE`, `FASTMOSS_REFERENCE_BLOCKER`, `reference_only=True` | Extend: add promoted lane constant; do not remove existing blocker |
| `agent/services/fastmoss_taxonomy_reconciliation_service.py` — `FastMossTaxonomyReconciliationService` | Exists | Methods: `load_fastmoss_source_data`, `audit_fastmoss_product`, `perform_full_fastmoss_audit` | Reuse for taxonomy/category audit during draft generation |
| `agent/models/product_registration.py` — `RegistrationReviewDraft` | Exists | Lines 53–105; has `source_lane`, `claim_risk_level`, `review_draft_id`, `declared_evidence_fields` | Extend: add `fastmoss_reference_id: str | None` field |
| `agent/models/product_registration.py` — `RegistrationReviewDraftEvidencePatchRequest` | Exists | Lines 115–144 | Reuse for per-draft evidence editing of promoted drafts |
| `agent/api/product_registration.py` — review draft CRUD + evidence + commit routes | Exists | Routes: `GET/POST /review-drafts`, `PATCH /evidence`, `POST /commit` etc. | Reuse; do not add bulk routes here — they belong in new `fastmoss_bulk.py` router |
| `agent/services/registration_draft_storage_service.py` | Exists | Confirmed by glob | Reuse for storing individual drafts created by the bulk pipeline |
| `agent/services/registration_commit_service.py` — commit lane block | Exists | Lines 84–91: `FASTMOSS_REFERENCE` and `FASTMOSS` blocked | Extend: add `FASTMOSS_PROMOTED` as an allowed lane with `PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH` confirmation phrase |
| `agent/services/registration_draft_evidence_editor_service.py` | Exists | Confirmed by glob | Reuse for per-draft evidence edit in the review panel |
| `agent/services/registration_draft_recompute_service.py` | Exists | Confirmed by glob | Reuse for recompute after draft generation or evidence edit |
| `dashboard/src/pages/ProductRegistrationPage.tsx` | Exists — single product only | Lines 1–58: no tabs, no bulk surface | Extend: add tab switcher with `Single Product` and `Bulk FastMoss Convert` tabs |
| `dashboard/src/components/product-registration/RegistrationReviewDraftPanel.tsx` | Exists | Confirmed by glob | Reuse for individual draft review inside the bulk panel |
| `fastmoss_bulk_draft_status` table / service / router | **Missing** | Grep: 0 matches for `fastmoss_bulk`, `FASTMOSS_PROMOTED`, `bulk_draft` | **New** |
| `agent/api/fastmoss_bulk.py` router | **Missing** | Glob: not found | **New** |
| `FastMossBulkPromotionService` | **Missing** | Glob: not found | **New** |
| Bulk FastMoss Convert tab in UI | **Missing** | `ProductRegistrationPage.tsx` has no tab switcher | **New** |

---

## 5. Data Model

### 5.1 `fastmoss_bulk_draft_status` Table

This table is the queue backbone. Each row tracks one FastMoss reference through the promotion pipeline.

| Column | Type | Notes |
| --- | --- | --- |
| `reference_id` | `str` | Primary key. FastMoss reference ID (e.g. `fastmoss-ref:<id>`). Unique per queue entry. |
| `raw_product_title` | `str` | Raw product title from FastMoss workbook. Never overwritten. |
| `source_url` | `str \| None` | FastMoss or product page source URL from reference row. |
| `tiktok_product_url` | `str \| None` | TikTok product URL from FastMoss reference if available. |
| `image_url` | `str \| None` | Product image URL from FastMoss reference. |
| `category` | `str \| None` | FastMoss category string from workbook. |
| `claim_risk_level` | `str` | `LOW`, `MEDIUM`, or `HIGH`. Computed during queue sync from taxonomy audit. |
| `mapping_confidence` | `float \| None` | Mapping confidence score 0.0–1.0 from taxonomy reconciliation. |
| `image_readiness` | `str` | `IMAGE_PRESENT`, `IMAGE_MISSING`. Derived from `image_url` availability. |
| `copy_route` | `str \| None` | Computed copy route: `BENEFIT_ONLY`, `FEATURE_ONLY`, `DIRECT_CLAIM`, etc. |
| `sold_count` | `int \| None` | Sold count from FastMoss workbook if available. |
| `commission_rate` | `float \| None` | Commission rate from FastMoss workbook if available. |
| `promotion_status` | `str` | See allowed statuses below. |
| `draft_id` | `str \| None` | Review draft ID after draft generation. |
| `committed_product_id` | `str \| None` | Canonical product ID after approved commit. |
| `error_message` | `str \| None` | Last error message if draft creation or commit failed. |
| `created_at` | `datetime` | When this row was added to the queue. |
| `updated_at` | `datetime` | Last status update timestamp. |

### 5.2 Allowed Promotion Statuses

| Status | Meaning |
| --- | --- |
| `PENDING_DRAFT` | Row is in queue; no draft generated yet. |
| `DRAFT_GENERATED` | Draft has been created and is awaiting review. |
| `READY_FOR_APPROVAL` | Draft passed all gates: LOW risk, image present, required fields present, no duplicate. |
| `NEEDS_REVIEW` | Draft is MEDIUM claim risk. Must be individually reviewed; not eligible for bulk approve. |
| `MISSING_REQUIRED_FIELD` | Draft is missing one or more required fields. Must be edited before approval. |
| `CLAIM_RISK` | Draft is HIGH claim risk. Not eligible for bulk approve. Must be individually reviewed or rejected. |
| `IMAGE_MISSING` | Draft has no image URL or image cache failed. Cannot become `READY_FOR_APPROVAL`. |
| `DUPLICATE_SUSPECTED` | Duplicate detected against existing owned products or another queue row. Requires review. |
| `APPROVED` | Draft was approved and committed to product truth. `committed_product_id` is populated. |
| `REJECTED` | Row was manually rejected by operator. |

---

## 6. `RegistrationReviewDraft` Extension

Add one field to `RegistrationReviewDraft` (`agent/models/product_registration.py`):

```python
fastmoss_reference_id: str | None = None
```

This field must be preserved through:

- Draft creation from bulk queue.
- Evidence patch operations.
- Recompute pipeline.
- Commit write-back into the committed product row.

All other `RegistrationReviewDraft` fields are inherited unchanged.

---

## 7. Source Lane Governance

### Lane Definitions

| Lane | Meaning | Direct Commit to Owned Product Truth |
| --- | --- | --- |
| `FASTMOSS_REFERENCE` | Raw FastMoss reference row loaded from import. `reference_only=True` enforced. | **BLOCKED** — `SOURCE_LANE_NOT_ALLOWED_FOR_OWNED_COMMIT` |
| `FASTMOSS` | Raw/import-origin FastMoss data without reference prefix. | **BLOCKED** — `SOURCE_LANE_NOT_ALLOWED_FOR_OWNED_COMMIT` |
| `FASTMOSS_PROMOTED` | Approved promotion lane. Set only after bulk approval passes all governance gates. | **ALLOWED** with confirmation phrase |

### Confirmation Phrase

Commits via the `FASTMOSS_PROMOTED` lane must use the confirmation phrase:

```text
PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH
```

This is distinct from `REGISTER_OWNED_PRODUCT` (used by OWNED/MANUAL lanes). Both phrases must be kept
in registration commit service as separate guarded lanes.

### Invariant

Raw `FASTMOSS_REFERENCE` and `FASTMOSS` lanes remain permanently blocked from direct owned commit.
The only upgrade path is through the bulk promotion pipeline:
`FASTMOSS_REFERENCE` → queue row → draft generation → review → bulk approve → `FASTMOSS_PROMOTED` commit.

---

## 8. Backend Architecture

### 8.1 `FastMossBulkPromotionService`

New service: `agent/services/fastmoss_bulk_promotion_service.py`

#### `sync_bulk_queue(batch_id: str | None) -> BulkQueueSyncResult`

- Load FastMoss reference rows from the latest import batch (or a specific `batch_id`).
- For each reference row not already in `fastmoss_bulk_draft_status`:
  - Compute `claim_risk_level` via taxonomy audit (`FastMossTaxonomyReconciliationService`).
  - Compute `image_readiness` from `image_url` availability.
  - Set `promotion_status = PENDING_DRAFT`.
  - Insert row into queue.
- Skip rows already in queue (idempotent).
- Return sync summary: total synced, skipped, error count.

#### `list_bulk_queue(filters: BulkQueueFilter, page: int, page_size: int) -> BulkQueuePage`

- Return paginated, filtered list of `fastmoss_bulk_draft_status` rows.
- Supported filters: `promotion_status`, `claim_risk_level`, `image_readiness`, `category`, free-text search on `raw_product_title`.
- Return total count for pagination.

#### `create_draft_from_reference(reference_id: str) -> RegistrationReviewDraft`

- Load the queue row for `reference_id`.
- Map FastMoss reference fields → `RegistrationReviewDraftCreateRequest` (see field mapping, Section 10).
- Call draft storage service to create a `RegistrationReviewDraft`.
- Set `fastmoss_reference_id` on the draft.
- Set `source_lane = FASTMOSS_PROMOTED` on the draft (promotion pipeline draft, not raw reference).
- Run recompute: compute missing evidence, claim gate, image readiness, mapping confidence, copy route.
- Classify final `promotion_status` based on recompute results (see governance rules, Section 11).
- Update queue row: set `draft_id`, `promotion_status`, `updated_at`.
- Return the created draft.

#### `bulk_create_drafts(reference_ids: list[str]) -> BulkCreateDraftsResult`

- For each `reference_id` in the list:
  - If row is `PENDING_DRAFT`: call `create_draft_from_reference`.
  - If row already has a draft: skip or refresh based on freshness.
- Return per-row result: success, draft_id, or error.
- Partial failures are allowed; do not abort the entire batch on a single row error.

#### `bulk_approve_drafts(reference_ids: list[str], confirmation_phrase: str) -> BulkApproveResult`

- Reject entire request if `confirmation_phrase != "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH"`.
- For each `reference_id`:
  - Load queue row; verify `promotion_status == READY_FOR_APPROVAL`.
  - If not `READY_FOR_APPROVAL`: skip with `NOT_ELIGIBLE` result (do not error the batch).
  - If `READY_FOR_APPROVAL`: call registration commit service with `source_lane = FASTMOSS_PROMOTED`.
  - On commit success: set `promotion_status = APPROVED`, populate `committed_product_id`.
  - On commit error: set `promotion_status = MISSING_REQUIRED_FIELD` or preserve existing non-READY status; record `error_message`.
- Return per-row result.

#### `get_queue_stats() -> BulkQueueStats`

- Return counts grouped by `promotion_status`.
- Return counts grouped by `claim_risk_level`.
- Return total queue size, pending count, approved count, rejected count.

### 8.2 API Router — `agent/api/fastmoss_bulk.py`

New router. Mount prefix: `/api/fastmoss-bulk`.

| Method | Path | Handler | Notes |
| --- | --- | --- | --- |
| `GET` | `/queue` | `list_bulk_queue` | Supports `status`, `risk`, `image_readiness`, `category`, `q`, `page`, `page_size` query params |
| `GET` | `/queue/stats` | `get_queue_stats` | Returns counts by status and risk level |
| `POST` | `/queue/sync` | `sync_bulk_queue` | Accepts optional `batch_id` body; idempotent |
| `POST` | `/queue/{reference_id}/create-draft` | `create_draft_from_reference` | Single-row draft generation |
| `POST` | `/queue/bulk-create-drafts` | `bulk_create_drafts` | Accepts `{ reference_ids: [...] }` |
| `POST` | `/queue/bulk-approve-drafts` | `bulk_approve_drafts` | Accepts `{ reference_ids: [...], confirmation_phrase: "..." }` |
| `PATCH` | `/queue/{reference_id}/status` | `update_queue_row_status` | Manual status override (REJECTED, PENDING_DRAFT reset) |

---

## 9. Frontend Architecture

### 9.1 `ProductRegistrationPage.tsx` — Tab Extension

Add a tab switcher at the top of `ProductRegistrationPage`:

```text
[ Single Product ]  [ Bulk FastMoss Convert ]
```

- `Single Product` tab: existing flow, no changes.
- `Bulk FastMoss Convert` tab: new `BulkFastMossConvertTab` component.

### 9.2 `BulkFastMossConvertTab` Component

New component: `dashboard/src/components/product-registration/BulkFastMossConvertTab.tsx`

#### Stats Bar

Displays counts from `GET /api/fastmoss-bulk/queue/stats`:

```
PENDING: N   DRAFT_GENERATED: N   READY: N   NEEDS_REVIEW: N   APPROVED: N   REJECTED: N
```

#### Sync Button

Triggers `POST /api/fastmoss-bulk/queue/sync`. Shows last-sync timestamp.

#### Filters

- Status filter (multi-select): `PENDING_DRAFT`, `DRAFT_GENERATED`, `READY_FOR_APPROVAL`, `NEEDS_REVIEW`, `CLAIM_RISK`, `IMAGE_MISSING`, `DUPLICATE_SUSPECTED`, `APPROVED`, `REJECTED`, `MISSING_REQUIRED_FIELD`
- Claim risk filter: `LOW`, `MEDIUM`, `HIGH`
- Image readiness filter: `IMAGE_PRESENT`, `IMAGE_MISSING`
- Category filter (free text)
- Title search (free text)
- Clear filters button

#### Paginated Table

Columns:

| Column | Notes |
| --- | --- |
| Checkbox | Row selection |
| Raw Product Title | Truncated with tooltip |
| Category | From FastMoss |
| Claim Risk | Badge: LOW (green), MEDIUM (amber), HIGH (red) |
| Image | Thumbnail or IMAGE_MISSING badge |
| Sold Count | If available |
| Commission Rate | If available |
| Status | Status badge with colour coding |
| Draft | Link to open draft review panel if `draft_id` is populated |
| Actions | Per-row: Generate Draft, Reject |

Pagination controls: page size selector (25 / 50 / 100), page navigation.

#### Bulk Action Bar (activates when rows are selected)

```
N rows selected
[ Generate Drafts for Selected ]  [ Approve Ready Selected ]  [ Reject Selected ]
```

- **Generate Drafts for Selected**: calls `POST /queue/bulk-create-drafts` with selected `reference_ids`.
- **Approve Ready Selected**: calls `POST /queue/bulk-approve-drafts`. Prompts operator to type confirmation phrase `PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH` in a modal before submitting. Only READY_FOR_APPROVAL rows will be committed; others are skipped with per-row result shown.
- **Reject Selected**: calls `PATCH /queue/{reference_id}/status` with `REJECTED` for each selected row.

#### Draft Review Panel

When operator clicks the draft link for a row:

- Open the existing `RegistrationReviewDraftPanel` in a side panel or modal.
- Supports all existing evidence editing, recompute, and individual commit actions.
- On individual commit success: queue row status updates to `APPROVED`.

---

## 10. Field Mapping

### FastMoss Reference → Draft → Canonical Product Truth

| FastMoss Reference Field | Draft Field (`declared_evidence_fields`) | Canonical Product Truth Field | Notes |
| --- | --- | --- | --- |
| `raw_product_title` | `product_name` | `product_name` | Preserved verbatim in queue; may be edited in draft before commit |
| `source_url` | `source_url` | `source_url` | Source provenance |
| `tiktok_product_url` | `tiktok_product_url` | `tiktok_product_url` | TikTok shop provenance |
| `image_url` | `image_url` | `image_url` | Image provenance; IMAGE_MISSING gates READY_FOR_APPROVAL |
| `category` | Mapped to taxonomy silo/category field | `silo` / `product_category` | Via `FastMossTaxonomyReconciliationService` |
| `sold_count` | Commercial evidence context | Not directly a product truth field | Used for copy route decision only |
| `commission_rate` | `commission_rate` | `commission_rate` | Commercial evidence field |
| `reference_id` (FastMoss) | `fastmoss_reference_id` on draft | `fastmoss_reference_id` on committed product row | Lineage anchor; must never be stripped |
| Import batch `batch_id` | `provenance` list entry | `provenance` list entry | Workbook import provenance |
| `draft_id` | `review_draft_id` | Referenced in lineage; not a product field | Links queue row to draft |
| `committed_product_id` | N/A | Assigned at commit | Written back to queue row |

### Required Fields for `READY_FOR_APPROVAL`

All of the following must be present and non-empty in the draft before status can become `READY_FOR_APPROVAL`:

- `product_name`
- `image_url` (and image must be reachable / cached)
- At least one of: `benefits_text`, `product_knowledge_text`, or `usage_text`
- `claim_risk_level = LOW`
- `mapping_confidence >= threshold` (configurable; default 0.6)
- No duplicate detected

---

## 11. Bulk Workflow

```text
1. SYNC QUEUE
   POST /queue/sync
   → FastMoss reference rows loaded into fastmoss_bulk_draft_status
   → claim_risk_level computed per row
   → image_readiness set per row
   → All rows start as PENDING_DRAFT

2. REVIEW QUEUE
   GET /queue (with filters)
   → Operator reviews counts by risk/status
   → Selects rows to process

3. GENERATE DRAFTS
   POST /queue/bulk-create-drafts (selected reference_ids)
   → Per row: field mapping + recompute + governance classification
   → Status becomes DRAFT_GENERATED, READY_FOR_APPROVAL, NEEDS_REVIEW,
     CLAIM_RISK, IMAGE_MISSING, MISSING_REQUIRED_FIELD, or DUPLICATE_SUSPECTED

4. REVIEW INDIVIDUAL DRAFTS (for NEEDS_REVIEW / CLAIM_RISK / IMAGE_MISSING rows)
   Open RegistrationReviewDraftPanel for the draft
   → Edit missing evidence
   → Fix image URL
   → Recompute
   → If gates pass: status may update to READY_FOR_APPROVAL
   → Or individually commit with PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH phrase

5. BULK APPROVE READY DRAFTS
   POST /queue/bulk-approve-drafts (selected reference_ids)
   Confirmation phrase modal: operator types PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH
   → Only READY_FOR_APPROVAL rows are committed
   → NEEDS_REVIEW / CLAIM_RISK rows are skipped
   → On commit: status = APPROVED, committed_product_id populated

6. PRODUCT TRUTH AVAILABLE
   Committed rows become canonical product truth
   Workspace generation eligibility depends on downstream image cache + mode readiness gates
```

---

## 12. Governance Model

### Claim Risk Classification Rules

| Condition | Assigned Status |
| --- | --- |
| `claim_risk_level = LOW` AND image present AND required fields present AND no duplicate | `READY_FOR_APPROVAL` |
| `claim_risk_level = LOW` AND image missing | `IMAGE_MISSING` |
| `claim_risk_level = LOW` AND required field missing | `MISSING_REQUIRED_FIELD` |
| `claim_risk_level = LOW` AND duplicate detected | `DUPLICATE_SUSPECTED` |
| `claim_risk_level = MEDIUM` (any image/field state) | `NEEDS_REVIEW` — not eligible for bulk approve |
| `claim_risk_level = HIGH` (any state) | `CLAIM_RISK` — not eligible for bulk approve |

### Image Governance Rules

- `IMAGE_MISSING` rows **cannot** become `READY_FOR_APPROVAL`.
- An image URL must be present and the image must be accessible (or cached locally) for `READY_FOR_APPROVAL`.
- If image cache fails **after** commit: the committed product truth row may exist, but workspace package readiness remains blocked until image is resolved. The promotion pipeline does not retroactively un-commit a product.
- `VISION_PROVIDER_NOT_CONFIGURED` is not equivalent to image missing. Semantic image analysis failure does not block `READY_FOR_APPROVAL` when a valid image URL is present.

### Duplicate Detection Rules

- Duplicate detection must include `FASTMOSS` source products (both raw reference rows and previously promoted rows).
- If an owned product with matching title or TikTok product URL already exists in canonical product truth: status becomes `DUPLICATE_SUSPECTED`.
- `DUPLICATE_SUSPECTED` rows are not eligible for bulk approve; they require individual operator review.

### Raw Reference Blocker — Preserved

`FASTMOSS_REFERENCE` and `FASTMOSS` lanes remain permanently blocked from direct owned commit in
`registration_commit_service.py`. No change to that gate. The promotion pipeline creates drafts with
`source_lane = FASTMOSS_PROMOTED` only after governance gates pass; it does not attempt to commit raw
reference lanes.

### Draft Freshness

- A queue row draft that was generated but then had its underlying reference data updated must be regenerated before it can be approved.
- A draft that has had evidence edits applied must be recomputed before commit.

### Post-Approval Workspace Eligibility

A committed product from `FASTMOSS_PROMOTED` lane becomes a canonical product truth row. Workspace
generation eligibility still depends on all downstream mode readiness gates (image cache, hook/CTA angles,
prompt approval), not just the act of promotion. Promotion is not a bypass of workspace readiness gates.

---

## 13. FastMoss Lineage Requirements

Every generated draft and every committed product truth row originating from this pipeline **must** preserve:

| Field | Location |
| --- | --- |
| `fastmoss_reference_id` | On `RegistrationReviewDraft` and committed product row |
| `source_url` / TikTok product URL | In `declared_evidence_fields` and committed product row |
| `raw_product_title` | In queue row (never overwritten), and in draft provenance |
| `source_lane = FASTMOSS_PROMOTED` | On draft and committed product row |
| Import batch `batch_id` / workbook provenance | In `provenance` list on draft and committed product row |
| `draft_id` | In queue row after draft creation |
| `committed_product_id` | Written back to queue row after commit |

Lineage fields must not be stripped during evidence editing, recompute, or commit.

---

## 14. Minimum First Wave (Wave 1 Scope)

### Implement in Wave 1

| Component | Details |
| --- | --- |
| `fastmoss_bulk_draft_status` table/store | All columns from Section 5.1 |
| `FastMossBulkPromotionService` | All 6 methods from Section 8.1 |
| `agent/api/fastmoss_bulk.py` router | All 7 endpoints from Section 8.2 |
| Sync queue from FastMoss references | Idempotent; loads from latest import batch |
| List queue with server-side filters and pagination | status, risk, image_readiness, category, title search |
| Create draft from one reference | Single-row draft generation with governance classification |
| Bulk create drafts from selected IDs | Partial-failure-tolerant batch |
| Bulk approve READY_FOR_APPROVAL drafts only | Confirmation phrase gate; skips ineligible rows |
| `FASTMOSS_PROMOTED` commit lane | In `registration_commit_service.py` with `PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH` phrase |
| Duplicate detection includes FASTMOSS source | Extend existing duplicate detection |
| `fastmoss_reference_id` on `RegistrationReviewDraft` | Extend model |
| `ProductRegistrationPage` tab switcher | Two tabs: Single Product + Bulk FastMoss Convert |
| `BulkFastMossConvertTab` component | Stats bar, filters, paginated table, row selection, bulk actions, draft links, status badges |
| Queue stats endpoint | Counts by status and risk |

### Defer to Later Waves

| Feature | Reason |
| --- | --- |
| Live streaming progress (WebSocket / SSE) | Complexity; polling is sufficient for Wave 1 |
| Advanced AI benefit / target-audience generation per row | Requires per-product LLM calls at scale; out of Wave 1 budget |
| Batch claim-safe rewrite automation | Requires claim-safe rewrite service integration at bulk scale |
| Bulk image cache automation beyond post-commit trigger | Requires background worker queue |
| Advanced sold/commission filters and analytics | Non-blocking for core promotion pipeline |
| Full background worker queue | Polling-based bulk create is sufficient for Wave 1 |
| Control Tower / RBAC for bulk approval roles | Deferred to Control Tower plan |

---

## 15. Out of Scope

The following are explicitly **excluded** from this plan and must not be implemented under this authority:

- **Google Flow DOM automation** — any changes to `content-flow-dom.js` or Chrome extension upload logic.
- **Auto-approval of unsafe products** — HIGH or MEDIUM claim risk rows cannot be auto-approved under any path.
- **Making raw `reference_only=true` rows generation-ready** — `FASTMOSS_REFERENCE` lane blocker remains intact. Only `FASTMOSS_PROMOTED` committed rows become canonical product truth.
- **Claim-safe batch rewrite automation** — not part of this wave.
- **WebSocket / SSE progress streaming** — deferred.
- **Full AI enrichment** — advanced LLM-generated benefit copy, targeting copy, and hook/CTA generation beyond safe field mapping is deferred.
- **Control Tower / RBAC** — role-based access control for bulk approval is deferred.
- **TikTok scraping or live price/commission fetch** — data comes from already-imported FastMoss workbook rows only.
- **Product lifecycle archive/unarchive** — not in scope.
- **Temporal extension / multi-block video planner** — unrelated.

---

## 16. Test Plan

### Backend / Service Tests

| Test | Covers |
| --- | --- |
| `test_bulk_queue_sync_from_latest_batch` | Sync loads reference rows; idempotent on re-run |
| `test_bulk_queue_sync_with_batch_id` | Sync from specific batch ID |
| `test_bulk_queue_list_filters_by_status` | List queue filtered by `promotion_status` |
| `test_bulk_queue_list_filters_by_risk` | List queue filtered by `claim_risk_level` |
| `test_bulk_queue_list_filters_by_image_readiness` | List queue filtered by `IMAGE_PRESENT` / `IMAGE_MISSING` |
| `test_bulk_queue_list_pagination` | Page size and offset correct |
| `test_create_draft_from_reference_low_risk` | LOW risk + image present + fields present → `READY_FOR_APPROVAL` |
| `test_create_draft_from_reference_medium_risk` | MEDIUM risk → `NEEDS_REVIEW` regardless of image/fields |
| `test_create_draft_from_reference_high_risk` | HIGH risk → `CLAIM_RISK` |
| `test_create_draft_from_reference_image_missing` | LOW risk + no image → `IMAGE_MISSING` |
| `test_create_draft_from_reference_missing_required_field` | LOW risk + image + missing title or body → `MISSING_REQUIRED_FIELD` |
| `test_create_draft_duplicate_detection` | Existing owned product match → `DUPLICATE_SUSPECTED` |
| `test_bulk_create_drafts_partial_failure` | One row errors; others succeed; batch not aborted |
| `test_bulk_approve_ready_drafts_correct_phrase` | `PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH` phrase → commits READY rows |
| `test_bulk_approve_rejects_wrong_phrase` | Wrong phrase → entire request rejected, no commits |
| `test_bulk_approve_skips_non_ready_rows` | NEEDS_REVIEW / CLAIM_RISK rows skipped; READY rows committed |
| `test_bulk_approve_sets_committed_product_id` | After commit, queue row has `committed_product_id` populated |
| `test_lineage_preserved_on_draft` | `fastmoss_reference_id`, `source_url`, `raw_product_title`, `source_lane` on draft |
| `test_lineage_preserved_on_committed_product` | Lineage fields present on committed product row |
| `test_reference_only_blocker_remains` | `FASTMOSS_REFERENCE` lane still blocked from direct owned commit |
| `test_fastmoss_promoted_lane_allowed` | `FASTMOSS_PROMOTED` lane allowed with correct phrase |
| `test_queue_stats_counts` | Stats endpoint returns correct counts per status |

### API Tests

| Test | Covers |
| --- | --- |
| `test_api_queue_list` | `GET /api/fastmoss-bulk/queue` returns paginated results |
| `test_api_queue_stats` | `GET /api/fastmoss-bulk/queue/stats` returns status counts |
| `test_api_queue_sync` | `POST /api/fastmoss-bulk/queue/sync` returns sync summary |
| `test_api_create_draft_single` | `POST /api/fastmoss-bulk/queue/{id}/create-draft` returns draft |
| `test_api_bulk_create_drafts` | `POST /api/fastmoss-bulk/queue/bulk-create-drafts` returns per-row results |
| `test_api_bulk_approve_drafts` | `POST /api/fastmoss-bulk/queue/bulk-approve-drafts` with correct phrase |
| `test_api_bulk_approve_wrong_phrase` | Returns 400/422 with wrong phrase |
| `test_api_update_queue_row_status_reject` | `PATCH /api/fastmoss-bulk/queue/{id}/status` sets `REJECTED` |

### UI / Contract Tests

| Test | Covers |
| --- | --- |
| `test_bulk_fastmoss_tab_renders` | Tab appears in `ProductRegistrationPage` |
| `test_stats_bar_displays_counts` | Stats bar shows correct status counts from API |
| `test_filter_by_status_updates_table` | Status filter changes table rows |
| `test_row_selection_enables_bulk_actions` | Selecting rows activates bulk action bar |
| `test_generate_drafts_selected_calls_api` | Bulk generate sends correct reference IDs |
| `test_approve_ready_requires_confirmation_phrase` | Approve modal requires correct phrase before submit |
| `test_draft_link_opens_review_panel` | Clicking draft link opens `RegistrationReviewDraftPanel` |
| `test_image_missing_badge_shown` | `IMAGE_MISSING` row shows badge; `READY_FOR_APPROVAL` not shown |

### Regression Tests

| Test | Covers |
| --- | --- |
| `test_existing_single_product_flow_unaffected` | Single Product tab and existing review draft flow unchanged |
| `test_fastmoss_reference_blocker_not_removed` | `registration_commit_service` still blocks `FASTMOSS_REFERENCE` lane |
| `test_owned_confirmation_phrase_unchanged` | `REGISTER_OWNED_PRODUCT` phrase still works for OWNED/MANUAL lanes |
| `test_workspace_readiness_not_bypassed` | Promoted products still require downstream image + mode readiness |

---

## 17. Implementation PR Report Format

After Wave 1 coding is complete, the implementation PR must include:

```text
# STATUS
PASS_PR_OPENED / BLOCKED

# ISSUE_AUTHORITY
Issue #92 URL

# BASELINE
main SHA at implementation start

# PLANNING_AUTHORITY
docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
planning commit SHA

# IMPLEMENTATION_SUMMARY
what was built

# DATA_MODEL_PROOF
fastmoss_bulk_draft_status table exists, all columns present

# SYNC_QUEUE_PROOF
sync endpoint called; reference rows appear in queue with correct risk classification

# DRAFT_GENERATION_PROOF
single and bulk draft creation; READY_FOR_APPROVAL / NEEDS_REVIEW / CLAIM_RISK classification correct

# BULK_APPROVE_PROOF
confirmation phrase gate; READY rows committed; NEEDS_REVIEW / CLAIM_RISK skipped

# LINEAGE_PROOF
fastmoss_reference_id, source_url, raw_product_title, source_lane present on draft and committed product

# REFERENCE_ONLY_BLOCKER_PROOF
FASTMOSS_REFERENCE and FASTMOSS lanes still blocked; FASTMOSS_PROMOTED allowed with correct phrase only

# WORKSPACE_READINESS_PROOF
promoted products require downstream image cache and mode readiness; promotion does not bypass workspace gates

# FRONTEND_PROOF
tab switcher present; stats bar; filters; table; row selection; bulk actions; draft panel link

# VALIDATION_RESULTS
pytest backend and API tests pass
npm run build passes
governance gate passes (npx tsx scripts/mandor-check.ts)
biome lint passes on changed frontend files

# REPO_HYGIENE_PROOF
no runtime artifacts; no live Google Flow calls; no extension changes

# CHANGED_FILES
exact files

# PR
actual PR URL

# HEAD_SHA
remote branch head SHA

# MERGE_READINESS
MERGE_READY / NOT_MERGE_READY with reason
```

---

## 18. Final Decision

This document authorizes **implementation planning only**.

No coding, no patching, no PR, no mutation of product truth is authorised by this document alone.

Implementation must proceed as a bounded Wave 1:

```text
BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION — WAVE_1
```

Implementation may begin after this planning document is:

1. Committed and pushed to `main`.
2. Reviewed and explicitly approved by the product owner (user).
3. Assigned to the correct implementing agent (Codex) with a bounded implementation prompt referencing this document's `file_id`.

The bounded implementation prompt must be authored separately and must not begin until Step 2 is confirmed.
