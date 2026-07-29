"""Exact Product Truth mappings for catalog product-type convergence.

Source ``product.type`` plus its source category path outranks title keywords
and broad BOSMAX family inference.  A mapping may remain review-only until a
specific scene strategy exists; the absence of a scene strategy is deliberate
and must never be converted into generic P4 support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


P57_REVIEWER_ID = "owner-mission:P5.7"
P57_REVIEWER_NOTE = (
    "Product Truth source-type mapping reviewed under "
    "P5.7-CATALOG-COVERAGE-CONVERGENCE-20260729"
)


@dataclass(frozen=True, slots=True)
class CatalogProductTypeTruthMapping:
    cluster: str
    product_type_group: str
    display_name: str
    source_types: tuple[str, ...] = ()
    source_categories: tuple[str, ...] = ()
    source_subcategories: tuple[str, ...] = ()
    specific_scene_strategy_id: str | None = None


CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS = (
    # Existing, proven Product Truth types.
    CatalogProductTypeTruthMapping(
        "baby_care",
        "baby_diaper",
        "Baby Diaper",
        source_types=("Pants",),
        source_categories=("Baby Care",),
        source_subcategories=("Diaper",),
        specific_scene_strategy_id="BABY_DIAPER",
    ),
    CatalogProductTypeTruthMapping(
        "baby_care",
        "baby_diaper",
        "Baby Diaper",
        source_types=("Diapers",),
        specific_scene_strategy_id="BABY_DIAPER",
    ),
    CatalogProductTypeTruthMapping(
        "baby_care",
        "baby_wipes",
        "Baby Wipes",
        source_types=("Baby Wipes",),
        specific_scene_strategy_id="BABY_WIPES",
    ),
    CatalogProductTypeTruthMapping(
        "fragrance",
        "fragrance",
        "Fragrance",
        source_types=(
            "Body Mist",
            "Car Fragrance",
            "Perfume",
            "Unisex Perfume",
            "Women's Perfume",
        ),
        specific_scene_strategy_id="FRAGRANCE",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "lipstick_lip_tint",
        "Lipstick Lip Tint",
        source_types=("Lipstick & Lip Gloss",),
        specific_scene_strategy_id="LIP_COLOR",
    ),
    CatalogProductTypeTruthMapping(
        "household_cleaning",
        "household_cleaner",
        "Household Cleaner",
        source_types=("Household Cleaners",),
        specific_scene_strategy_id="HOUSEHOLD_CLEANER",
    ),
    CatalogProductTypeTruthMapping(
        "household_laundry",
        "detergent",
        "Detergent",
        source_types=("Laundry Detergent",),
        specific_scene_strategy_id="LAUNDRY_DETERGENT",
    ),
    CatalogProductTypeTruthMapping(
        "food_cooking",
        "rempah_seasoning",
        "Rempah Seasoning",
        source_types=("Herbs, Spices & Seasonings",),
        specific_scene_strategy_id="SPICE_SEASONING",
    ),
    CatalogProductTypeTruthMapping(
        "food_cooking",
        "sauce",
        "Sauce",
        source_types=("Cooking Sauces", "Sauce-Food"),
        specific_scene_strategy_id="PACKAGED_SAUCE_SAMBAL",
    ),
    CatalogProductTypeTruthMapping(
        "food_ready_to_eat",
        "instant_food",
        "Instant Food",
        source_types=(
            "Breakfast Cereal, Granola & Oatmeal",
            "Canned, Jarred & Packaged Foods",
            "Instant Hotpot",
            "Instant Noodles",
        ),
        specific_scene_strategy_id="PACKAGED_FOOD",
    ),
    CatalogProductTypeTruthMapping(
        "home_storage",
        "storage_organizer",
        "Storage Organizer",
        source_types=(
            "Food Container",
            "Hangers & Pegs",
            "Storage Boxes & Bins",
            "Storage Holders & Racks",
        ),
        specific_scene_strategy_id="HOUSEHOLD_STORAGE",
    ),
    CatalogProductTypeTruthMapping(
        "electronics_accessory",
        "electronics_accessory",
        "Electronics Accessory",
        source_types=(
            "Audio & Video Accessories",
            "Cables, Chargers & Adapters",
            "Phone Holders & Mounts",
        ),
        specific_scene_strategy_id="ELECTRONICS_ACCESSORY",
    ),
    CatalogProductTypeTruthMapping(
        "electronics_accessory",
        "electronics_wearable",
        "Electronics Wearable",
        source_types=("Smart Watches", "Smartwatch"),
        specific_scene_strategy_id="ELECTRONICS_SMALL_DEVICE",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "modestwear",
        "Modestwear",
        source_types=(
            "Instant Hijab",
            "Instant Sarung",
            "Mukena",
            "Robes",
            "Square Hijabs",
            "Underscarves",
        ),
        specific_scene_strategy_id="MODESTWEAR",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "sportswear",
        "Sportswear",
        source_types=(
            "Islamic Tracksuits",
            "Jersey-Athleisure",
            "Jerseys",
            "Kids' Sports Clothing",
            "Sports Leggings",
            "Sports Outerwear & Hoodies",
            "Sports Underwear",
        ),
        specific_scene_strategy_id="SPORTSWEAR",
    ),
    # P5.7 reviewed/activated exact types.
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "bottom_apparel",
        "Bottom Apparel",
        source_types=("Leggings", "Pants", "Shorts", "Trousers"),
        source_categories=("Fashion", "Menswear & Underwear", "Womenswear & Underwear"),
        specific_scene_strategy_id="BOTTOM_APPAREL",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "bottom_apparel",
        "Bottom Apparel",
        source_categories=("Fashion",),
        source_subcategories=("Bottoms",),
        specific_scene_strategy_id="BOTTOM_APPAREL",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "body_cleanser",
        "Body Cleanser",
        source_types=("Bath & Body Care", "Body Wash & Soap", "Soap"),
        specific_scene_strategy_id="BODY_CLEANSER",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_skincare",
        "facial_cleanser",
        "Facial Cleanser",
        source_types=("Facial Cleansers",),
        specific_scene_strategy_id="FACIAL_CLEANSER",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "complexion_makeup",
        "Complexion Makeup",
        source_types=("Concealer & Foundation",),
        specific_scene_strategy_id="COMPLEXION_MAKEUP",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "nail_color",
        "Nail Color",
        source_types=("Nail Art & Nail Polish",),
        specific_scene_strategy_id="NAIL_COLOR",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_skincare",
        "facial_serum",
        "Facial Serum",
        source_types=("Serums & Essences",),
        specific_scene_strategy_id="FACIAL_SERUM",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "mascara",
        "Mascara",
        source_types=("Mascara",),
        specific_scene_strategy_id="MASCARA",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "eyeliner",
        "Eyeliner",
        source_types=("Eyeliner & Lipliner",),
        specific_scene_strategy_id="EYELINER",
    ),
    CatalogProductTypeTruthMapping(
        "sensitive_wellness",
        "wellness_supplement",
        "Wellness Supplement",
        source_types=("Beauty Supplement", "Wellness Supplements"),
        specific_scene_strategy_id="WELLNESS_SUPPLEMENT",
    ),
    CatalogProductTypeTruthMapping(
        "sensitive_wellness",
        "male_wellness",
        "Male Wellness",
        source_types=("Male Health",),
        specific_scene_strategy_id="SENSITIVE_WELLNESS",
    ),
    CatalogProductTypeTruthMapping(
        "food_ready_to_eat",
        "packaged_snack",
        "Packaged Snack",
        source_types=(
            "Biscuits, Cookies & Wafers",
            "Candy",
            "Chocolate & Chocolate Snacks",
            "Crisps & Puffed Snacks",
            "Dried Snacks",
            "Popcorn",
        ),
        specific_scene_strategy_id="PACKAGED_SNACK",
    ),
    CatalogProductTypeTruthMapping(
        "pet_care",
        "pet_food",
        "Pet Food",
        source_types=("Cat Food", "Cat Treats"),
        specific_scene_strategy_id="PET_FOOD",
    ),
    CatalogProductTypeTruthMapping(
        "food_beverage",
        "packaged_beverage",
        "Packaged Beverage",
        source_types=(
            "Chocolate & Malted Drinks",
            "Juice & Smoothies",
            "Tea",
            "Water & Flavored Water",
        ),
        specific_scene_strategy_id="PACKAGED_BEVERAGE",
    ),
    CatalogProductTypeTruthMapping(
        "food_cooking",
        "pantry_ingredient",
        "Pantry Ingredient",
        source_types=(
            "Beans & Grains",
            "Jams, Dressings & Spreads",
            "Sugar & Sweeteners",
        ),
        specific_scene_strategy_id="PANTRY_INGREDIENT",
    ),
    CatalogProductTypeTruthMapping(
        "home_textiles",
        "bedding",
        "Bedding",
        source_types=(
            "Bedding Sets",
            "Duvets",
            "Pillow",
            "Pillows & Bed Wedges",
            "Sheets & Pillowcases",
        ),
        specific_scene_strategy_id="BEDDING",
    ),
    CatalogProductTypeTruthMapping(
        "home_textiles",
        "rug_mat",
        "Rug And Mat",
        source_types=("Bath Mats", "Carpets, Mats & Rugs", "Mat-Rug"),
        specific_scene_strategy_id="RUG_MAT",
    ),
    CatalogProductTypeTruthMapping(
        "books_media",
        "book",
        "Book",
        source_types=("Religion & Philosophy",),
        specific_scene_strategy_id="BOOK",
    ),
    CatalogProductTypeTruthMapping(
        "home_equipment",
        "home_fan",
        "Home Fan",
        source_types=("Fans",),
        specific_scene_strategy_id="HOME_FAN",
    ),
    CatalogProductTypeTruthMapping(
        "home_equipment",
        "vacuum_cleaner",
        "Vacuum Cleaner",
        source_types=("Vacuum Cleaners & Sweeping Robots",),
        specific_scene_strategy_id="VACUUM_CLEANER",
    ),
    CatalogProductTypeTruthMapping(
        "home_equipment",
        "vacuum_sealer",
        "Vacuum Sealer",
        source_types=("Vacuum Sealers",),
        specific_scene_strategy_id="VACUUM_SEALER",
    ),
    CatalogProductTypeTruthMapping(
        "home_equipment",
        "blender",
        "Blender",
        source_types=("Juicers & Blenders",),
        specific_scene_strategy_id="ELECTRONICS_SMALL_DEVICE",
    ),
    CatalogProductTypeTruthMapping(
        "home_equipment",
        "chopper",
        "Chopper",
        source_types=("Food Choppers",),
        specific_scene_strategy_id="ELECTRONICS_SMALL_DEVICE",
    ),
    # Mapped now, held REVIEW_REQUIRED/FALLBACK_ONLY until a specific scene and
    # deterministic P4 strategy are authored in a later P5.7 stage.
    CatalogProductTypeTruthMapping(
        "beauty_skincare",
        "face_mask",
        "Face Mask",
        source_types=("Face Masks",),
        specific_scene_strategy_id="FACE_MASK",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_skincare",
        "moisturizer",
        "Moisturizer",
        source_types=("Moisturizers & Mists",),
        specific_scene_strategy_id="MOISTURIZER",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_skincare",
        "sunscreen",
        "Sunscreen",
        source_types=("Facial Sunscreen & Sun Care",),
        specific_scene_strategy_id="SUNSCREEN",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_skincare",
        "eye_treatment",
        "Eye Treatment",
        source_types=("Eye Treatments",),
        specific_scene_strategy_id="EYE_TREATMENT",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "makeup_setting_spray",
        "Makeup Setting Spray",
        source_types=("Makeup Fixing Spray",),
        specific_scene_strategy_id="MAKEUP_SETTING_SPRAY",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "eyebrow_makeup",
        "Eyebrow Makeup",
        source_types=("Eyebrow Pencils/Powder/Paste",),
        specific_scene_strategy_id="EYEBROW_MAKEUP",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "eyeshadow",
        "Eyeshadow",
        source_types=("Eyeshadow",),
        specific_scene_strategy_id="EYESHADOW",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "false_eyelashes",
        "False Eyelashes",
        source_types=("False Eyelashes & Adhesives",),
        specific_scene_strategy_id="FALSE_EYELASHES",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "face_primer",
        "Face Primer",
        source_types=("Makeup Base and Primers",),
        specific_scene_strategy_id="FACE_PRIMER",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "makeup_set",
        "Makeup Set",
        source_types=("Makeup Sets",),
        specific_scene_strategy_id="MAKEUP_SET",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "face_powder",
        "Face Powder",
        source_types=("Powder",),
        specific_scene_strategy_id="FACE_POWDER",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "body_oil",
        "Body Oil",
        source_types=("Body & Massage Oil",),
        specific_scene_strategy_id="BODY_OIL",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "body_exfoliant",
        "Body Exfoliant",
        source_types=("Body Scrubs & Peels",),
        specific_scene_strategy_id="BODY_EXFOLIANT",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "deodorant",
        "Deodorant",
        source_types=("Deodorants & Antiperspirants",),
        specific_scene_strategy_id="DEODORANT",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "hair_wash",
        "Hair Wash",
        source_types=("Shampoo & Conditioner",),
        specific_scene_strategy_id="HAIR_WASH",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "hair_color",
        "Hair Color",
        source_types=("Hair Dye",),
        specific_scene_strategy_id="HAIR_COLOR",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "hair_treatment",
        "Hair Treatment",
        source_types=("Hair Treatments/Scalp Treatments",),
        specific_scene_strategy_id="HAIR_TREATMENT",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "makeup_remover",
        "Makeup Remover",
        source_types=("Makeup Remover",),
        specific_scene_strategy_id="MAKEUP_REMOVER",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "lip_treatment",
        "Lip Treatment",
        source_types=("Lip Treatments",),
        specific_scene_strategy_id="LIP_TREATMENT",
    ),
    CatalogProductTypeTruthMapping(
        "beauty_personal_care",
        "oral_care",
        "Oral Care",
        source_types=("Teeth Whitening", "Toothpastes"),
        specific_scene_strategy_id="ORAL_CARE",
    ),
    CatalogProductTypeTruthMapping(
        "sensitive_wellness",
        "feminine_hygiene",
        "Feminine Hygiene",
        source_types=("Feminine Hygiene", "Sanitary Towels"),
        specific_scene_strategy_id="FEMININE_HYGIENE",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "top_apparel",
        "Top Apparel",
        source_types=(
            "Blouses & Shirts",
            "Shirts & Blouses",
            "Turtlenecks & Inners",
            "Vest, Tank & Tube Tops",
        ),
        specific_scene_strategy_id="TOP_APPAREL",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "undergarment",
        "Undergarment",
        source_types=("Bras", "Socks", "Underwear"),
        specific_scene_strategy_id="UNDERGARMENT",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "sleepwear",
        "Sleepwear",
        source_types=("Nightdresses", "Pajamas"),
        specific_scene_strategy_id="SLEEPWEAR",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "dress",
        "Dress",
        source_types=("Casual Dresses",),
        specific_scene_strategy_id="DRESS",
    ),
    CatalogProductTypeTruthMapping(
        "fashion_footwear",
        "footwear",
        "Footwear",
        source_types=("Sandals & Flip Flops",),
        specific_scene_strategy_id="FOOTWEAR",
    ),
    CatalogProductTypeTruthMapping(
        "food_ready_to_eat",
        "frozen_food",
        "Frozen Food",
        source_types=("Frozen Food",),
        specific_scene_strategy_id="FROZEN_FOOD",
    ),
    CatalogProductTypeTruthMapping(
        "home_textiles",
        "curtain",
        "Curtain",
        source_types=("Curtains",),
        specific_scene_strategy_id="CURTAIN",
    ),
    CatalogProductTypeTruthMapping(
        "home_improvement",
        "wall_covering",
        "Wall Covering",
        source_types=("Wallpaper & Wall Trim",),
        specific_scene_strategy_id="WALL_COVERING",
    ),
    CatalogProductTypeTruthMapping(
        "craft_hobby",
        "knitting_crochet",
        "Knitting And Crochet",
        source_types=("Knitting & Crochet",),
        specific_scene_strategy_id="KNITTING_CROCHET",
    ),
)


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _matches(value: str, candidates: tuple[str, ...]) -> bool:
    return not candidates or value in {_normalize(candidate) for candidate in candidates}


def resolve_catalog_product_type_truth(
    product: Mapping[str, object],
) -> CatalogProductTypeTruthMapping | None:
    """Resolve an exact source-authority mapping without title inference."""

    source_type = _normalize(product.get("type"))
    source_category = _normalize(product.get("category"))
    source_subcategory = _normalize(product.get("subcategory"))
    for mapping in CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS:
        if mapping.source_types and not source_type:
            continue
        if not _matches(source_type, mapping.source_types):
            continue
        if not _matches(source_category, mapping.source_categories):
            continue
        if not _matches(source_subcategory, mapping.source_subcategories):
            continue
        return mapping
    return None


def iter_catalog_product_type_truth_registry_entries() -> tuple[
    CatalogProductTypeTruthMapping, ...
]:
    """Return one deterministic registry row per exact product-type pair."""

    by_pair: dict[tuple[str, str], CatalogProductTypeTruthMapping] = {}
    for mapping in CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS:
        pair = (mapping.cluster, mapping.product_type_group)
        existing = by_pair.get(pair)
        if existing is None:
            by_pair[pair] = mapping
            continue
        if (
            existing.specific_scene_strategy_id
            != mapping.specific_scene_strategy_id
        ):
            raise ValueError(f"CONFLICTING_PRODUCT_TRUTH_MAPPING:{pair}")
    return tuple(by_pair.values())
