from __future__ import annotations

from typing import Any

from agent.services.product_mapping import normalize_mapping_text


def _rule(
    *,
    physics_class: str,
    product_scale: str,
    hand_object_interaction: str,
    recommended_grip: str,
    air_gap_rule: str,
    material_behavior: str,
    surface_behavior: str,
    fragility_level: str,
    camera_handling_notes: str,
    unsafe_handling_rules: list[str],
) -> dict[str, Any]:
    section_5_prompt = (
        f"Physics DNA: {physics_class}. Scale: {product_scale}. "
        f"Hand-object interaction: {hand_object_interaction}. Recommended grip: {recommended_grip}. "
        f"Air-gap rule: {air_gap_rule}. Material behavior: {material_behavior}. "
        f"Surface behavior: {surface_behavior}. Fragility: {fragility_level}. "
        f"Camera handling notes: {camera_handling_notes}. Avoid: {'; '.join(unsafe_handling_rules)}."
    )
    return {
        "physics_class": physics_class,
        "product_scale": product_scale,
        "hand_object_interaction": hand_object_interaction,
        "recommended_grip": recommended_grip,
        "air_gap_rule": air_gap_rule,
        "material_behavior": material_behavior,
        "surface_behavior": surface_behavior,
        "fragility_level": fragility_level,
        "camera_handling_notes": camera_handling_notes,
        "unsafe_handling_rules": unsafe_handling_rules,
        "section_5_product_physics_prompt": section_5_prompt,
    }


PHYSICS_RULES: list[tuple[list[str], dict[str, Any]]] = [
    (
        ["diaper", "lampin", "pull ups", "pull-ups", "baby diaper"],
        _rule(
            physics_class="SOFT_PACKAGED_GOODS",
            product_scale="MEDIUM_PACK",
            hand_object_interaction="supportive two-hand presentation of a soft compressible pack",
            recommended_grip="flat palm support or light side pinch",
            air_gap_rule="keep fingers clear of the front branding panel when possible",
            material_behavior="soft plastic packaging with compressible edges and slight crinkle response",
            surface_behavior="matte-soft pack with mild highlights on sealed edges",
            fragility_level="LOW",
            camera_handling_notes="keep the pack front-facing, squared, and stable during turns",
            unsafe_handling_rules=["do not show a baby wearing the product", "do not imply medical claims", "avoid crushed pack presentation"],
        ),
    ),
    (
        ["jersey", "jersi", "seluar", "pants", "trousers", "athleisure", "baju sukan", "muslimah"],
        _rule(
            physics_class="FLEXIBLE_FABRIC",
            product_scale="GARMENT",
            hand_object_interaction="fabric drape, fold, spread, and controlled lift",
            recommended_grip="hanger hold, two-hand fabric spread, or waistband hold",
            air_gap_rule="keep visible separation so fabric silhouette and seams remain readable",
            material_behavior="soft textile with fold memory, drape, and edge flutter",
            surface_behavior="microfiber or cotton-like weave with natural crease response",
            fragility_level="LOW",
            camera_handling_notes="present the garment stretched just enough to reveal cut, stitching, and texture",
            unsafe_handling_rules=["avoid body-shape exaggeration claims", "avoid unnatural stretch deformation"],
        ),
    ),
    (
        ["body spray", "perfume", "fragrance", "mist", "roll on", "roll-on"],
        _rule(
            physics_class="A",
            product_scale="SMALL_OBJECT",
            hand_object_interaction="delicate bottle handling with clear label presentation",
            recommended_grip="elegant pinch or side hold with label visible",
            air_gap_rule="maintain clear finger separation from the label and nozzle area",
            material_behavior="glossy bottle or canister with rigid cap and reflective highlights",
            surface_behavior="specular reflections on bottle edges and nozzle/cap transitions",
            fragility_level="MEDIUM",
            camera_handling_notes="keep reflections controlled and label legible while rotating the bottle slowly",
            unsafe_handling_rules=["avoid fake spray plume contact on skin", "avoid unsupported efficacy claims"],
        ),
    ),
    (
        ["food container", "bekas makanan", "bekas kedap udara", "container set"],
        _rule(
            physics_class="RIGID_CONTAINER",
            product_scale="MEDIUM_OBJECT",
            hand_object_interaction="stable two-hand or single-hand lid-off presentation of a rigid storage container",
            recommended_grip="side grip on the container wall or lid edge hold",
            air_gap_rule="keep fingers clear of the transparent body and lid seal when demonstrating closure",
            material_behavior="rigid plastic body with snap-fit or press-fit lid response",
            surface_behavior="semi-gloss plastic with clear edge reflections and visible container depth",
            fragility_level="LOW",
            camera_handling_notes="show lid open-close action and stackable form without implying food is included unless visible",
            unsafe_handling_rules=["avoid edible implication when container is empty", "avoid warped lid presentation"],
        ),
    ),
    (
        ["sambal", "jar", "sachet", "mee kari", "food", "sauce"],
        _rule(
            physics_class="B",
            product_scale="SMALL_CONTAINER",
            hand_object_interaction="stable side-hold or pinch presentation of sealed food packaging",
            recommended_grip="jar side hold or pack pinch",
            air_gap_rule="leave the front label unobstructed and the seal area visible",
            material_behavior="rigid jar or flexible sachet with food-safe sealed surfaces",
            surface_behavior="glossy label, mild oil sheen cues, and container edge reflections",
            fragility_level="LOW",
            camera_handling_notes="present as clean and food-safe, with lid or seal clearly intact",
            unsafe_handling_rules=["avoid unsupported health claims", "avoid messy spills unless intentional food styling is shown"],
        ),
    ),
    (
        ["sampul duit raya", "money packet", "angpow", "red packet", "envelope"],
        _rule(
            physics_class="PAPER_GOODS",
            product_scale="SMALL_FLAT_OBJECT",
            hand_object_interaction="fan, stack, or single-piece presentation of thin paper goods",
            recommended_grip="light pinch on the edge or corner to keep the front face visible",
            air_gap_rule="preserve visible separation between overlapping envelopes so design details remain readable",
            material_behavior="thin paper stock with slight bend memory and crisp fold lines",
            surface_behavior="matte or light satin paper finish with printed design visibility",
            fragility_level="LOW",
            camera_handling_notes="keep edges aligned and surfaces clean so printed festive details stay legible",
            unsafe_handling_rules=["avoid torn edges", "avoid cash implication unless explicitly shown as packaging use"],
        ),
    ),
    (
        ["carpet", "karpet", "rug", "mat", "pillow", "bantal"],
        _rule(
            physics_class="D",
            product_scale="LARGE_SOFT_GOOD",
            hand_object_interaction="two-hand lift, fold, roll, unroll, or fluff presentation",
            recommended_grip="two-hand corner lift or broad palm support",
            air_gap_rule="maintain enough lift for the textile edge and thickness to read on camera",
            material_behavior="textile fiber body with bend, roll, compression, and rebound",
            surface_behavior="visible fiber texture, pile direction, and soft shadowing",
            fragility_level="LOW",
            camera_handling_notes="show thickness, texture, and recovery without abrupt shaking",
            unsafe_handling_rules=["avoid dragging on dirty surfaces", "avoid unrealistic floating folds"],
        ),
    ),
]


