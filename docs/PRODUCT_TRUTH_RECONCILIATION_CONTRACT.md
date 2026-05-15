# BOSMAX Product Truth Reconciliation Contract

**Status:** Architecture locked for Phase 1 implementation  
**Contract scope:** `PRODUCT_TRUTH_RECONCILIATION_CONTRACT`  
**First coding scope:** `PRODUCT_TRUTH_PROFILE_READ_ONLY_BUILDER`  
**Base checkpoint:** after PR #41 merge (`47eb8f7995547a526c646c8c94c311c53805ee66`)  

---

## 1. Purpose

BOSMAX must stop deciding product identity from isolated keyword matches.

All product lanes must first produce a normalized evidence object before Product Intelligence Mapping, Product Physics, Copy Route, Claim Gate, Product Readiness, Prompt Asset Generator, and future batch/video/image workflows use the product.

Correct pipeline:

```text
Input Adapters
├── FastMoss Adapter
├── TikTok Shop Link Adapter
└── Manual Product Adapter
        ↓
Product Truth Reconciliation Layer
        ↓
Unified Product Intelligence Profile
        ↓
Product Physics / Copy Route / Claim Gate / Readiness
        ↓
Prompt Asset Generator
```

This contract exists so Codex, Antigravity, and any future agent can continue the same architecture without re-litigating the foundation.

---

## 2. Problem Statement

Current resolver behavior is too close to:

```text
title keyword / generic resolver
→ taxonomy fallback
→ confidence
```

This produced false high-confidence mappings such as:

- Baby Wipes mapped to `BEAUTY_AND_PERSONAL_CARE / beauty_fragrance`.
- Lipmatte or makeup powder mapped to `HOUSEHOLD_CARE / HOME_TEXTILE`.
- Smartwatch mapped to `MALE_HEALTH_SENSITIVE`.
- Normal fashion or pants mapped to `MALE_HEALTH_SENSITIVE`.

Root cause is not only bad rules. The deeper fault is missing evidence reconciliation before mapping.

---

## 3. Current Baseline

The current main branch already includes:

- PR #38: Product Selector Hydration Source Alignment.
- PR #39: Product Image Semantic Analysis Layer.
- PR #41: Products / Sales Analyzer UI Repair + Mapping Audit.

Current mapping audit baseline from PR #41:

```text
total_products = 317
FASTMOSS = 299
MANUAL = 18
suspicious_high_confidence_count = 19
unknown_review_required_count = 31
low_confidence_count = 29
semantic_unavailable_count = 314
image_missing_count = 3
```

Important limitation:

```text
Product Image Semantic Analysis Layer exists, but no real vision/OCR provider is active yet.
Most products return VISION_PROVIDER_NOT_CONFIGURED.
No fake OCR or fake visual package detection is allowed.
```

---

## 4. Three Product Ingestion States

### 4.1 State 1 — FastMoss Lane

Highest potential accuracy lane if source fields are preserved correctly.

Expected evidence:

- FastMoss source row.
- Source category.
- Source subcategory.
- Source product type.
- Source file hint.
- Product title.
- Product image URL or cache reference.
- Source URL.
- TikTok URL.
- Sales/shop metrics.
- Commission data.
- Product Image Semantic Analysis if provider exists.

Rule:

```text
FastMoss source taxonomy must become a source anchor, not a volatile field that keyword rules can casually override.
```

### 4.2 State 2 — TikTok Shop Link Lane

User provides a TikTok Shop link.

Expected extracted evidence:

- Final canonical URL.
- Title.
- Price.
- Sold count.
- Shop name.
- TikTok product category.
- Description.
- Product specs.
- Product images.
- Visible text if OCR/vision exists.
- Dimensions or scale clues.
- Claim phrases.
- Shipping/return signals when available.

Extraction principle:

```text
vt.tiktok.com redirect resolution may use lightweight URL resolution, but product evidence extraction must primarily come from rendered Chrome page DOM via BOSMAX Chrome Extension content script and Local Agent parser.
```

Do not build the core extraction flow on random third-party extensions or unverified private APIs.

### 4.3 State 3 — Manual Entry Lane

User manually enters product details, but the form must mirror TikTok Shop evidence fields.

Expected fields:

