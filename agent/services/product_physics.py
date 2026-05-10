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
    handling_notes: str | None = None,
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
        "handling_notes": handling_notes or camera_handling_notes,
        "camera_handling_notes": camera_handling_notes,
        "unsafe_handling_rules": unsafe_handling_rules,
        "section_5_product_physics_prompt": section_5_prompt,
        "section_5_physics_hint": section_5_prompt,
    }


PHYSICS_RULES: list[tuple[list[str], dict[str, Any]]] = [
    (
        ["baby wipes", "newborn wet wipes", "wet wipes", "wet tissue", "baby wet tissue", "tisu basah", "tisu basah baby", "baby tissue", "wipes newborn", "baby wipes"],
        _rule(
            physics_class="WIPES_SOFT_PACK",
            product_scale="SOFT_PACK",
            hand_object_interaction="supportive presentation of a soft wipes pack with the front panel, seal, and opening edge kept readable",
            recommended_grip="pack side-hold, flat palm support, or pinch corner lift",
            air_gap_rule="keep fingers clear of the front label and opening edge so pack scale and seal cues stay visible",
            material_behavior="soft sealed wipes pack with light compression, flexible corners, and gentle crinkle response",
            surface_behavior="matte-soft pack surfaces with mild highlights on the seal, opening flap, and side seams",
            fragility_level="LOW",
            handling_notes="keep front label visible and avoid squeezing the soft pack unnaturally during presentation",
            camera_handling_notes="show soft pack scale, front label, and seal or opening edge if visible while keeping the pack stable and front-readable",
            unsafe_handling_rules=["avoid implying medical sterilization claims", "avoid crushed or over-squeezed pack presentation", "avoid hiding the opening flap or front label"],
        ),
    ),
    (
        ["instant sarung", "sarung syria", "sarung", "syria", "telekung", "khimar", "moscrepe"],
        _rule(
            physics_class="APPAREL_TEXTILE",
            product_scale="GARMENT",
            hand_object_interaction="controlled drape reveal, edge hold, and two-hand spread for soft modestwear fabric",
            recommended_grip="two-hand fabric spread, neckline hold, or edge hold for drape control",
            air_gap_rule="maintain enough separation for coverage, silhouette, and fabric fall to remain readable",
            material_behavior="soft modestwear textile with visible drape, fold memory, and light edge flutter",
            surface_behavior="matte crepe-like textile finish with natural folds and soft highlights",
            fragility_level="LOW",
            camera_handling_notes="present the fabric drape, coverage, and fall cleanly without overstretching or body-shape exaggeration",
            unsafe_handling_rules=["avoid exaggerated body-shape claims", "avoid unnatural fabric stretch", "avoid styling that breaks modestwear context"],
        ),
    ),
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


PHYSICS_FAMILY_RULES: dict[str, dict[str, Any]] = {
    "modestwear_textile": _rule(
        physics_class="MODESTWEAR_TEXTILE",
        product_scale="GARMENT",
        hand_object_interaction="two-hand fabric reveal, edge support, and controlled drape presentation for modestwear silhouettes",
        recommended_grip="two-hand fabric spread, edge pinch, or neckline hold with clean drape control",
        air_gap_rule="keep enough lift and separation for the hijab or garment silhouette to stay readable on camera",
        material_behavior="lightweight to medium-weight modestwear textile with soft fold memory, drape, and edge flutter",
        surface_behavior="matte or satin textile finish with visible seam, hem, and layering detail",
        fragility_level="LOW",
        handling_notes="Keep the textile front clean, coverage readable, and drape natural without over-stretching the fabric.",
        camera_handling_notes="Show coverage, fall, and edge lines clearly while avoiding styling that distorts modestwear fit.",
        unsafe_handling_rules=["avoid exaggerated body-shape styling", "avoid twisting the fabric into unnatural tension", "avoid cramped framing that hides silhouette cues"],
    ),
    "fashion_apparel_textile": _rule(
        physics_class="APPAREL_TEXTILE",
        product_scale="GARMENT",
        hand_object_interaction="supportive garment lift, fold, waistband or shoulder hold, and clear fabric spread for fit readability",
        recommended_grip="waistband hold, shoulder hold, hanger hold, or two-hand fabric spread",
        air_gap_rule="maintain visible separation around seams and silhouette edges so the cut and texture remain readable",
        material_behavior="woven or knit apparel textile with natural drape, fold recovery, and seam definition",
        surface_behavior="soft textile face with visible stitching, hems, and natural crease response",
        fragility_level="LOW",
        handling_notes="Present the apparel in a clean, front-readable pose that reveals fit, fabric weight, and important seams.",
        camera_handling_notes="Keep fabric stretched only enough to show construction and avoid deformation that changes perceived fit.",
        unsafe_handling_rules=["avoid over-stretching garments", "avoid body-shape exaggeration claims", "avoid cramped folds that hide cut details"],
    ),
    "beauty_bottle_or_tube": _rule(
        physics_class="BEAUTY_BOTTLE_OR_TUBE",
        product_scale="SMALL_OBJECT",
        hand_object_interaction="precise label-forward handling of a beauty bottle, tube, stick, or compact with controlled rotation",
        recommended_grip="light side pinch, cap-base hold, or palm-supported label-forward grip",
        air_gap_rule="keep fingers clear of labels, applicators, pumps, and active product surfaces",
        material_behavior="rigid or semi-flexible cosmetic container with cap resistance, squeeze response, or applicator control",
        surface_behavior="glossy or satin packaging with controlled highlights and readable branding surfaces",
        fragility_level="MEDIUM",
        handling_notes="Keep branding legible, cap alignment clean, and applicator or dispensing surfaces unobstructed.",
        camera_handling_notes="Rotate slowly, control reflections, and frame the container so benefit cues come from packaging rather than fake usage claims.",
        unsafe_handling_rules=["avoid messy product smears unless the format requires it", "avoid unsupported efficacy claims", "avoid obscuring the label with fingers"],
    ),
    "skincare_jar_or_tube": _rule(
        physics_class="SKINCARE_JAR_OR_TUBE",
        product_scale="SMALL_OBJECT",
        hand_object_interaction="careful jar, tube, sheet-mask, or balm presentation with front label lock and cap-or-seal emphasis",
        recommended_grip="base support, side pinch, or top-edge hold with the front face visible",
        air_gap_rule="maintain clear space around the label, seal, and dispensing edge so skincare format cues remain readable",
        material_behavior="tube, sachet, jar, or mask packaging with gentle squeeze response and stable lid or seal behavior",
        surface_behavior="clean cosmetic-grade packaging surfaces with satin or glossy reflections and visible seal edges",
        fragility_level="LOW",
        handling_notes="Keep the container, sachet, or mask sheet clean and upright so the skincare format and branding stay obvious.",
        camera_handling_notes="Favor clean beauty close-ups, keep the label and seal readable, and avoid spilling, crushing, or over-squeezing the product container.",
        unsafe_handling_rules=["avoid messy leakage", "avoid obscuring expiry or seal areas", "avoid unsupported before-after claims"],
    ),
    "household_packaged_goods": _rule(
        physics_class="HOUSEHOLD_PACKAGED_GOODS",
        product_scale="MEDIUM_OBJECT",
        hand_object_interaction="stable pack, bottle, pouch, or boxed-goods handling with front readability and practical utility emphasis",
        recommended_grip="side carry grip, bottom support, or front-readable two-hand hold depending on pack size",
        air_gap_rule="keep hands clear of the key label area and any opening, nozzle, or closure mechanism",
        material_behavior="flexible pouch, rigid bottle, or lightweight boxed packaging with realistic carry weight and closure resistance",
        surface_behavior="plastic, paper, or laminated household packaging with readable front panels and closure details",
        fragility_level="LOW",
        handling_notes="Present the household item like a real usable product: label visible, closure intact, and form stable.",
        camera_handling_notes="Show utility cues through clean orientation and grip clarity rather than dramatic motion or fake usage effects.",
        unsafe_handling_rules=["avoid leaking contents", "avoid upside-down handling that hides the label", "avoid unsupported safety claims"],
    ),
    "kitchen_tool": _rule(
        physics_class="KITCHEN_TOOL",
        product_scale="MEDIUM_OBJECT",
        hand_object_interaction="controlled utensil, bottle, pan, or tool handling that shows grip points and working surfaces clearly",
        recommended_grip="handle grip, rim support, or balanced two-hand support depending on tool weight",
        air_gap_rule="keep hands clear of blade, grate, rim, or mouth openings so the working surface remains visible",
        material_behavior="rigid kitchenware in steel, plastic, or coated surfaces with realistic heft and handle balance",
        surface_behavior="semi-gloss to polished surfaces with visible edges, handles, lids, or working teeth",
        fragility_level="LOW",
        handling_notes="Orient the kitchen item so functional surfaces, handles, and fill openings are obvious at a glance.",
        camera_handling_notes="Use stable tabletop or hand-held utility framing and avoid unsafe or misleading food-prep motions.",
        unsafe_handling_rules=["avoid implying food is included unless visible", "avoid unsafe blade handling", "avoid unstable tilts that hide function"],
    ),
    "toy_box_or_pack": _rule(
        physics_class="TOY_BOX_OR_PACK",
        product_scale="SMALL_TO_MEDIUM_OBJECT",
        hand_object_interaction="light playful handling of craft or toy packs with shape, color, and interaction points kept visible",
        recommended_grip="light side pinch, bottom support, or two-hand pack hold",
        air_gap_rule="maintain enough spacing for pack edges, toy silhouette, or craft bundle texture to stay readable",
        material_behavior="lightweight toy or craft packaging with flexible pack edges or small-part rigidity",
        surface_behavior="printed pack surfaces or tactile toy materials with visible color contrast and shape cues",
        fragility_level="LOW",
        handling_notes="Keep the toy or craft item readable and friendly without chaotic movement or compressed pack presentation.",
        camera_handling_notes="Favor cheerful, stable framing that shows the toy or craft contents cleanly and safely.",
        unsafe_handling_rules=["avoid implying unsafe child use", "avoid crushing the pack", "avoid motion blur that hides parts"],
    ),
    "food_pack_or_jar": _rule(
        physics_class="FOOD_PACK_OR_JAR",
        product_scale="SMALL_CONTAINER",
        hand_object_interaction="clean jar, pouch, sachet, or bottle handling with seal integrity and front readability maintained",
        recommended_grip="jar side hold, base support, or pack pinch with the front label visible",
        air_gap_rule="leave the label and seal area unobstructed so food-safe packaging cues remain readable",
        material_behavior="sealed food container or flexible food pack with realistic fill weight and closure response",
        surface_behavior="glossy labels, jar edges, or laminated packaging with appetizing but controlled reflections",
        fragility_level="LOW",
        handling_notes="Keep the package sealed-looking, clean, and food-safe, with the front panel easy to read.",
        camera_handling_notes="Use appetizing but tidy tabletop framing without spills unless the product format clearly calls for it.",
        unsafe_handling_rules=["avoid unsupported health claims", "avoid broken seals", "avoid messy spills without food styling context"],
    ),
    "supplement_bottle": _rule(
        physics_class="SUPPLEMENT_BOTTLE",
        product_scale="SMALL_OBJECT",
        hand_object_interaction="stable bottle presentation with dosage-format cues, cap integrity, and label lock",
        recommended_grip="side grip with thumb behind label or base-supported bottle hold",
        air_gap_rule="keep fingers away from the label copy and cap seam so the supplement format is obvious",
        material_behavior="rigid supplement bottle or canister with screw-cap resistance and audible closure expectation",
        surface_behavior="matte or satin bottle body with readable print and clean cap transitions",
        fragility_level="LOW",
        handling_notes="Hold the supplement upright and clean, emphasizing bottle format and label readability over exaggerated gestures.",
        camera_handling_notes="Avoid medical theatrics; frame the bottle like a trustworthy daily product with cap and label clearly visible.",
        unsafe_handling_rules=["avoid medical cure claims", "avoid loose pills unless explicitly shown", "avoid obscuring dosage-format cues"],
    ),
    "electronics_small_box": _rule(
        physics_class="ELECTRONICS_SMALL_DEVICE",
        product_scale="SMALL_TO_MEDIUM_OBJECT",
        hand_object_interaction="careful device handling with controls, ports, screens, or cable ends kept visible during turns",
        recommended_grip="balanced side grip, underside support, or connector-end hold depending on device form",
        air_gap_rule="maintain visibility around screens, ports, buttons, blades, or connectors so functional details remain readable",
        material_behavior="rigid electronic housing with weighted balance, hinge or button resistance, and cable or accessory articulation",
        surface_behavior="plastic, coated metal, or screen surfaces with clean edge highlights and visible control geometry",
        fragility_level="MEDIUM",
        handling_notes="Present the device as a real consumer object: keep controls readable, cable routing clean, and screens or ports unobstructed.",
        camera_handling_notes="Use measured product turns and stable grip transitions so ports, controls, and device function stay obvious without fake activation effects.",
        unsafe_handling_rules=["avoid unrealistic floating cables", "avoid hiding ports or controls", "avoid unsupported performance claims"],
    ),
    "stationery_pack": _rule(
        physics_class="STATIONERY_PACK",
        product_scale="SMALL_FLAT_OBJECT",
        hand_object_interaction="flat lay, page-turn, fan, stack, or board-front handling of paper and stationery goods",
        recommended_grip="edge pinch, corner support, or back support with the printed face unobstructed",
        air_gap_rule="preserve enough spacing for page edges, cover art, or printed surfaces to remain readable",
        material_behavior="paper, card, sticker, or notebook materials with light bend, page stack resistance, and crisp edge response",
        surface_behavior="matte or satin printed surfaces with visible cover, page, or label detail",
        fragility_level="LOW",
        handling_notes="Keep printed surfaces neat, square, and fully readable while avoiding bent corners or crushed page blocks.",
        camera_handling_notes="Favor top-down or front-readable framing so the stationery format and design details stay clear.",
        unsafe_handling_rules=["avoid torn corners", "avoid obscuring printed details", "avoid implying hidden contents that are not shown"],
    ),
    "home_textile_soft_good": _rule(
        physics_class="HOME_TEXTILE_SOFT_GOOD",
        product_scale="LARGE_SOFT_GOOD",
        hand_object_interaction="two-hand lift, spread, fold, drape, or fluff presentation of curtains, towels, blankets, or similar soft goods",
        recommended_grip="two-hand corner lift, hem hold, or broad palm support",
        air_gap_rule="maintain enough lift and separation for thickness, drape, and surface texture to remain visible",
        material_behavior="soft woven textile with fold memory, drape, compression, and recovery",
        surface_behavior="textile face with weave, pile, or quilting detail and natural crease response",
        fragility_level="LOW",
        handling_notes="Spread or fold the textile cleanly so size, softness, and edge finish are easy to read on camera.",
        camera_handling_notes="Show textile thickness and drape with stable motions instead of abrupt shaking or bunched folds.",
        unsafe_handling_rules=["avoid dragging on dirty surfaces", "avoid cramped bunching that hides texture", "avoid impossible floating folds"],
    ),
    "small_rigid_decor": _rule(
        physics_class="SMALL_RIGID_DECOR",
        product_scale="SMALL_OBJECT",
        hand_object_interaction="careful decor or accessory handling with front-facing display and stable edge support",
        recommended_grip="light side pinch, back support, or base hold depending on the display surface",
        air_gap_rule="keep display surfaces, edges, and decorative details unobstructed during turns",
        material_behavior="rigid decorative object in plastic, metal, resin, glass, or coated board with stable form",
        surface_behavior="printed, metallic, glossy, or matte decor surfaces with visible detail and edge highlights",
        fragility_level="MEDIUM",
        handling_notes="Keep the decorative face or silhouette unobstructed so the design reads immediately.",
        camera_handling_notes="Use stable hero framing and slow turns that keep the object front-readable and intact.",
        unsafe_handling_rules=["avoid chipped-edge presentation", "avoid hiding the decorative face", "avoid unstable spinning motions"],
    ),
    "medical_test_kit": _rule(
        physics_class="MEDICAL_TEST_KIT",
        product_scale="SMALL_OBJECT",
        hand_object_interaction="careful front-facing handling of a slim test kit or pen-style diagnostic object with packaging context retained",
        recommended_grip="mid-body pinch or base support with the test window and branding visible",
        air_gap_rule="keep fingers clear of the display window, cap, and instruction-facing surfaces",
        material_behavior="light rigid plastic device or kit component with cap-fit resistance and stable straight profile",
        surface_behavior="clean plastic body with readable test window or printed labeling",
        fragility_level="LOW",
        handling_notes="Present the kit cleanly and clinically without implying results or interpretation beyond what is visibly shown.",
        camera_handling_notes="Frame the device like a sealed or controlled-use product and keep the window, label, and cap visible.",
        unsafe_handling_rules=["avoid medical claims or diagnoses", "avoid showing bodily fluid interaction", "avoid obscuring the test window"],
    ),
    "footwear_pair": _rule(
        physics_class="FOOTWEAR_PAIR",
        product_scale="PAIR_OBJECT",
        hand_object_interaction="balanced pair or single-shoe presentation that shows sole, upper, and strap or opening clearly",
        recommended_grip="heel hold, strap hold, or under-sole support",
        air_gap_rule="keep enough separation to show profile, sole thickness, and upper shape",
        material_behavior="structured footwear with flexible upper, shaped sole, and realistic bend at the forefoot",
        surface_behavior="matte or semi-gloss upper with visible strap, stitch, and sole-edge detail",
        fragility_level="LOW",
        handling_notes="Show the shoe profile and opening clearly while keeping the pair aligned and wearable-looking.",
        camera_handling_notes="Use clean profile turns and avoid collapsing the upper or hiding the sole shape.",
        unsafe_handling_rules=["avoid impossible bending", "avoid flattening the upper unnaturally", "avoid hiding the outsole profile"],
    ),
    "fashion_accessory_small_object": _rule(
        physics_class="FASHION_ACCESSORY_SMALL_OBJECT",
        product_scale="SMALL_OBJECT",
        hand_object_interaction="precise small-accessory handling that keeps decorative details and attachment points visible",
        recommended_grip="light pinch at the edge or backing point with the decorative face visible",
        air_gap_rule="keep fingers clear of decorative stones, letters, or clasp details",
        material_behavior="small rigid accessory with clasp, pin, or decorative hardware resistance",
        surface_behavior="metallic, enamel, or embellished surfaces with crisp highlights and visible ornament detail",
        fragility_level="MEDIUM",
        handling_notes="Present the accessory front-first and keep clasps, pins, or decorative details readable.",
        camera_handling_notes="Use macro-friendly framing and slow controlled turns to avoid glitter glare or lost detail.",
        unsafe_handling_rules=["avoid obscuring clasps or pin backs", "avoid harsh reflection blowout", "avoid unstable fingertip wobble"],
    ),
}


def _title_or_taxonomy_contains(haystack: str, *keywords: str) -> bool:
    return any(normalize_mapping_text(keyword) in haystack for keyword in keywords)


def _resolve_physics_family(title: str, category: str, subcategory: str, type_name: str) -> str | None:
    if category == "muslim fashion":
        return "modestwear_textile"

    if category in {"womenswear and underwear", "menswear and underwear", "sports and outdoor"}:
        return "fashion_apparel_textile"

    if category == "shoes":
        return "footwear_pair"

    if category == "textiles and soft furnishings":
        return "home_textile_soft_good"

    if category == "beauty and personal care":
        if subcategory == "skincare":
            return "skincare_jar_or_tube"
        if subcategory in {
            "bath and body",
            "bath and body care",
            "feminine care",
            "haircare and styling",
            "hand foot and nail care",
            "makeup",
            "men s care",
            "nasal and oral care",
        }:
            return "beauty_bottle_or_tube"

    if category == "health":
        if subcategory == "supplements":
            return "supplement_bottle"
        return "medical_test_kit"

    if category in {"books magazines and audio", "computers and office equipment"}:
        return "stationery_pack"

    if category == "kitchenware":
        return "kitchen_tool"

    if category in {"electronics", "household appliances", "phones and electronics"}:
        return "electronics_small_box"

    if category == "automotive and motorcycle":
        if _title_or_taxonomy_contains(f"{subcategory} {type_name} {title}", "cleaner", "coating", "fluid", "spray"):
            return "household_packaged_goods"
        return "electronics_small_box"

    if category == "home improvement":
        if subcategory == "lights and lighting":
            return "electronics_small_box"
        if _title_or_taxonomy_contains(f"{subcategory} {type_name} {title}", "wallpaper", "sticker", "frame", "hook"):
            return "small_rigid_decor"
        return "household_packaged_goods"

    if category == "home supplies":
        if subcategory == "bathroom supplies" or type_name == "towels":
            return "home_textile_soft_good"
        if subcategory == "home decor":
            return "small_rigid_decor"
        if subcategory == "home organizers" and _title_or_taxonomy_contains(title, "hanger", "penyangkut"):
            return "fashion_accessory_small_object"
        return "household_packaged_goods"

    if category == "toys and hobbies":
        if _title_or_taxonomy_contains(f"{subcategory} {type_name} {title}", "yarn", "benang", "pipe cleaners", "craft"):
            return "toy_box_or_pack"
        return "toy_box_or_pack"

    if category == "fashion accessories":
        return "fashion_accessory_small_object"

    if category == "tools and hardware":
        if _title_or_taxonomy_contains(f"{subcategory} {type_name} {title}", "sticker", "wall", "hook", "adhesive"):
            return "small_rigid_decor"
        return "household_packaged_goods"

    if category == "food and beverage":
        return "food_pack_or_jar"

    return None


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

    family = _resolve_physics_family(
        title=title,
        category=normalize_mapping_text(category or (product or {}).get("category")),
        subcategory=normalize_mapping_text(subcategory or (product or {}).get("subcategory")),
        type_name=normalize_mapping_text(type_name or (product or {}).get("type")),
    )
    if family:
        return dict(PHYSICS_FAMILY_RULES[family])

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
        "handling_notes": "",
        "camera_handling_notes": "",
        "unsafe_handling_rules": [],
        "section_5_product_physics_prompt": "",
        "section_5_physics_hint": "",
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
    if not (product.get("section_4_hint") or "").strip():
        missing_fields.append("section_4_hint")
    if not (product.get("section_6_copy_hint") or "").strip():
        missing_fields.append("section_6_copy_hint")
    if not (product.get("section_9_overlay_hint") or "").strip():
        missing_fields.append("section_9_overlay_hint")

    status = "READY" if not missing_fields else ("NEEDS_REVIEW" if len(missing_fields) <= 2 else "MISSING_FIELDS")
    return {
        "prompt_readiness_status": status,
        "prompt_missing_fields": missing_fields,
        "physics_dna_status": "READY" if physics.get("physics_class") else "MISSING_FIELDS",
        "section_4_visual_action_prompt": f"Show {product.get('product_short_name') or 'the product'} in a clear commercial action that highlights {product.get('type') or 'its form'}.",
        "section_6_dialogue_prompt": product.get("copywriting_angle") or "",
        "section_9_overlay_prompt": f"Overlay: {product.get('product_short_name') or 'Product'} | {product.get('category') or 'Unmapped'}",
    }