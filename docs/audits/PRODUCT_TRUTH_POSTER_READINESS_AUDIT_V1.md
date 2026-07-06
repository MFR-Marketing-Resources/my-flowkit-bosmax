# Product Truth Poster Readiness Audit V2 (FORENSIC CORRECTION)

**Date:** 2026-07-06 (revised)  
**Auditor:** Hermes Agent (counter-audit correction of PR #231)  
**DB Path:** `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`  
**Command:** `python scripts/audit-product-truth-poster-readiness.py`  
**Script:** `scripts/audit-product-truth-poster-readiness.py`  

> **FORENSIC NOTE:** This V2 report replaces V1. V1 contained material contradictions between the markdown report (claimed 194 ready) and raw JSON (recorded 3 ready), used a flawed source=FASTMOSS→ref_only heuristic, excluded APPROVED mapping from the ready gate, and applied an unacceptably weak PASS threshold. See counter-audit findings below.

---

## Executive Verdict: PASS ✅

**196 committed product rows meet the POSTER_READY gate.** All four strict threshold checks pass:

| Threshold | Required | Actual | Status |
|-----------|----------|--------|--------|
| Ready products | ≥5 | **196** | ✅ |
| Distinct categories | ≥3 | **24** | ✅ |
| Target product (Bosmax/Minyak) | ≥1 | **1** (Minyak Warisan) | ✅ |
| Product with local/downloaded image | ≥1 | **1** | ✅ |

The poster/image prompt generation module can be built and tested now. Use the 196 POSTER_READY products as test fixtures.

> **⚠️ WARNING:** Bosmax Oil 10 ML and Bosmax Herbs 5 ML are **NOT** POSTER_READY. Both are blocked by `CLAIM_RISK_HIGH`. Only Minyak Warisan Tok Cap Burung 25ml is a target product that passes the poster gate. See Section 7.

---

## Counter-Audit: V1 Material Contradictions Repaired

| Issue | V1 (broken) | V2 (fixed) |
|-------|-------------|------------|
| **Report vs JSON** | Report claimed 194 ready; JSON said 3 ready | Both report 196 ready ✅ |
| **APPROVED mapping** | Script excluded APPROVED as blocker; report claimed it was ready | APPROVED IS a valid ready state; script and report agree ✅ |
| **Canonical / ref-only** | `source=FASTMOSS` → ref_only (wrong) | All 516 product table rows are canonical; `source` is provenance, not lifecycle |
| **PASS threshold** | `ready > 0` (trivial) | ≥5 ready, ≥3 categories, ≥1 target, ≥1 local image ✅ |
| **Confidence** | Unlabeled heuristic | Clearly labeled "heuristic only" — not ProductTruthService ✅ |
| **Image counts** | Report said 36 local_image; JSON said 3 | Both now say 3 local / 3 DOWNLOADED ✅ |
| **Bosmax targets** | Not reported | Full per-product readiness matrix in Section 7 ✅ |

---

## 1. Product Counts Table (ALL 516 = canonical committed rows)

> The `product` table has **no `reference_only` column**. All 516 rows are committed canonical product rows. `source=FASTMOSS` indicates provenance (import source), not lifecycle state. Reference-only products live in the FastMoss workbook (outside the product table) and are not counted here.

| # | Metric | Count |
|---|--------|-------|
| 1 | Total products in `product` table | **516** |
| 2 | Active products | **516** |
| 3 | Archived products | **0** |
| 4 | Source: FASTMOSS (provenance only) | **298** |
| 5 | Source: MANUAL | **218** |
| 6 | With `raw_product_title` | **516** (100%) |
| 7 | With `product_display_name` | **516** (100%) |
| 8 | With `product_short_name` | **516** (100%) |
| 9 | With `category` | **516** (100%) |
| 10 | With `subcategory` | **516** (100%) |
| 11 | With `type` | **508** |
| 12 | `mapping_status` robust (READY + APPROVED) | **211** (7 READY + 204 APPROVED) |
| 13 | `mapping_status` missing (NULL) | **302** (295 FASTMOSS + 7 MANUAL) |
| 14 | `mapping_status` BLOCKED | **3** |
| 15 | With `image_url` | **505** |
| 16 | With `local_image_path` | **3** |
| 17 | `image_asset_status` DOWNLOADED | **3** |
| 18 | `image_asset_status` IMAGE_READY | **0** |
| 19 | `claim_safe_copy_status` breakdown | APPROVED: 302, REVIEW_READY: 196, PREVIEW_ONLY: 13, MISSING: 5 |
| 20 | `claim_risk_level` breakdown | HIGH: 3 (2 are Bosmax), MEDIUM: 2, LOW: 206, MISSING: 305 (all FASTMOSS) |
| 21 | Production-approved for IMG | **495** |
| 22 | Products passing POSTER_READY gate | **196** |

---

## 2. Image Readiness Tiers

| Tier | Count | Description |
|------|-------|-------------|
| **PRODUCT_HERO_POSTER_READY** | 3 | Local image cached OR image_asset_status=DOWNLOADED |
| **PRODUCT_IMAGE_PROMPT_READY** | 503 | Has remote image_url (no local cache) |
| **TEXT_ONLY_POSTER_READY** | 10 | No image at all — poster generation must use text-only subject |

The IMG mode supports text-only subject through `PROMPT_TEXT_SUBJECT` fallback (`approved_product_package_service.py` L253-258), so TEXT_ONLY products are not blocked for IMG — they just cannot produce visual product hero posters.

---

## 3. Product Truth Confidence (Simplified Heuristic Only)

> ⚠️ **LIMITATION:** Confidence values below use a simplified heuristic (`simple_confidence()`). The actual `ProductTruthService.build_computed_profile()` is NOT invoked because it requires the full async app context (aiosqlite, FastMoss taxonomy reconciliation, image analysis provider). These labels are approximate and should not be treated as authoritative Product Truth confidence.

| Label | Count | Heuristic Basis |
|-------|-------|----------------|
| MEDIUM (heuristic) | 211 | mapping_status IN (READY, APPROVED) |
| LOW (heuristic) | 302 | mapping_status NULL (needs mapping) |
| NEEDS_REVIEW (heuristic) | 3 | mapping_status BLOCKED |

No HIGH heuristic confidence exists for FastMoss source + raw file because 0 FASTMOSS products have `fastmoss_source_file` populated.

---

## 4. Poster Readiness Distribution

| Gate | Count | Description |
|------|-------|-------------|
| **POSTER_READY** | **196** | All identity fields + mapping robust + claim safe ready + IMG prod approved |
| **POSTER_PREVIEW_ONLY** | **320** | One or more blockers (see below) |
| **POSTER_BLOCKED** | **0** | Zero archived products; zero missing raw_title/display_name |

---

## 5. Top Blockers Table

| Blocker Code | Count | Severity | Recommended Fix |
|-------------|-------|----------|----------------|
| `MAPPING_MISSING` | 302 | P1 | Run product mapping workflow on all NULL-mapping products. 295 are FASTMOSS-source — these were bulk-imported but never mapped. |
| `MAPPING_BLOCKED` | 3 | P1 | Review blocked mapping. Run mapping reconciliation. |
| `IMG_NOT_PROD_APPROVED` | 19 | P1 | Run production prompt approval flow. Add "IMG" to `production_prompt_approved_modes`. |
| `CLAIM_RISK_HIGH` | 2 | P0 | **CRITICAL:** Bosmax Oil and Bosmax Herbs have HIGH claim risk. Manual claim review required before poster generation. |
| `NO_IMAGE` | 7 | P2 | Upload/attach product images. |
| `MISSING_CATEGORY` | 0 | — | No products missing category (fixed from V1 overcount). |
| `MISSING_SUBCAT_AND_TYPE` | 0 | — | No products missing both (fixed from V1 overcount). |

---

## 6. Sample Products

### 6.1 POSTER_READY (5 samples)

| Product ID | Display Name | Source | Mapping | Image Tier | Claim | Confidence |
|------------|-------------|--------|---------|-----------|-------|------------|
| `de3ee6bd` | [KKM] 7LUME White Tomato Skin Supplement | MANUAL | READY | IMAGE_PROMPT | APPROVED | MEDIUM (h) |
| `3bc08dc9` | Sumikko Premium Baby Diaper pants | MANUAL | READY | IMAGE_PROMPT | APPROVED | MEDIUM (h) |
| `ef9c117e` | Wooden Curtain Rod Batang Langsir Kayu 28mm | MANUAL | APPROVED | IMAGE_PROMPT | REVIEW_READY | MEDIUM (h) |
| `29db89c6` | Sabun Dobi Malaya Combo 10 KG | MANUAL | APPROVED | IMAGE_PROMPT | REVIEW_READY | MEDIUM (h) |
| `6483d624` | **Minyak Warisan Tok Cap Burung 25ml** | MANUAL | READY | HERO_POSTER | REVIEW_READY | MEDIUM (h) |

### 6.2 POSTER_PREVIEW_ONLY (5 samples)

| Product ID | Display Name | Source | Mapping | Image | Claim | Blocker |
|------------|-------------|--------|---------|-------|-------|---------|
| `b460ffbd` | **Bosmax Oil 10 ML** | MANUAL | APPROVED | HERO_POSTER | APPROVED | `CLAIM_RISK_HIGH` |
| `90349f8c` | **Bosmax Herbs 5 ML** | MANUAL | READY | HERO_POSTER | APPROVED | `CLAIM_RISK_HIGH` |
| `8ae553d2` | CLASSY Karpet Velvet | FASTMOSS | NULL | IMAGE_PROMPT | APPROVED | `MAPPING_MISSING` |
| *(various)* | *(295 FASTMOSS products)* | FASTMOSS | NULL | IMAGE_PROMPT | various | `MAPPING_MISSING` |
| *(various)* | *(7 MANUAL + 3 BLOCKED)* | MANUAL | BLOCKED/NULL | various | various | `MAPPING_BLOCKED` or `MAPPING_MISSING` |

### 6.3 POSTER_BLOCKED (0 samples)

Zero products are truly blocked. All 516 have `raw_product_title`, `product_display_name`, and are ACTIVE.

---

## 7. Target Product Readiness Matrix

> ⚠️ These are the poster module's primary target products.

### Bosmax Herbs 5 ML

| Field | Value |
|-------|-------|
| `product_id` | `90349f8c-9e14-4efe-988e-76ec60ea31f4` |
| Product state | **POSTER_PREVIEW_ONLY** (not ready) |
| Source | MANUAL |
| Lifecycle | ACTIVE |
| Mapping status | READY ✅ |
| Claim safe copy | CLAIM_SAFE_COPY_APPROVED ✅ |
| Claim risk level | **HIGH** 🔴 |
| Image URL | Yes |
| Local image path | Yes (DOWNLOADED) |
| Image tier | PRODUCT_HERO_POSTER_READY |
| IMG production approved | Yes (in modes: T2V, IMG) |
| **Blocker** | `CLAIM_RISK_HIGH` |

### Bosmax Oil 10 ML

| Field | Value |
|-------|-------|
| `product_id` | `b460ffbd-7d9d-4f6b-a570-0e9b1056439a` |
| Product state | **POSTER_PREVIEW_ONLY** (not ready) |
| Source | MANUAL |
| Lifecycle | ACTIVE |
| Mapping status | APPROVED ✅ |
| Claim safe copy | CLAIM_SAFE_COPY_APPROVED ✅ |
| Claim risk level | **HIGH** 🔴 |
| Image URL | Yes |
| Local image path | Yes (DOWNLOADED) |
| Image tier | PRODUCT_HERO_POSTER_READY |
| IMG production approved | Yes (in modes: T2V, IMG) |
| **Blocker** | `CLAIM_RISK_HIGH` |

### Minyak Warisan Tok Cap Burung 25ml ⭐

| Field | Value |
|-------|-------|
| `product_id` | `6483d624-a03d-4933-9bba-6ca2e5f7b6fd` |
| Product state | **POSTER_READY** ✅ |
| Source | MANUAL |
| Lifecycle | ACTIVE |
| Mapping status | READY ✅ |
| Claim safe copy | CLAIM_SAFE_COPY_REVIEW_READY ✅ |
| Claim risk level | MEDIUM ✅ |
| Image URL | Yes |
| Local image path | Yes (DOWNLOADED) |
| Image tier | PRODUCT_HERO_POSTER_READY |
| IMG production approved | Yes (in modes: T2V, IMG) |
| **Blocker** | None ✅ |

---

## 8. Critical Decision: APPROVED as Valid Ready State

**DECISION: `mapping_status=APPROVED` IS a valid ready state.**

Rationale:
- The mapping pipeline produces two equivalent outcome states: `READY` (auto-mapped) and `APPROVED` (manually reviewed and approved).
- 204 MANUAL products carry `APPROVED` status. These went through the same approval workflow as the 7 `READY` products, just through a different path.
- Excluding `APPROVED` would drop the ready count from 196 → 7, which would be a FALSE NEGATIVE — treating fully-approved mapped products as if they need remediation.
- The `product_catalog_read_model` and mapping audit both treat `APPROVED` as a resolved state.

The script now uses:
```python
MAPPING_READY_STATES = {"READY", "APPROVED", "MAPPED", "COMPLETE"}
```

---

## 9. Canonical vs Reference-Only: Corrected Methodology

**V1 error:** Script treated `source=FASTMOSS` as reference-only. This was wrong.

**Correct methodology:**
- The `product` table has **no `reference_only` column**. The schema `CHECK(source IN ('FASTMOSS','TIKTOKSHOP','MANUAL','IMPORTED'))` — `source` is provenance, not lifecycle.
- `derive_catalog_state()` in `product_catalog_read_model.py` checks `row.get("reference_only")` — this key is injected by the reference workbook loader for products that are NOT in the product table. Product table rows never have this key set.
- `is_fastmoss_reference_product_id()` checks for `fastmoss-ref:*` ID prefix — our FASTMOSS products have UUIDs, not ref prefixes.
- All 516 rows in the `product` table are **committed canonical products**. None are reference-only.

**Limitation:** This script only queries the `product` table. It cannot detect FastMoss reference-only products that live in the external reference workbook (loaded via `list_fastmoss_reference_products()`). Those are out of scope for this product-table-focused audit.

---

## 10. Remaining Gaps

| Gap | Impact | Priority |
|-----|--------|----------|
| Bosmax Oil + Herbs blocked by HIGH claim risk | Cannot generate poster prompts for primary BOSMAX products | **P0** |
| 295 FASTMOSS products with NULL mapping | Were bulk-imported but never mapped. Cannot reach POSTER_READY until mapped. | P1 |
| Confidence is heuristic, not ProductTruthService | Real contradiction detection (boundary locks, taxonomy conflicts) not performed | P2 |
| Only 3 products with local image cache | Hero poster generation limited to 3 products with cached images | P2 |
| Image analysis status all UNRESOLVED or MISSING | No actual vision provider analysis performed on any product image | P3 |

---

## 11. Recommended Pre-Poster Actions

1. **P0:** Clear `claim_risk_level=HIGH` on Bosmax Oil and Bosmax Herbs through claim-safe review.
2. **P1:** Run mapping workflow on 295 FASTMOSS null-mapping products to reach robust mapping.
3. **P2:** Download images for priority categories to increase PRODUCT_HERO_POSTER_READY count beyond 3.
4. **P2:** Replace simple_confidence() with actual `ProductTruthService.build_computed_profile()` for authoritative contradiction detection.
5. **P3:** Enable vision provider for image analysis.

---

## 12. Validation Proof

```
DB Path:      C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db
Command:      python scripts/audit-product-truth-poster-readiness.py
Total:        516
Ready:        196
Preview:      320
Blocked:      0
Categories:   24
Verdict:      PASS
JSON matches: YES (all counts verified identical)
```

| Check | Status |
|-------|--------|
| Raw JSON `poster_ready` matches report | ✅ Both = 196 |
| Script treats APPROVED as ready | ✅ `MAPPING_READY_STATES` includes APPROVED |
| No source=FASTMOSS→ref_only lie | ✅ All 516 are canonical |
| Stricter PASS threshold applied | ✅ 4 checks, all pass |
| Confidence labeled as heuristic | ✅ |
| Bosmax/Minyak targets reported | ✅ Section 7 |
| Image tiers distinguished | ✅ HERO/IMAGE_PROMPT/TEXT_ONLY |
| JSON `verdict_detail` matches threshold checks | ✅ |

---

*Generated by corrected audit script V2 on 2026-07-06. Read-only. No product rows were modified.*
