# Product Truth Poster Readiness Audit V3 (generated)

**Generated:** 2026-07-06T09:23:46Z  
**DB Path:** `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`  
**Command:** `python scripts/audit-product-truth-poster-readiness.py`  
**Script version:** V3 (JSON + markdown from single `output` dict)

---

## Scoped executive verdict

- **Generic product-table poster module readiness:** PASS
- **Primary BOSMAX poster generation (Bosmax Oil / Bosmax Herbs):** HOLD
- **Minyak Warisan Tok Cap Burung poster testing:** READY

> PASS for generic product-table poster module readiness applies only when threshold checks pass on committed `product` rows.  
> Primary BOSMAX products remain blocked by `CLAIM_RISK_HIGH` until claim review clears risk.  
> Do not imply BOSMAX poster generation is ready.

**Threshold detail:** 196 POSTER_READY (>=5), 24 categories (>=3), 1 target product(s) (>=1), 1 with local/downloaded image (>=1)

---

## Product counts (from script)

| Metric | Count |
|--------|-------|
| Total products | 516 |
| Active | 516 |
| Archived | 0 |
| With raw_product_title | 516 |
| With product_display_name | 516 |
| With product_short_name | 516 |
| With category | 510 |
| With subcategory | 510 |
| With type | 508 |
| Mapping robust (READY+APPROVED+…) | 211 |
| Mapping NULL | 302 |
| Mapping BLOCKED | 3 |
| With image_url (non-empty string) | 505 |
| With usable remote image_url | 503 |
| With local_image_path | 3 |
| image_asset DOWNLOADED | 3 |
| image_asset IMAGE_READY | 0 |
| IMG in production_prompt_approved_modes | 495 |
| POSTER_READY | 196 |
| POSTER_PREVIEW_ONLY | 320 |
| POSTER_BLOCKED | 0 |

**Sources:** {"FASTMOSS": 298, "MANUAL": 218}  
**Mapping breakdown:** {"MISSING": 302, "READY": 7, "APPROVED": 204, "BLOCKED": 3}

---

## Claim-safe copy status

| Status | Count |
|--------|-------|
| CLAIM_SAFE_COPY_APPROVED | 300 |
| CLAIM_SAFE_COPY_REVIEW_READY | 195 |
| CLAIM_SAFE_COPY_PREVIEW_ONLY | 13 |
| MISSING | 8 |

## Claim risk level

| Level | Count |
|-------|-------|
| MISSING | 305 |
| LOW | 206 |
| HIGH | 3 |
| MEDIUM | 2 |

---

## Confidence (heuristic only)

Confidence labels use simplified heuristic ONLY. NOT ProductTruthService.build_computed_profile().

| Label | Count |
|-------|-------|
| LOW (heuristic) | 302 |
| MEDIUM (heuristic) | 208 |
| HIGH (heuristic) | 3 |
| NEEDS_REVIEW (heuristic) | 3 |

---

## Image tiers

| Tier | Count |
|------|-------|
| PRODUCT_IMAGE_PROMPT_READY | 503 |
| TEXT_ONLY_POSTER_READY | 10 |
| PRODUCT_HERO_POSTER_READY | 3 |

---

## Top blockers (preview + blocked)

| Blocker | Count |
|---------|-------|
| `MAPPING_MISSING` | 302 |
| `IMG_NOT_PROD_APPROVED` | 21 |
| `NO_IMAGE` | 10 |
| `MISSING_CATEGORY` | 6 |
| `MISSING_SUBCAT_AND_TYPE` | 6 |
| `CLAIM_RISK_HIGH` | 3 |
| `MAPPING_BLOCKED` | 3 |

---

## Target product readiness

| Product | poster_tier | mapping | claim_risk | image_url_raw | image_url_usable | local_image_path | image_asset_status | image_tier | blocker |
|---------|-------------|---------|------------|---------------|------------------|------------------|--------------------|------------|---------|
| Bosmax Oil 10 ML | POSTER_PREVIEW_ONLY | APPROVED | HIGH | UNKNOWN | False | yes | DOWNLOADED | PRODUCT_HERO_POSTER_READY | CLAIM_RISK_HIGH |
| Bosmax Herbs 5 ML | POSTER_PREVIEW_ONLY | READY | HIGH | UNKNOWN | False | yes | DOWNLOADED | PRODUCT_HERO_POSTER_READY | CLAIM_RISK_HIGH |
| Minyak Warisan Tok Cap Burung 25ml | POSTER_READY | READY | MEDIUM | null | False | yes | DOWNLOADED | PRODUCT_HERO_POSTER_READY | None |