- Title.
- User-declared category.
- User-declared subcategory.
- User-declared product type.
- Description/specs.
- Images.
- Price.
- Commission or margin.
- Shop/source info.
- Claims.
- Keywords.

Manual user input is **declared evidence**, not automatic truth.

---

## 5. Normalized Product Truth Profile

The Product Truth Profile is the computed evidence object produced before Product Intelligence Mapping.

### 5.1 Required top-level shape

```json
{
  "product_id": "string | null",
  "provenance": {},
  "source_anchors": {},
  "declared_evidence": {},
  "text_evidence": {},
  "spec_evidence": {},
  "visual_evidence": {},
  "commerce_evidence": {},
  "claim_evidence": {},
  "reconciliation": {},
  "final_output_preview": {}
}
```

### 5.2 Field contract

#### `provenance`

```json
{
  "source_origin": "FASTMOSS | TIKTOKSHOP | MANUAL | INTERNAL_CANONICAL | TEST | UNKNOWN",
  "commerce_mode": "OWN_STORE | AFFILIATE | HYBRID | UNKNOWN",
  "source_url": "string | null",
  "tiktok_product_url": "string | null",
  "source_file_hint": "string | null",
  "ingestion_timestamp": "ISO8601 | null",
  "builder_version": "string"
}
```

#### `source_anchors`

```json
{
  "source_category": "string | null",
  "source_subcategory": "string | null",
  "source_product_type": "string | null",
  "source_anchor_status": "PRESENT | PARTIAL | MISSING | UNVERIFIED",
  "source_anchor_origin": "FASTMOSS_ROW | FASTMOSS_WORKBOOK | TIKTOKSHOP_DOM | MANUAL_DECLARED | UNKNOWN"
}
```

#### `declared_evidence`

```json
{
  "user_category": "string | null",
  "user_subcategory": "string | null",
  "user_product_type": "string | null",
  "manual_authority_status": "NOT_PROVIDED | DECLARED_PENDING_RECONCILIATION | VERIFIED | CONTRADICTED",
  "review_required": "boolean"
}
```

#### `text_evidence`

```json
{
  "raw_title": "string | null",
  "normalized_title": "string | null",
  "description": "string | null",
  "extracted_keywords": [],
  "keyword_matches": [],
  "negative_exclusion_matches": []
}
```

#### `spec_evidence`

```json
{
  "raw_specs": {},
  "normalized_specs": {},
  "dimension_evidence": "string | null",
  "material_evidence": "string | null",
  "power_voltage_evidence": "string | null",
  "spec_status": "PRESENT | PARTIAL | MISSING"
}
```

#### `visual_evidence`

```json
{
  "image_urls": [],
  "image_analysis_status": "ANALYZED | VISION_PROVIDER_NOT_CONFIGURED | IMAGE_MISSING | IMAGE_INACCESSIBLE | ANALYSIS_FAILED | UNKNOWN",
  "analyzed_traits": {
    "scale": { "value": "string | null", "confidence": "number | null" },
    "package": { "value": "string | null", "confidence": "number | null" },
    "text": { "value": [], "confidence": "number | null" }
  },
  "provider": "metadata_only | not_configured | existing_provider_name | unknown"
}
```

#### `commerce_evidence`

```json
{
  "price": "number | null",
  "currency": "string | null",
  "commission_rate": "string | null",
  "commission_amount": "number | null",
  "margin": "number | null",
  "sold_count": "number | null",
  "shop_count": "number | null",
  "shop_names": []
}
```

#### `claim_evidence`

```json
{
  "claim_tokens": [],
  "claim_sources": [],
  "claim_gate_preview": "CLAIM_SAFE | CLAIM_REVIEW_REQUIRED | CLAIM_BLOCKED | UNKNOWN"
}
```

#### `reconciliation`

```json
{
  "contradiction_flags": [],
  "evidence_scores": {},
  "authority_decision": "SOURCE_ANCHOR | TIKTOKSHOP_DOM | MANUAL_DECLARED | KEYWORD_RULE | IMAGE_CORROBORATED | REVIEW_REQUIRED",
  "confidence_score": "number",
  "confidence_label": "HIGH | MEDIUM | LOW | NEEDS_REVIEW",
  "warnings": [],
  "provenance": []
}
```

#### `final_output_preview`

