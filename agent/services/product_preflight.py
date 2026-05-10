from __future__ import annotations

from typing import Any

from agent.services.product_mapping import normalize_mapping_text


CREATIVE_REQUIRED_FIELDS = [
    "product_display_name",
    "product_short_name",
    "category",
    "subcategory",
    "type",
    "product_type_id",
    "silo",
    "trigger_id",
    "formula",
    "copywriting_angle",
    "claim_risk_level",
    "physics_class",
    "recommended_grip",
    "handling_notes",
    "camera_handling_notes",
    "scene_context",
    "camera_style",
    "camera_behavior",
    "camera_shot",
    "section_4_hint",
    "section_5_physics_hint",
    "section_6_copy_hint",
    "section_9_overlay_hint",
]

BLOCKING_MAPPING_FIELDS = {
    "category",
    "subcategory",
    "type",
    "product_type_id",
    "silo",
    "trigger_id",
    "formula",
    "physics_class",
    "scene_context",
    "camera_style",
    "camera_behavior",
    "camera_shot",
}


def _joined_text(product: dict[str, Any]) -> str:
    parts = [
        product.get("raw_product_title"),
        product.get("product_display_name"),
        product.get("product_short_name"),
        product.get("category"),
        product.get("subcategory"),
        product.get("type"),
    ]
    return " ".join(normalize_mapping_text(part) for part in parts if part)


def _contains_any(haystack: str, keywords: list[str]) -> bool:
    return any(normalize_mapping_text(keyword) in haystack for keyword in keywords)


def resolve_product_family(product: dict[str, Any]) -> str:
    haystack = _joined_text(product)
    category = normalize_mapping_text(product.get("category"))
    subcategory = normalize_mapping_text(product.get("subcategory"))
    type_name = normalize_mapping_text(product.get("type"))

    if _contains_any(haystack, ["baby wipes", "newborn wet wipes", "wet wipes", "wet tissue", "baby wet tissue", "tisu basah", "tisu basah baby", "baby tissue", "wipes newborn"]):
        return "baby_wipes"
    if _contains_any(haystack, ["diaper", "lampin", "pull ups", "baby diaper"]):
        return "baby_diaper"
    if _contains_any(haystack, ["instant sarung", "sarung syria", "sarung", "syria", "khimar", "telekung", "tudung labuh", "moscrepe"]):
        return "fashion_modestwear"
    if _contains_any(haystack, ["jersey", "jersi", "athleisure", "baju sukan", "quick dry"]):
        return "fashion_sportswear"
    if category == "fashion" and subcategory in {"bottoms", "muslim fashion"}:
        return "fashion_apparel"
    if _contains_any(haystack, ["body spray", "fragrance", "perfume", "body mist"]):
        return "beauty_fragrance"
    if _contains_any(haystack, ["food container", "bekas makanan", "kitchen storage"]):
        return "household_storage"
    if _contains_any(haystack, ["sambal", "ready to eat", "sauce", "food"]):
        return "food_packaged"
    if _contains_any(haystack, ["money packet", "duit raya", "angpow", "envelope"]):
        return "stationery_paper"
    if _contains_any(haystack, ["smartwatch", "wearable", "jam tangan"]):
        return "electronics_wearable"
    if _contains_any(haystack, ["toy", "mainan"]):
        return "toy_play"
    if category == "fashion":
        return "fashion_apparel"
    if category == "baby care" and ("baby wipes" in type_name or "wet wipes" in subcategory or "diapering" in subcategory):
        return "baby_wipes"
    if category == "baby care":
        return "baby_diaper"
    if category == "food beverage" or category == "food and beverage":
        return "food_packaged"
    if category == "beauty personal care":
        return "beauty_fragrance"
    if category == "home living":
        return "household_storage"
    if category == "stationery":
        return "stationery_paper"
    return "generic"


