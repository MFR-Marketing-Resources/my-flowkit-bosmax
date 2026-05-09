# PRODUCT CREATIVE BRIEF CONTRACT

## OBJECTIVE
Define one canonical object generated from Sales Analyzer to guide the creative process.

## SCHEMA
```json
{
  "brief_id": "uuid",
  "product_id": "uuid",
  "product_intelligence": {
    "product_short_name": "",
    "raw_product_title": "",
    "category": "",
    "subcategory": "",
    "type": "",
    "price": null,
    "commission_rate": null,
    "image_readiness_status": "",
    "source_url": "",
    "tiktok_product_url": ""
  },
  "physics_dna": {
    "physics_class": "",
    "product_scale": "",
    "recommended_grip": "",
    "hand_object_interaction": "",
    "material_behavior": "",
    "surface_behavior": "",
    "unsafe_handling_rules": [],
    "section_5_product_physics_prompt": ""
  },
  "copywriting_route": {
    "product_type": "",
    "silo": "",
    "trigger_id": "",
    "formula": "",
    "copywriting_angle": "",
    "claim_risk_level": ""
  },
  "creative_mapping": {
    "character_recommendations": [],
    "scene_context_recommendations": [],
    "camera_recommendations": [],
    "mode_recommendations": []
  },
  "readiness": {
    "Images": "READY | BLOCKED | NEEDS_REVIEW",
    "Ingredients": "READY | BLOCKED | NEEDS_REVIEW",
    "Frames": "READY | BLOCKED | NEEDS_REVIEW",
    "Text to Video": "READY | BLOCKED | NEEDS_REVIEW"
  },
  "missing_fields": []
}
```

## ACCEPTANCE CRITERIA
1. **Product Mapping Dependency**: Brief cannot be `READY` if product mapping is missing.
2. **Asset Dependency**: `Images`, `Ingredients`, and `Frames` cannot be `READY` if the primary product image is missing.
3. **Metadata Independence**: `Text to Video` may be `READY_OR_NEEDS_REVIEW` without an image if metadata, physics DNA, and copywriting route are complete.
4. **Canonical Source**: The Operator must eventually consume this brief as a single source of truth, rather than scattered manual fields.