```json
{
  "final_group": "string | null",
  "final_sub_group": "string | null",
  "final_type_of_product": "string | null",
  "bosmax_product_family": "string | null",
  "package_form": "string | null",
  "physical_state": "string | null",
  "product_scale_class": "string | null",
  "copy_route": "DIRECT | STEALTH | REVIEW_REQUIRED | UNKNOWN",
  "claim_gate": "CLAIM_SAFE | CLAIM_REVIEW_REQUIRED | CLAIM_BLOCKED | UNKNOWN"
}
```

---

## 6. Authority Matrix

Authority is field-specific.

| Target field | Primary authority | Secondary authority | Tertiary authority |
|---|---|---|---|
| Product category | Source anchor from workbook/DOM | Manual declared evidence after reconciliation | Keyword/image corroboration |
| Product family | Source anchor from workbook/DOM | Manual declared evidence after reconciliation | Keyword/image corroboration |
| Product scale | Image/OCR when `ANALYZED + HIGH` | Spec evidence / dimensions | Title keyword refinement |
| Package form | Image/OCR when `ANALYZED + HIGH` | Spec evidence | Title keyword refinement |
| Physical state | Image/OCR when `ANALYZED + HIGH` | Spec evidence | Family default |
| Technical specs | DOM evidence | Manual declared evidence | None |
| Claim gate | Claim tokens from title/description/specs | Manual declared claims | Image text if OCR exists |
| Copy route | Product family + claim posture | Source taxonomy | Manual declared category after reconciliation |

Manual input is never absolute truth. It must be represented as declared evidence and reconciled.

Image/OCR does not automatically override category family. It is high authority for physical fields when genuinely analyzed with high confidence.

---

## 7. Confidence Scoring Rules

Labels:

```text
HIGH
MEDIUM
LOW
NEEDS_REVIEW
```

Rules:

- `HIGH` requires source anchor or trusted DOM/manual evidence plus corroborating signal and no contradiction flags.
- A single weak keyword match must never produce `HIGH`.
- If source taxonomy and keyword mapping conflict, force `NEEDS_REVIEW` or downgrade below `HIGH`.
- If manual input conflicts with title/spec/image evidence, add `MANUAL_INPUT_CONTRADICTION_REVIEW_REQUIRED`.
- If image semantic provider is not configured, do not use image as classification evidence.
- If image is `ANALYZED + HIGH`, it can strongly support package form, scale, visible dimensions, and physical state.
- If claim tokens exist, claim gate may require review even when product family is correct.

Contradiction flags include:

```text
KEYWORD_VS_ANCHOR_TAXONOMY
MANUAL_INPUT_CONTRADICTION_REVIEW_REQUIRED
IMAGE_VS_SOURCE_PHYSICS_CONFLICT
SOURCE_ANCHOR_MISSING
SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE
TIKTOKSHOP_EXTRACTION_INCOMPLETE
```

---

## 8. Phase 1 Scope

### First coding scope

```text
PRODUCT_TRUTH_PROFILE_READ_ONLY_BUILDER
```

### Objective

Build a read-only computed Product Truth Profile from existing product rows and current supporting evidence.

### Required behavior

- Create a service such as `ProductTruthService.build_computed_profile(product_row)`.
- Build NPTP from existing product row fields.
- Include source anchors when present.
- Include declared evidence when present.
- Include image_analysis truth from existing layer.
- Include sales/shop/commerce evidence when available.
- Include contradiction flags.
- Include confidence scoring preview.
- Include final output preview.
- Expose read-only inspection endpoint if needed.
- Add full-catalog dry-run report if maintainable.

### Suggested endpoint

```text
GET /api/products/{product_id}/truth-audit
```

Optional catalog-level endpoint or script:

```text
GET /api/product-truth/reconciliation-audit?sample_limit=20
scripts/build_product_truth_report.py
```

### Absolute exclusions

Phase 1 must not:

- Run `ALTER TABLE`.
- Add DB columns.
- Update product rows.
- Persist NPTP to DB.
- Modify `product_mapping_rules.json`.
- Implement live TikTok scraping.
- Connect image vision/OCR provider.
- Start Product Registration.
- Register BOSMAX Oil.
- Start Multi-Mode Prompt Package.
- Touch Google Flow automation.
- Touch `content-flow-dom`.
- Add Generate/upload/batch execution.

