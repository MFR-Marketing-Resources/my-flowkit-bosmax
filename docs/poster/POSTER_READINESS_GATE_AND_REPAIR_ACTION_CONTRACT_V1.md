# Poster Readiness Gate and Repair Action Contract V1

This document defines the deterministic gate the future poster module must call **before** generating posters. It does not implement poster generation, image rendering, or prompt compilation for posters.

Baseline audit: `docs/audits/PRODUCT_TRUTH_POSTER_READINESS_AUDIT_V3` (merged PR #231).

## API

```http
GET /api/products/{product_id}/poster-readiness
```

Read-only. No product mutations. Response model: `agent/models/poster_readiness.py`. Service: `agent/services/poster_readiness_service.py`.

## Status taxonomy

| Status | Meaning |
|--------|---------|
| `POSTER_READY` | Normal poster generation allowed (production + preview). |
| `POSTER_READY_RESTRICTED` | Poster generation allowed only under safe restricted rules (no cure/treat/heal/disease/guaranteed relief, etc.). Requires verified restricted-safe clearance signal. |
| `POSTER_REPAIR_REQUIRED` | Not ready yet, but the system returns concrete repair actions. **No dead-end hold.** |
| `POSTER_PREVIEW_ONLY` | Diagnostic / preview prompt only; production poster output blocked. |
| `POSTER_BLOCKED` | Hard stop (archived, missing identity, severe truth contradiction). Human review required. |

## Blocker taxonomy

Hard blockers → `POSTER_BLOCKED`:

- `PRODUCT_ARCHIVED`
- `MISSING_RAW_TITLE`
- `MISSING_DISPLAY_NAME`
- `SEVERE_PRODUCT_TRUTH_CONTRADICTION`

Repair blockers → `POSTER_REPAIR_REQUIRED` (with actions):

- `MAPPING_MISSING`, `MAPPING_BLOCKED`
- `MISSING_CATEGORY`, `MISSING_SUBCAT_AND_TYPE`
- `NO_IMAGE`, `IMG_NOT_PROD_APPROVED`
- `CLAIM_RISK_HIGH`, `CLAIM_SAFE_COPY_REQUIRED`
- `PRODUCT_TRUTH_GAP`

Soft blockers → `POSTER_PREVIEW_ONLY` when they are the only issues:

- `REMOTE_IMAGE_ONLY`, `LOW_CONFIDENCE_METADATA`, `WEAK_IMAGE_SOURCE`

## Why `CLAIM_RISK_HIGH` is not permanent hold

High claim risk means **unrestricted** poster generation is not allowed until:

1. `RUN_SAFE_CLAIM_CLEARANCE` — claim-safe rewrite preview + human approval (`GET/POST /api/products/{id}/claim-safe-rewrite-*`).
2. Claim risk is lowered and claim-safe copy is approved.
3. `APPROVE_RESTRICTED_SAFE_POSTER_ROUTE` — production prompt approval with `RESTRICTED_SAFE_POSTER` recorded in approval note/provenance (`POST /api/products/{id}/production-prompt-approval`).

After success, re-check readiness → expected `POSTER_READY_RESTRICTED` (not unrestricted `POSTER_READY` while product remains claim-sensitive).

## Restricted-safe clearance signal (verified, not invented)

`POSTER_READY_RESTRICTED` is returned only when **all** are true:

- `claim_risk_level` is not `HIGH`
- Claim-safe copy status is `CLAIM_SAFE_COPY_APPROVED` or `CLAIM_SAFE_COPY_REVIEW_READY`
- `IMG` mode is production-approved
- Approval note or provenance contains `RESTRICTED_SAFE_POSTER`

Without this signal, high-risk products stay `POSTER_REPAIR_REQUIRED` with clearance actions.

## Repair action contract

Each action includes: `action_code`, `label`, `severity`, `allowed_now`, `auto_executable`, `requires_human_approval`, `recommended_endpoint` (existing routes only), `next_check`, `expected_status_after_success`, `notes`.

### Blocker → action mapping (minimum)

| Blocker | Actions | Endpoint hints |
|---------|---------|----------------|
| `MAPPING_MISSING` | `RUN_PRODUCT_MAPPING` | `POST /api/products/map`, `POST /api/products/backfill-mapping` |
| `MAPPING_BLOCKED` | `REVIEW_PRODUCT_MAPPING` | `PATCH /api/products/{id}` |
| `MISSING_CATEGORY` | `FIX_PRODUCT_CATEGORY` | `PATCH /api/products/{id}` |
| `MISSING_SUBCAT_AND_TYPE` | `FIX_PRODUCT_TAXONOMY` | `PATCH /api/products/{id}` |
| `NO_IMAGE` | `UPLOAD_PRODUCT_IMAGE`, `CACHE_PRODUCT_IMAGE` | `PATCH /api/products/{id}`, `POST /api/products/{id}/cache-image` |
| `IMG_NOT_PROD_APPROVED` | `RUN_IMG_PRODUCTION_APPROVAL` | `POST /api/products/{id}/production-prompt-approval` |
| `CLAIM_RISK_HIGH` | `RUN_SAFE_CLAIM_CLEARANCE`, `APPROVE_RESTRICTED_SAFE_POSTER_ROUTE` | claim-safe + production approval routes |
| `PRODUCT_ARCHIVED` | `UNARCHIVE_OR_DUPLICATE_PRODUCT` | `POST /api/products/{id}/unarchive` |
| `SEVERE_PRODUCT_TRUTH_CONTRADICTION` | `HUMAN_PRODUCT_TRUTH_REVIEW` | `GET /api/product-truth/reconciliation-audit` |

## Decision matrix (summary)

```text
ARCHIVED / missing identity / severe contradiction → POSTER_BLOCKED
CLAIM_RISK_HIGH without clearance → POSTER_REPAIR_REQUIRED (+ clearance actions)
Other repair blockers → POSTER_REPAIR_REQUIRED (+ mapped actions)
Only soft blockers → POSTER_PREVIEW_ONLY
No blockers + restricted clearance verified → POSTER_READY_RESTRICTED
No blockers → POSTER_READY
```

## Repair action expectations

- `expected_status_after_success`: immediate outcome after the action — usually `RECHECK_REQUIRED` (call readiness again).
- `expected_status_if_no_other_blockers`: terminal poster status when this was the last remaining blocker (e.g. `POSTER_READY`, `POSTER_READY_RESTRICTED`).
- Notes on `RECHECK_REQUIRED` actions state that additional blockers may still apply.

## Live target verification (PR #231 IDs)

When `flow_agent.db` is present locally, `tests/unit/test_poster_readiness_live_targets.py` verifies:

| Product | ID |
|---------|-----|
| Bosmax Oil 10 ML | `b460ffbd-7d9d-4f6b-a570-0e9b1056439a` |
| Bosmax Herbs 5 ML | `90349f8c-9e14-4efe-988e-76ec60ea31f4` |
| Minyak Warisan Tok Cap Burung 25ml | `6483d624-a03d-4933-9bba-6ca2e5f7b6fd` |

Expected: Bosmax products → `POSTER_REPAIR_REQUIRED` + `CLAIM_RISK_HIGH`; Minyak → `POSTER_READY` when DB matches audit baseline (test allows reporting stricter actual status).

## Mapping ready states

`mapping_route.mapping_ready` uses `MAPPING_READY_STATES`: `READY`, `APPROVED`, `MAPPED`, `COMPLETE` (aligned with blocker logic).

## Image signals

`_has_any_image` considers `local_image_path`, usable `image_url`, `asset_status`, `image_asset_status`, and `image_readiness_status` (`IMAGE_READY_STATES`).

| Product | Expected |
|---------|----------|
| Minyak Warisan Tok Cap Burung 25ml | `POSTER_READY` when DB has mapping, taxonomy, local image, IMG approval, non-HIGH claim risk |
| Bosmax Herbs 5 ML | `POSTER_REPAIR_REQUIRED`, `CLAIM_RISK_HIGH`, actions include `RUN_SAFE_CLAIM_CLEARANCE` |
| Bosmax Oil 10 ML | Same as Herbs while `claim_risk_level=HIGH` |

Live DB IDs may differ; use the API against real `product_id` values from the catalog.

## Future poster module consumption

```text
User selects product
  → GET /api/products/{id}/poster-readiness
  → POSTER_READY → allow normal poster flow
  → POSTER_READY_RESTRICTED → allow restricted template / copy rules only
  → POSTER_REPAIR_REQUIRED → show repair_actions UI; run endpoint; recheck
  → POSTER_PREVIEW_ONLY → preview only + fixes
  → POSTER_BLOCKED → hard stop + human review
```

## Out of scope (this PR)

- Poster image/prompt generation
- Wiring to image generation backends
- Auto-clearing claim risk or auto-approving production packages
- Mutating product rows during readiness check
- Changing PR #231 audit baseline artifacts