---

## Samples

### Samples Ready

| product_id | display_name | source | mapping | image_tier | claim | confidence | blocker |
|------------|--------------|--------|---------|------------|-------|------------|---------|
| `de3ee6bd…` | 【KKM】7LUME White Tomato（Buy 3 Save RM8）S | FASTMOSS | READY | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | HIGH (heuristic) | None |
| `3bc08dc9…` | Sumikko 50PCS Premium Baby Diaper pants  | FASTMOSS | READY | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | HIGH (heuristic) | None |
| `ef9c117e…` | Wooden Curtain Rod Batang Langsir Kayu L | MANUAL | APPROVED | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_REVIEW_READY | MEDIUM (heuristic) | None |
| `29db89c6…` | Sabun Dobi Malaya Combo isi ulang 10 KG  | MANUAL | APPROVED | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_REVIEW_READY | MEDIUM (heuristic) | None |
| `6c70428f…` | [KKM] FEREENA GLUTA SOAP 10g | MANUAL | APPROVED | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_REVIEW_READY | MEDIUM (heuristic) | None |

### Samples Preview

| product_id | display_name | source | mapping | image_tier | claim | confidence | blocker |
|------------|--------------|--------|---------|------------|-------|------------|---------|
| `8ae553d2…` | CLASSY 6XXXL Size Karpet Velvet Paling B | FASTMOSS | None | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | LOW (heuristic) | MAPPING_MISSING |
| `bd96da55…` | Elianto Body Spray Fragrance Mist Pewang | FASTMOSS | None | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | LOW (heuristic) | MAPPING_MISSING |
| `3b51d01e…` | QAYRAA P1 (S-XL) Jersi Muslimah Labuh Mi | FASTMOSS | None | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | LOW (heuristic) | MAPPING_MISSING |
| `1c5b5c1a…` | UNICO LEMON TTOX ( 10 PAKET) | FASTMOSS | None | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | LOW (heuristic) | MAPPING_MISSING |
| `dcf0b2a3…` | Seluar Tarik Ke Atas, SUMIKKO, 50PCS, La | FASTMOSS | None | PRODUCT_IMAGE_PROMPT_READY | CLAIM_SAFE_COPY_APPROVED | LOW (heuristic) | MAPPING_MISSING |

### Samples Blocked

| product_id | display_name | source | mapping | image_tier | claim | confidence | blocker |
|------------|--------------|--------|---------|------------|-------|------------|---------|

---

## Consistency check (script)

| Key | JSON value | Embedded in this report |
|-----|------------|-------------------------|
| total | 516 | 516 | OK |
| with_category | 510 | 510 | OK |
| with_subcategory | 510 | 510 | OK |
| with_type | 508 | 508 | OK |
| poster_ready | 196 | 196 | OK |
| poster_preview | 320 | 320 | OK |
| poster_blocked | 0 | 0 | OK |
| mapping_robust | 211 | 211 | OK |
| with_local_image | 3 | 3 | OK |
| ready_category_count | 24 | 24 | OK |
| target_ready_count | 1 | 1 | OK |
| confidence:LOW (heuristic) | 302 | 302 | OK |
| confidence:MEDIUM (heuristic) | 208 | 208 | OK |
| confidence:HIGH (heuristic) | 3 | 3 | OK |
| confidence:NEEDS_REVIEW (heuristic) | 3 | 3 | OK |
| claim_safe:CLAIM_SAFE_COPY_APPROVED | 300 | 300 | OK |
| claim_safe:CLAIM_SAFE_COPY_REVIEW_READY | 195 | 195 | OK |
| claim_safe:CLAIM_SAFE_COPY_PREVIEW_ONLY | 13 | 13 | OK |
| claim_safe:MISSING | 8 | 8 | OK |
| blocker:MAPPING_MISSING | 302 | 302 | OK |
| blocker:IMG_NOT_PROD_APPROVED | 21 | 21 | OK |
| blocker:NO_IMAGE | 10 | 10 | OK |
| blocker:MISSING_CATEGORY | 6 | 6 | OK |
| blocker:MISSING_SUBCAT_AND_TYPE | 6 | 6 | OK |
| blocker:CLAIM_RISK_HIGH | 3 | 3 | OK |
| blocker:MAPPING_BLOCKED | 3 | 3 | OK |

**All metrics match:** True

---

## Notes

- ALL rows in the product table are canonical committed product rows.
- source=FASTMOSS is provenance, not reference-only lifecycle.
- mapping_status=APPROVED is a valid ready state alongside READY.

*End of generated report.*