def resolve_creative_profile(product: dict[str, Any]) -> dict[str, Any]:
    family = resolve_product_family(product)
    short_name = (product.get("product_short_name") or product.get("raw_product_title") or "Product").strip()
    category = (product.get("category") or "Product").strip()
    type_name = (product.get("type") or "product").strip()
    copy_angle = (product.get("copywriting_angle") or f"Trust-led {category.lower()} framing").strip()
    physics_hint = (product.get("section_5_product_physics_prompt") or "Keep product handling natural and physically plausible.").strip()

    profiles: dict[str, dict[str, str]] = {
        "baby_wipes": {
            "product_type_id": "BABY_WIPES",
            "handling_notes": "Use supportive soft-pack handling with the front panel, opening edge, and seal kept readable and natural.",
            "scene_context": "clean baby-care tabletop, nursery shelf, or parent-trust hygiene scene with gentle household realism",
            "camera_style": "clean baby-care product close-up",
            "camera_behavior": "slow trust-led reveal with stable front-facing pack support",
            "camera_shot": "hero soft-pack close-up with seal and label detail cut-ins",
            "section_4_hint": "Show the wipes pack in a trust-led baby-care reveal that emphasizes gentle newborn hygiene, pack softness, and clean handling.",
            "section_6_copy_hint": "Keep copy reassuring and hygiene-led without medical, sterilization, or rash-prevention guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a gentle baby-care hygiene line and no medical claims.",
        },
        "baby_diaper": {
            "product_type_id": "BABY_CARE_SOFT_PACK",
            "handling_notes": "Use supportive two-hand pack presentation with the front panel square and readable.",
            "scene_context": "clean baby-care tabletop or nursery shelf with soft household realism",
            "camera_style": "clean commercial tabletop",
            "camera_behavior": "slow supportive reveal with stable front-on framing",
            "camera_shot": "hero pack close-up with gentle push-in",
            "section_4_hint": "Show the diaper pack in a trust-led baby-care reveal focused on softness, pack integrity, and parent confidence.",
            "section_6_copy_hint": "Keep copy practical and reassuring without medical or safety guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a soft baby-care trust line and no medical claims.",
        },
        "fashion_modestwear": {
            "product_type_id": "APPAREL_MODESTWEAR",
            "handling_notes": "Use two-hand fabric spread, edge hold, and controlled drape handling to show coverage, fall, and texture.",
            "scene_context": "modest fashion fitting area, wardrobe rail, or clean indoor apparel scene",
            "camera_style": "modest fashion garment showcase",
            "camera_behavior": "controlled drape reveal with texture-led movement",
            "camera_shot": "mid-shot wardrobe reveal with close fabric cut-ins",
            "section_4_hint": "Reveal the apparel through natural drape, fit, and coverage gestures in a modest fashion context.",
            "section_6_copy_hint": "Use modest-fashion confidence language focused on comfort, drape, elegance, and daily wearability.",
            "section_9_overlay_hint": f"Overlay {short_name} with a modest-fashion comfort or elegance line.",
        },
        "fashion_sportswear": {
            "product_type_id": "APPAREL_ACTIVEWEAR",
            "handling_notes": "Use hanger hold, waistband hold, and stretched-fabric presentation to show fit and quick-dry texture.",
            "scene_context": "clean apparel fitting corner or activewear wardrobe scene",
            "camera_style": "apparel movement showcase",
            "camera_behavior": "energetic but controlled garment reveal",
            "camera_shot": "mid-shot fit reveal with seam detail close-ups",
            "section_4_hint": "Reveal the garment through confident fit and texture-led activewear movement.",
            "section_6_copy_hint": "Keep copy focused on fit, confidence, comfort, and styling instead of performance guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a confidence-led fashion line.",
        },
        "fashion_apparel": {
            "product_type_id": "APPAREL_TEXTILE",
            "handling_notes": "Use two-hand fabric spread and controlled fold or drape handling so cut and texture remain visible.",
            "scene_context": "clean indoor apparel scene with wardrobe or fitting cues",
            "camera_style": "apparel detail commercial",
            "camera_behavior": "gentle drape and silhouette reveal",
            "camera_shot": "mid-shot product reveal with texture close-ups",
            "section_4_hint": "Show the apparel naturally in use with visible drape, seams, and silhouette.",
            "section_6_copy_hint": "Use fashion copy that emphasizes comfort, fit, and versatile styling.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise fashion-benefit line.",
        },
        "beauty_fragrance": {
            "product_type_id": "BEAUTY_FRAGRANCE",
            "handling_notes": "Use careful label-forward bottle handling with elegant wrist and finger positioning.",
            "scene_context": "clean vanity, dressing table, or beauty shelf scene",
            "camera_style": "beauty product close-up",
            "camera_behavior": "slow reflective rotation with label lock",
            "camera_shot": "macro-to-mid bottle reveal",
            "section_4_hint": "Highlight the bottle form, finish, and premium fragrance presentation without implying performance claims.",
            "section_6_copy_hint": "Use scent and daily-confidence framing without exaggerated longevity claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a simple freshness or scent line.",
        },
        "household_storage": {
            "product_type_id": "HOUSEHOLD_STORAGE",
            "handling_notes": "Use stable two-hand handling that shows open-close, stackability, and shape clarity.",
            "scene_context": "clean kitchen counter or organized storage shelf",
            "camera_style": "household utility demo",
            "camera_behavior": "clear open-close demonstration and stack reveal",
            "camera_shot": "utility close-up with countertop hero shot",
            "section_4_hint": "Demonstrate storage utility and clean organization in a practical home setting.",
            "section_6_copy_hint": "Keep copy practical and trust-led around convenience and organization.",
            "section_9_overlay_hint": f"Overlay {short_name} with an organization or convenience line.",
        },
        "food_packaged": {
            "product_type_id": "FOOD_PACKAGED_GOODS",
            "handling_notes": "Use clean sealed-pack or jar handling that keeps labels visible and food-safe cues intact.",
            "scene_context": "clean kitchen counter or appetizing tabletop food scene",
            "camera_style": "food commercial tabletop",
            "camera_behavior": "appetite-led reveal with clean pack framing",
            "camera_shot": "hero pack close-up with serving-context cutaway",
            "section_4_hint": "Show the packaged food clearly with appetite appeal, seal integrity, and practical serving context.",
            "section_6_copy_hint": "Keep copy taste-led and convenience-led without unsupported health claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise taste or convenience line.",
        },
        "stationery_paper": {
            "product_type_id": "PAPER_GOODS_GIFTING",
            "handling_notes": "Use light edge pinch and fan-out presentation to keep printed details readable.",
            "scene_context": "clean tabletop gifting or festive stationery scene",
            "camera_style": "paper goods tabletop",
            "camera_behavior": "gentle fan and stack reveal",
            "camera_shot": "top-down pattern reveal with edge close-ups",
            "section_4_hint": "Show the paper goods in a neat, festive arrangement with clear printed details.",
            "section_6_copy_hint": "Use gifting and presentation language rather than utility claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a gifting-led festive line.",
        },
        "electronics_wearable": {
            "product_type_id": "ELECTRONICS_WEARABLE",
            "handling_notes": "Use precise hand positioning that keeps the screen, band, and profile readable.",
            "scene_context": "clean desk or lifestyle tech setup",
            "camera_style": "tech feature showcase",
            "camera_behavior": "measured product turn with screen-first emphasis",
            "camera_shot": "macro detail cut-ins and wrist-scale hero shot",
            "section_4_hint": "Show the device with clear screen, controls, and wearable scale.",
            "section_6_copy_hint": "Use authority-led feature framing without unverifiable performance claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with one concrete feature-led line.",
        },
        "toy_play": {
            "product_type_id": "TOY_PLAYABLE",
            "handling_notes": "Use safe playful handling that shows scale, interaction, and key parts without chaotic motion.",
            "scene_context": "clean playroom, child-safe tabletop, or cheerful indoor toy scene",
            "camera_style": "playful product demo",
            "camera_behavior": "bright interactive reveal with stable focus on the toy",
            "camera_shot": "toy hero shot with hands-on play close-ups",
            "section_4_hint": "Show how the toy is handled and enjoyed through safe, readable play gestures.",
            "section_6_copy_hint": "Use playful benefit-led copy without developmental guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a simple playful-benefit line.",
        },
        "generic": {
            "product_type_id": "GENERIC_PRODUCT",
            "handling_notes": "Use steady hands, preserve label readability, and keep the product physically plausible.",
            "scene_context": "clean commercial product environment",
            "camera_style": "generic commercial close-up",
            "camera_behavior": "slow stable product reveal",
            "camera_shot": "hero close-up with contextual secondary angle",
            "section_4_hint": "Show the product clearly in a clean environment that matches its likely use.",
            "section_6_copy_hint": "Use grounded product-benefit language with no unverifiable promises.",
            "section_9_overlay_hint": f"Overlay {short_name} with one concise {type_name.lower()} benefit line.",
        },
    }

    profile = dict(profiles.get(family, profiles["generic"]))
    profile["section_5_physics_hint"] = physics_hint
    profile["display_name"] = (product.get("product_display_name") or short_name).strip()
    profile["camera_handling_notes"] = (
        product.get("camera_handling_notes")
        or profile["handling_notes"]
    )
    profile["section_6_copy_hint"] = f"{profile['section_6_copy_hint']} Angle: {copy_angle}."
    return profile