---

## 9. Roadmap After Phase 1

### Phase 2 — FastMoss Taxonomy Reconciliation

Scope candidate:

```text
FASTMOSS_TAXONOMY_RECONCILIATION_FIRST
```

Purpose:

- Preserve source category/subcategory/product type as source anchors.
- Audit FastMoss files/workbooks for missing/discarded taxonomy fields.
- Prevent keyword rules from overriding anchors without contradiction handling.

### Phase 3 — Product Intelligence Mapping V2 Repair

Scope candidate:

```text
PRODUCT_INTELLIGENCE_MAPPING_V2_REPAIR_PASS
```

Purpose:

- Use NPTP to repair false high-confidence mapping.
- Correct or downgrade suspicious mappings.
- Prove before/after audit delta.

### Phase 4 — TikTokShop Link Extraction POC

Scope candidate:

```text
TIKTOKSHOP_LINK_EXTRACTION_POC
```

Purpose:

- Resolve short links.
- Use BOSMAX Chrome Extension content script for rendered DOM extraction.
- Capture specs/about/product category/description/images.
- Send raw evidence payload to Local Agent.
- Normalize into NPTP.

### Phase 5 — Manual Product Entry Parity

Scope candidate:

```text
MANUAL_PRODUCT_ENTRY_PARITY
```

Purpose:

- Make manual product entry mirror TikTokShop evidence schema.
- Require source anchors or explicit declared evidence.
- Add contradiction checks.

### Phase 6 — Unified Owned Product Registration Core

Scope candidate:

```text
UNIFIED_PRODUCT_REGISTRATION_OWNED_PRODUCT_CORE
```

Purpose:

- Register owned/canonical products after truth profile and mapping are stable.
- Register BOSMAX Oil 5ml and 10ml after system can safely reconcile product truth.

---

## 10. Agent Work Protocol

Before any coding task in this architecture:

- Start from latest `main`.
- Report base SHA.
- Inspect current files before editing.
- Do not assume previous local changes exist.
- Do not hardcode one product or one sample.
- Add tests proving behavior.
- Provide runtime proof.
- Provide Git branch, commit SHA, PR URL for remote delivery.
- Never claim DONE without proof.

---

## 11. Phase 1 Acceptance Criteria

`PRODUCT_TRUTH_PROFILE_READ_ONLY_BUILDER` passes only if:

- NPTP output exists for FastMoss products.
- NPTP output exists for Manual products.
- No DB write-back occurs.
- No schema migration occurs.
- Image analysis truth is represented honestly.
- Manual fields are represented as declared evidence, not absolute truth.
- Source anchors are clearly separated from keywords.
- Contradiction flags are computed.
- Confidence label is computed without single-keyword HIGH inflation.
- Current false-mapping examples surface as contradiction/review cases.
- Existing Product Intelligence and Product Asset Generator tests still pass.
- Dashboard build passes if dashboard types are touched.

Required proof examples:

- Baby Wipes: should show source/taxonomy vs keyword reconciliation; must not silently become `beauty_fragrance` with HIGH confidence.
- Lipmatte / makeup powder: must not silently become `HOME_TEXTILE` with HIGH confidence.
- Smartwatch: must not silently become `MALE_HEALTH_SENSITIVE` with HIGH confidence.
- Normal fashion/pants: must not silently become `MALE_HEALTH_SENSITIVE` with HIGH confidence.
- One true male-health sensitive sample: must still be representable as sensitive when evidence is real.

---

## 12. Final Lock

The first implementation must be:

```text
PRODUCT_TRUTH_PROFILE_READ_ONLY_BUILDER
```

Do not start:

```text
PRODUCT_INTELLIGENCE_MAPPING_V2_REPAIR_PASS
UNIFIED_PRODUCT_REGISTRATION_OWNED_PRODUCT_CORE
BOSMAX Oil registration
MULTI_MODE_PROMPT_PACKAGE
BATCH_PLANNER
CHROME_EXTENSION_DOM_EXECUTION
```

until this read-only truth layer is proven.

FINAL LINE:
CONTRACT_SCOPE: PRODUCT_TRUTH_RECONCILIATION_CONTRACT
