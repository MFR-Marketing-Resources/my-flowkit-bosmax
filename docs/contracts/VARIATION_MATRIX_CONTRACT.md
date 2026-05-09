# VARIATION MATRIX CONTRACT

## OBJECTIVE
Define how one product brief expands into multiple unique video concepts through controlled variation.

## VARIATION DIMENSIONS
- `hook_angle`
- `copywriting_formula`
- `trigger_id`
- `scene_context`
- `character_route`
- `camera_route`
- `visual_action`
- `overlay_strategy`
- `cta_style`
- `google_flow_mode`
- `asset_strategy`

## DIVERSITY GATES (BATCH CONSTRAINTS)
- **Hook Uniqueness**: No duplicate hooks allowed within the same batch.
- **Visual Isolation**: No duplicate first shots (Section 4) within the same batch.
- **Context Cap**: No duplicate `scene_context` above the configured saturation cap.
- **Camera Cap**: No duplicate `camera_route` above the configured saturation cap.
- **CTA Diversity**: No duplicate `cta_style` above the configured saturation cap.
- **Compliance**: No unsupported claim variations allowed.
- **Safety**: No variations involving unsafe product handling or prohibited physics interactions.

## OUTPUT SCHEMA (PER VARIANT)
```json
{
  "variant_id": "uuid",
  "product_id": "uuid",
  "brief_id": "uuid",
  "variation_index": 1,
  "hook_angle": "",
  "scene_context": "",
  "camera_route": "",
  "copywriting_formula": "",
  "overlay_strategy": "",
  "cta_style": "",
  "google_flow_mode": "Images | Text to Video | Ingredients | Frames",
  "asset_strategy": "WITH_IMAGE | NO_IMAGE | START_FRAME | START_END_FRAMES",
  "diversity_fingerprint": "hash_of_key_dimensions",
  "readiness": "READY | BLOCKED | NEEDS_REVIEW",
  "blocked_reason": []
}
```
