from __future__ import annotations

from typing import Any

from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_lifecycle_service import lifecycle_status
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
    explicit_family = str(
        product.get("bosmax_product_family")
        or ((product.get("product_intelligence") or {}).get("bosmax_product_family") if isinstance(product.get("product_intelligence"), dict) else "")
        or ""
    ).strip()
    if explicit_family:
        return explicit_family
    return str(derive_bosmax_product_family(product)["bosmax_product_family"])


def resolve_creative_profile(product: dict[str, Any]) -> dict[str, Any]:
    family = resolve_product_family(product)
    short_name = (product.get("product_short_name") or product.get("raw_product_title") or "Product").strip()
    category = (product.get("category") or "Product").strip()
    type_name = (product.get("type") or "product").strip()
    physics_hint = (product.get("section_5_product_physics_prompt") or "Keep product handling natural and physically plausible.").strip()

    profiles: dict[str, dict[str, str]] = {
        "BABY_WIPES": {
            "product_type_id": "BABY_WIPES",
            "copywriting_angle": "Trust-led baby hygiene and gentle newborn care",
            "handling_notes": "Use supportive soft-pack handling with the front panel, opening edge, and seal kept readable and natural.",
            "scene_context": "clean baby-care tabletop, nursery shelf, or parent-trust hygiene scene with gentle household realism",
            "camera_style": "clean baby-care product close-up",
            "camera_behavior": "slow trust-led reveal with stable front-facing pack support",
            "camera_shot": "hero soft-pack close-up with seal and label detail cut-ins",
            "section_4_hint": "Show the wipes pack in a trust-led baby-care reveal that emphasizes gentle newborn hygiene, pack softness, and clean handling.",
            "section_6_copy_hint": "Keep copy reassuring and hygiene-led without medical, sterilization, or rash-prevention guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a gentle baby-care hygiene line and no medical claims.",
        },
        "BABY_DIAPER": {
            "product_type_id": "BABY_CARE_SOFT_PACK",
            "copywriting_angle": "Trust-led baby care with softness and parent confidence",
            "handling_notes": "Use supportive two-hand pack presentation with the front panel square and readable.",
            "scene_context": "clean baby-care tabletop or nursery shelf with soft household realism",
            "camera_style": "clean commercial tabletop",
            "camera_behavior": "slow supportive reveal with stable front-on framing",
            "camera_shot": "hero pack close-up with gentle push-in",
            "section_4_hint": "Show the diaper pack in a trust-led baby-care reveal focused on softness, pack integrity, and parent confidence.",
            "section_6_copy_hint": "Keep copy practical and reassuring without medical or safety guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a soft baby-care trust line and no medical claims.",
        },
        "APPAREL_SLEEPWEAR": {
            "product_type_id": "APPAREL_SLEEPWEAR",
            "copywriting_angle": "Comfort-led sleepwear styling and everyday home wearability",
            "handling_notes": "Use two-hand fabric spread, shoulder hold, and gentle drape handling to show fall, comfort, and silhouette.",
            "scene_context": "clean bedroom corner, wardrobe area, or relaxed home-wear setting",
            "camera_style": "sleepwear detail commercial",
            "camera_behavior": "gentle drape reveal with natural home-use movement",
            "camera_shot": "mid-shot garment reveal with fabric and cut close-ups",
            "section_4_hint": "Show the sleepwear naturally through drape, comfort cues, and a tidy home-use context.",
            "section_6_copy_hint": "Use daily comfort, neatness, and wearable-at-home language without exaggerated claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a sleepwear comfort line.",
        },
        "fashion_modestwear": {
            "product_type_id": "APPAREL_MODESTWEAR",
            "copywriting_angle": "Comfort-led modestwear elegance and daily wear confidence",
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
            "copywriting_angle": "Confidence-led activewear fit and daily motion comfort",
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
            "copywriting_angle": "Comfort-led apparel fit and versatile styling",
            "handling_notes": "Use two-hand fabric spread and controlled fold or drape handling so cut and texture remain visible.",
            "scene_context": "clean indoor apparel scene with wardrobe or fitting cues",
            "camera_style": "apparel detail commercial",
            "camera_behavior": "gentle drape and silhouette reveal",
            "camera_shot": "mid-shot product reveal with texture close-ups",
            "section_4_hint": "Show the apparel naturally in use with visible drape, seams, and silhouette.",
            "section_6_copy_hint": "Use fashion copy that emphasizes comfort, fit, and versatile styling.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise fashion-benefit line.",
        },
        "BEAUTY_PERSONAL_CARE": {
            "product_type_id": "BEAUTY_PERSONAL_CARE",
            "copywriting_angle": "Trust-led beauty and personal care benefits",
            "handling_notes": "Use careful label-forward beauty handling with clean close-up readability.",
            "scene_context": "clean vanity, sink-side, or beauty shelf scene",
            "camera_style": "beauty personal-care close-up",
            "camera_behavior": "slow close-up reveal with texture and label clarity",
            "camera_shot": "close-up bottle or tube hero shot with practical-use context",
            "section_4_hint": "Show the product clearly with clean beauty or personal-care cues and practical handling.",
            "section_6_copy_hint": "Use practical self-care and routine language without unsupported efficacy claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise routine-led beauty line.",
        },
        "beauty_fragrance": {
            "product_type_id": "BEAUTY_FRAGRANCE",
            "copywriting_angle": "Confidence-led scent appeal and everyday freshness",
            "handling_notes": "Use careful label-forward bottle handling with elegant wrist and finger positioning.",
            "scene_context": "clean vanity, dressing table, or beauty shelf scene",
            "camera_style": "beauty product close-up",
            "camera_behavior": "slow reflective rotation with label lock",
            "camera_shot": "macro-to-mid bottle reveal",
            "section_4_hint": "Highlight the bottle form, finish, and premium fragrance presentation without implying performance claims.",
            "section_6_copy_hint": "Use scent and daily-confidence framing without exaggerated longevity claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a simple freshness or scent line.",
        },
        "LAUNDRY_DETERGENT_LIQUID_REFILL": {
            "product_type_id": "HOUSEHOLD_LAUNDRY_DETERGENT",
            "copywriting_angle": "Utility-led laundry cleanliness, refill value, and pakaian wangi framing",
            "handling_notes": "Use stable two-hand carry, bottom support, or cap-side grip to show refill size, front label, and opening detail clearly.",
            "scene_context": "clean laundry corner, washing area, or utility shelf with refill-pack practicality",
            "camera_style": "laundry utility demo",
            "camera_behavior": "practical carry-and-pour reveal with label lock and cap/nozzle detail",
            "camera_shot": "front-label hero shot with refill opening or cap detail cut-ins",
            "section_4_hint": "Demonstrate the detergent through practical laundry-use cues, refill scale, and clean label visibility.",
            "section_6_copy_hint": "Use washing-routine, refill quantity, and pakaian bersih/wangi language without unsupported antibacterial or safety claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a practical laundry-benefit line.",
        },
        "FABRIC_SOFTENER_LIQUID": {
            "product_type_id": "HOUSEHOLD_FABRIC_SOFTENER",
            "copywriting_angle": "Comfort-led fabric softness and pakaian wangi routine framing",
            "handling_notes": "Use stable bottle or pouch handling that keeps the label, cap, and pour direction visible.",
            "scene_context": "clean laundry shelf, washing area, or fabric-care utility scene",
            "camera_style": "fabric-care product demo",
            "camera_behavior": "steady label-forward reveal with pour-ready detail",
            "camera_shot": "front-label hero shot with cap or nozzle detail",
            "section_4_hint": "Show the fabric-care product through clean handling, label clarity, and practical routine cues.",
            "section_6_copy_hint": "Use softness, freshness, and routine comfort language without unsupported performance guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a fabric-care comfort line.",
        },
        "HOUSEHOLD_CLEANER_GENERAL": {
            "product_type_id": "HOUSEHOLD_CLEANER_GENERAL",
            "copywriting_angle": "Utility-led household cleaning and practical routine clarity",
            "handling_notes": "Use stable two-hand handling or supported bottle grip to keep the label and opening detail readable.",
            "scene_context": "clean utility area, kitchen sink-side, or household cleaning setup",
            "camera_style": "household cleaner demo",
            "camera_behavior": "steady utility reveal with practical-use framing",
            "camera_shot": "label-forward cleaner hero shot with cap/nozzle detail",
            "section_4_hint": "Show the cleaner clearly in a practical household-use setting with visible label and format cues.",
            "section_6_copy_hint": "Use practical cleaning-routine language without exaggerated safety or efficacy claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise cleaning-utility line.",
        },
        "HOUSEHOLD_STORAGE_ORGANIZER": {
            "product_type_id": "HOUSEHOLD_STORAGE",
            "copywriting_angle": "Comfort-led storage convenience and organization",
            "handling_notes": "Use stable two-hand handling that shows open-close, stackability, and shape clarity.",
            "scene_context": "clean kitchen counter or organized storage shelf",
            "camera_style": "household utility demo",
            "camera_behavior": "clear open-close demonstration and stack reveal",
            "camera_shot": "utility close-up with countertop hero shot",
            "section_4_hint": "Demonstrate storage utility and clean organization in a practical home setting.",
            "section_6_copy_hint": "Keep copy practical and trust-led around convenience and organization.",
            "section_9_overlay_hint": f"Overlay {short_name} with an organization or convenience line.",
        },
        "HOME_TEXTILE": {
            "product_type_id": "HOME_TEXTILE",
            "copywriting_angle": "Comfort-led textile texture and home coziness",
            "handling_notes": "Use two-hand spread, fold, or drape handling to show thickness, texture, and surface detail naturally.",
            "scene_context": "clean bedroom, bathroom, or soft-home furnishing scene",
            "camera_style": "home textile detail commercial",
            "camera_behavior": "gentle spread-and-texture reveal with stable folds",
            "camera_shot": "texture close-up with broad textile hero framing",
            "section_4_hint": "Show the textile through thickness, drape, and texture clarity in a clean home setting.",
            "section_6_copy_hint": "Use softness, comfort, and practical home-use language without exaggerated claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise comfort or texture line.",
        },
        "food_packaged": {
            "product_type_id": "FOOD_PACKAGED_GOODS",
            "copywriting_angle": "Taste-led packaged-food convenience and appetite framing",
            "handling_notes": "Use clean sealed-pack or jar handling that keeps labels visible and food-safe cues intact.",
            "scene_context": "clean kitchen counter or appetizing tabletop food scene",
            "camera_style": "food commercial tabletop",
            "camera_behavior": "appetite-led reveal with clean pack framing",
            "camera_shot": "hero pack close-up with serving-context cutaway",
            "section_4_hint": "Show the packaged food clearly with appetite appeal, seal integrity, and practical serving context.",
            "section_6_copy_hint": "Keep copy taste-led and convenience-led without unsupported health claims.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise taste or convenience line.",
        },
        "ACCESSORY_SMALL_ITEM": {
            "product_type_id": "ACCESSORY_SMALL_ITEM",
            "copywriting_angle": "Style-led small-detail accessorizing",
            "handling_notes": "Use light fingertip handling that keeps detail, finish, and silhouette readable in close-up.",
            "scene_context": "clean tabletop styling scene or close-up accessory setup",
            "camera_style": "accessory close-up detail",
            "camera_behavior": "controlled close-up reveal with detail lock",
            "camera_shot": "macro detail cut-ins with small-item hero shot",
            "section_4_hint": "Show the accessory through close-up detail, finish clarity, and natural styling context.",
            "section_6_copy_hint": "Use style, matching, and detail-led language without overclaiming transformation.",
            "section_9_overlay_hint": f"Overlay {short_name} with a concise style-detail line.",
        },
        "stationery_paper": {
            "product_type_id": "PAPER_GOODS_GIFTING",
            "copywriting_angle": "Festive gifting and presentation clarity",
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
            "copywriting_angle": "Authority-led wearable feature and daily utility framing",
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
            "copywriting_angle": "Trust-led playful value and family-friendly fun",
            "handling_notes": "Use safe playful handling that shows scale, interaction, and key parts without chaotic motion.",
            "scene_context": "clean playroom, child-safe tabletop, or cheerful indoor toy scene",
            "camera_style": "playful product demo",
            "camera_behavior": "bright interactive reveal with stable focus on the toy",
            "camera_shot": "toy hero shot with hands-on play close-ups",
            "section_4_hint": "Show how the toy is handled and enjoyed through safe, readable play gestures.",
            "section_6_copy_hint": "Use playful benefit-led copy without developmental guarantees.",
            "section_9_overlay_hint": f"Overlay {short_name} with a simple playful-benefit line.",
        },
        "GENERIC_UNCLASSIFIED": {
            "product_type_id": "GENERIC_PRODUCT",
            "copywriting_angle": f"Trust-led {category.lower()} framing",
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

    profile = dict(profiles.get(family, profiles["GENERIC_UNCLASSIFIED"]))
    copy_angle = profile.get("copywriting_angle") or (product.get("copywriting_angle") or f"Trust-led {category.lower()} framing").strip()
    profile["section_5_physics_hint"] = physics_hint
    profile["display_name"] = (product.get("product_display_name") or short_name).strip()
    profile["bosmax_product_family"] = family
    profile["copywriting_angle"] = copy_angle
    profile["camera_handling_notes"] = (
        product.get("camera_handling_notes")
        or profile["handling_notes"]
    )
    profile["section_6_copy_hint"] = f"{profile['section_6_copy_hint']} Angle: {copy_angle}."
    return profile


_GENERIC_PRODUCT_TYPE_IDS = {"", "GENERIC_PRODUCT", "UNIVERSAL"}
_GENERIC_SCENE_VALUES = {
    "clean commercial product environment",
    "clean commercial product environment ",
}
_GENERIC_CAMERA_STYLE_VALUES = {"generic commercial close-up"}
_GENERIC_CAMERA_BEHAVIOR_VALUES = {"slow stable product reveal"}
_GENERIC_CAMERA_SHOT_VALUES = {"hero close-up with contextual secondary angle"}


def apply_creative_profile_overrides(product: dict[str, Any], creative_profile: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product)
    payload["bosmax_product_family"] = creative_profile.get("bosmax_product_family") or payload.get("bosmax_product_family")
    payload["copywriting_angle"] = creative_profile.get("copywriting_angle") or payload.get("copywriting_angle")

    generic_product_type = str(payload.get("product_type_id") or "").strip() in _GENERIC_PRODUCT_TYPE_IDS
    if generic_product_type and creative_profile.get("product_type_id"):
        payload["product_type_id"] = creative_profile["product_type_id"]

    override_rules = {
        "handling_notes": lambda value: not str(value or "").strip(),
        "camera_handling_notes": lambda value: not str(value or "").strip(),
        "scene_context": lambda value: normalize_mapping_text(value) in _GENERIC_SCENE_VALUES or not str(value or "").strip(),
        "camera_style": lambda value: normalize_mapping_text(value) in _GENERIC_CAMERA_STYLE_VALUES or not str(value or "").strip(),
        "camera_behavior": lambda value: normalize_mapping_text(value) in _GENERIC_CAMERA_BEHAVIOR_VALUES or not str(value or "").strip(),
        "camera_shot": lambda value: normalize_mapping_text(value) in _GENERIC_CAMERA_SHOT_VALUES or not str(value or "").strip(),
        "section_4_hint": lambda value: not str(value or "").strip() or str(value).strip() == "Show the product clearly in a clean environment that matches its likely use.",
        "section_6_copy_hint": lambda value: not str(value or "").strip() or "comfort-led household utility and organization" in str(value).strip().lower(),
        "section_9_overlay_hint": lambda value: not str(value or "").strip(),
    }
    for field, should_override in override_rules.items():
        if should_override(payload.get(field)) and creative_profile.get(field):
            payload[field] = creative_profile[field]
    return payload


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
    product_lifecycle_status = lifecycle_status(product)
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
    if product_lifecycle_status == "ARCHIVED":
        blocking_reason = "PRODUCT_ARCHIVED"
    elif product.get("mapping_status") == "BLOCKED":
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
        "lifecycle_status": product_lifecycle_status,
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
        "safe_to_generate_prompt": blocking_reason is None,
    }