def evaluate_mapping_status(product: dict[str, Any]) -> dict[str, Any]:
    missing_fields: list[str] = []
    for field in CREATIVE_REQUIRED_FIELDS:
        value = product.get(field)
        if isinstance(value, list):
            if not value:
                missing_fields.append(field)
            continue
        if not str(value or "").strip():
            missing_fields.append(field)

    status = "READY"
    mapping_source = (product.get("mapping_source") or "").strip().lower()
    if any(field in BLOCKING_MAPPING_FIELDS for field in missing_fields):
        status = "BLOCKED"
    elif missing_fields or mapping_source == "fallback":
        status = "NEEDS_REVIEW"

    return {
        "mapping_status": status,
        "mapping_missing_fields": missing_fields,
    }


def build_product_preflight(product: dict[str, Any], flow_readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    creative_missing = [
        field for field in [
            "scene_context",
            "camera_style",
            "camera_behavior",
            "camera_shot",
            "section_4_hint",
            "section_5_physics_hint",
            "section_6_copy_hint",
            "section_9_overlay_hint",
        ]
        if not str(product.get(field) or "").strip()
    ]
    prompt_missing = list(product.get("prompt_missing_fields") or [])
    mapping_missing = list(product.get("mapping_missing_fields") or [])
    flow_status = flow_readiness.get("status") if flow_readiness else "NOT_CHECKED"

    blocking_reason = None
    if product.get("mapping_status") == "BLOCKED":
        blocking_reason = f"MAPPING_BLOCKED:{','.join(mapping_missing)}"
    elif product.get("mapping_status") == "NEEDS_REVIEW":
        blocking_reason = f"MAPPING_NEEDS_REVIEW:{','.join(mapping_missing)}"
    elif creative_missing:
        blocking_reason = f"CREATIVE_BRIEF_MISSING:{','.join(creative_missing)}"
    elif prompt_missing:
        blocking_reason = f"PROMPT_NOT_READY:{','.join(prompt_missing)}"
    elif flow_readiness and flow_readiness.get("primary_blocker"):
        blocking_reason = str(flow_readiness["primary_blocker"])

    return {
        "product_id": product.get("id") or product.get("product_id"),
        "mapping_status": product.get("mapping_status") or "BLOCKED",
        "missing_fields": mapping_missing,
        "physics_dna_status": product.get("physics_dna_status") or ("READY" if product.get("physics_class") else "MISSING_FIELDS"),
        "creative_brief_status": "READY" if not creative_missing else "MISSING_FIELDS",
        "creative_missing_fields": creative_missing,
        "prompt_readiness_status": product.get("prompt_readiness_status") or "MISSING_FIELDS",
        "prompt_missing_fields": prompt_missing,
        "flow_readiness_status": flow_status,
        "blocking_reason": blocking_reason,
        "repair_action": f"/api/products/{product.get('id') or product.get('product_id')}/repair-mapping" if (product.get("id") or product.get("product_id")) else "/api/products/{product_id}/repair-mapping",
        "backfill_action": "/api/products/backfill-mapping",
        "flow_readiness_action": "/api/operator/flow-readiness-smoke",
        "build_allowed": not blocking_reason,
    }