def resolve_product_physics(
    *,
    product: dict[str, Any] | None = None,
    product_name: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    type_name: str | None = None,
) -> dict[str, Any]:
    existing_payload = None
    if product and all(product.get(field) for field in [
        "physics_class",
        "product_scale",
        "hand_object_interaction",
        "recommended_grip",
        "air_gap_rule",
        "material_behavior",
        "surface_behavior",
        "fragility_level",
        "camera_handling_notes",
        "section_5_product_physics_prompt",
    ]):
        existing_payload = {key: product.get(key) for key in [
            "physics_class", "product_scale", "hand_object_interaction", "recommended_grip", "air_gap_rule",
            "material_behavior", "surface_behavior", "fragility_level", "camera_handling_notes",
            "unsafe_handling_rules", "section_5_product_physics_prompt",
        ]}
        if isinstance(existing_payload.get("unsafe_handling_rules"), str):
            existing_payload["unsafe_handling_rules"] = [item.strip() for item in existing_payload["unsafe_handling_rules"].split("|") if item.strip()]

    title = normalize_mapping_text(product_name or (product or {}).get("raw_product_title") or "")
    taxonomy = " ".join(
        normalize_mapping_text(part)
        for part in [category or (product or {}).get("category"), subcategory or (product or {}).get("subcategory"), type_name or (product or {}).get("type")]
        if part
    )
    haystack = f"{title} {taxonomy}".strip()

    for keywords, rule in PHYSICS_RULES:
        if any(normalize_mapping_text(keyword) in haystack for keyword in keywords):
            return dict(rule)

    if existing_payload:
        return existing_payload

    return {
        "physics_class": "",
        "product_scale": "",
        "hand_object_interaction": "",
        "recommended_grip": "",
        "air_gap_rule": "",
        "material_behavior": "",
        "surface_behavior": "",
        "fragility_level": "",
        "camera_handling_notes": "",
        "unsafe_handling_rules": [],
        "section_5_product_physics_prompt": "",
    }


def evaluate_prompt_readiness(product: dict[str, Any], physics: dict[str, Any]) -> dict[str, Any]:
    missing_fields: list[str] = []
    if not (product.get("product_short_name") or "").strip():
        missing_fields.append("product_short_name")
    if not (product.get("category") or "").strip():
        missing_fields.append("category")
    if not (product.get("subcategory") or "").strip():
        missing_fields.append("subcategory")
    if not (product.get("type") or "").strip():
        missing_fields.append("type")
    image_ready = product.get("image_readiness_status") in {"IMAGE_READY", "IMAGE_CACHE_READY"}
    if not image_ready and not ((product.get("image_url") or "").strip() or (product.get("local_image_path") or "").strip()):
        missing_fields.append("image")
    elif not image_ready and product.get("image_readiness_status") in {"IMAGE_DOWNLOAD_FAILED", "IMAGE_NOT_AVAILABLE", "IMAGE_URL_MISSING", "IMAGE_URL_MISSING_FROM_SOURCE"}:
        missing_fields.append("image")
    if not (physics.get("physics_class") or "").strip():
        missing_fields.append("physics_class")
    if not (physics.get("section_5_product_physics_prompt") or "").strip():
        missing_fields.append("section_5_product_physics_prompt")
    if not (product.get("copywriting_angle") or "").strip():
        missing_fields.append("copywriting_angle")
    if not (product.get("claim_risk_level") or "").strip():
        missing_fields.append("claim_risk_level")

    status = "READY" if not missing_fields else ("NEEDS_REVIEW" if len(missing_fields) <= 2 else "MISSING_FIELDS")
    return {
        "prompt_readiness_status": status,
        "prompt_missing_fields": missing_fields,
        "physics_dna_status": "READY" if physics.get("physics_class") else "MISSING_FIELDS",
        "section_4_visual_action_prompt": f"Show {product.get('product_short_name') or 'the product'} in a clear commercial action that highlights {product.get('type') or 'its form'}.",
        "section_6_dialogue_prompt": product.get("copywriting_angle") or "",
        "section_9_overlay_prompt": f"Overlay: {product.get('product_short_name') or 'Product'} | {product.get('category') or 'Unmapped'}",
    }