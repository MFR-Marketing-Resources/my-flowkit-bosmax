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
P58_REVIEWER_ID = "owner-mission:P5.8"
P58_REVIEWER_NOTE = (
    "Final catalog authority reviewed under "
    "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
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
    auto_classification_enabled: bool = True
    include_in_registry: bool = True
    reviewer_id: str = P57_REVIEWER_ID
    reviewer_note: str = P57_REVIEWER_NOTE


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
    # P5.8 source-taxonomy closure. These mappings are exact reusable source
    # signatures, not title-derived aliases.
    CatalogProductTypeTruthMapping(
        "automotive_care",
        "car_surface_coating",
        "Car Surface Coating",
        source_types=("Paint Care",),
        specific_scene_strategy_id="CAR_CARE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "baby_care",
        "baby_feeding_accessory",
        "Baby Feeding Accessory",
        source_types=("Baby Bottles & Accessories",),
        specific_scene_strategy_id="BABY_FEEDING",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "baby_care",
        "baby_skincare",
        "Baby Skincare",
        source_types=("Baby Skincare",),
        specific_scene_strategy_id="BABY_SKINCARE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_textiles",
        "bath_linen",
        "Bath Linen",
        source_types=("Towels", "Towels & Shower Caps"),
        specific_scene_strategy_id="BATH_LINEN",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "stationery",
        "sticky_note",
        "Sticky Note",
        source_types=("Labels, Index Dividers & Stamps",),
        specific_scene_strategy_id="STATIONERY",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "stationery",
        "gift_stationery",
        "Gift Stationery",
        source_types=("School & Educational Supplies",),
        specific_scene_strategy_id="STATIONERY",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "stationery",
        "money_packet",
        "Money Packet",
        source_types=("Money Packet",),
        specific_scene_strategy_id="STATIONERY",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "fashion_accessory",
        "brooch",
        "Brooch",
        source_types=("Collar Clips & Brooches",),
        specific_scene_strategy_id="FASHION_ACCESSORY",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "health_device",
        "pregnancy_test",
        "Pregnancy Test",
        source_types=("Family Planning Tests",),
        specific_scene_strategy_id="HEALTH_TEST_DEVICE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "health_device",
        "health_monitor",
        "Health Monitor",
        source_types=("Health Monitors & Tests",),
        specific_scene_strategy_id="HEALTH_TEST_DEVICE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_lighting",
        "outdoor_light",
        "Outdoor Light",
        source_types=("Outdoor Lighting",),
        specific_scene_strategy_id="OUTDOOR_LIGHTING",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "garden_care",
        "plant_care",
        "Plant Care",
        source_types=("Plant Care & Support",),
        specific_scene_strategy_id="PLANT_CARE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_electrical",
        "power_saver_device",
        "Power Saver Device",
        source_types=("Power Savers",),
        specific_scene_strategy_id="ELECTRICAL_DEVICE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "household_cleaning",
        "cleaning_cloth",
        "Cleaning Cloth",
        source_types=("Cleaning Cloths",),
        specific_scene_strategy_id="CLEANING_TOOL",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "kitchen_storage",
        "food_cover",
        "Food Cover",
        source_types=("Dust Covers",),
        source_subcategories=("Home Care Supplies",),
        specific_scene_strategy_id="FOOD_COVER",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_decor",
        "photo_frame",
        "Photo Frame",
        source_types=("Photo Frames",),
        specific_scene_strategy_id="HOME_DECOR",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "kitchen_cookware",
        "pan_wok",
        "Pan And Wok",
        source_types=("Pans & Woks",),
        specific_scene_strategy_id="COOKWARE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "kitchen_drinkware",
        "insulated_bottle",
        "Insulated Bottle",
        source_types=("Water Bottles",),
        specific_scene_strategy_id="DRINKWARE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_lighting",
        "usb_light",
        "USB Light",
        source_types=("USB & Mobile Lights",),
        specific_scene_strategy_id="SMALL_LIGHT",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "beauty_makeup",
        "blush",
        "Blush",
        source_types=("Blush",),
        specific_scene_strategy_id="BLUSH",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_decor",
        "decorative_magnet",
        "Decorative Magnet",
        source_types=("Refrigerator Magnets",),
        specific_scene_strategy_id="HOME_DECOR",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "household_cleaning",
        "trash_bag",
        "Trash Bag",
        source_types=("Trash Bags",),
        specific_scene_strategy_id="CLEANING_TOOL",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "home_decor",
        "candle",
        "Candle",
        source_types=("Candles",),
        specific_scene_strategy_id="HOME_DECOR",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "household_pest_control",
        "pest_control",
        "Pest Control",
        source_types=("Pest & Weed Control",),
        specific_scene_strategy_id="PEST_CONTROL",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "automotive_care",
        "car_care_fluid",
        "Car Care Fluid",
        source_types=("Cleaning & Care Fluids",),
        specific_scene_strategy_id="CAR_CARE",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "kitchen_tool",
        "kitchen_tool",
        "Kitchen Tool",
        source_types=("Specialty Kitchen Utensils",),
        specific_scene_strategy_id="KITCHEN_TOOL",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "stationery",
        "notebook",
        "Notebook",
        source_types=("Notebooks & Paper",),
        specific_scene_strategy_id="STATIONERY",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
    CatalogProductTypeTruthMapping(
        "fashion_apparel",
        "apparel_set",
        "Apparel Set",
        source_types=("Sets",),
        source_categories=("Womenswear & Underwear",),
        source_subcategories=("Women's Suits & Overalls",),
        specific_scene_strategy_id="APPAREL",
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    ),
)


# Mission-07G reviewed decisions. Kept distinct from the P5.8 reviewer so this round's
# rulings are not misattributed to that earlier review.
P07G_REVIEWER_ID = "owner-mission:07G"
P07G_REVIEWER_NOTE = (
    "Archived catalogue closure reviewed under "
    "BOSMAX-ALL-659-CATALOGUE-CLOSURE-07G; source taxonomy triple did not describe the "
    "product, so an exact product-ID-bound decision was recorded instead"
)


def _p07g_mapping(
    cluster: str,
    product_type_group: str,
    display_name: str,
    scene_strategy_id: str,
) -> CatalogProductTypeTruthMapping:
    return CatalogProductTypeTruthMapping(
        cluster=cluster,
        product_type_group=product_type_group,
        display_name=display_name,
        specific_scene_strategy_id=scene_strategy_id,
        auto_classification_enabled=False,
        include_in_registry=True,
        reviewer_id=P07G_REVIEWER_ID,
        reviewer_note=P07G_REVIEWER_NOTE,
    )


def _p58_mapping(
    cluster: str,
    product_type_group: str,
    display_name: str,
    scene_strategy_id: str,
    *,
    include_in_registry: bool = True,
) -> CatalogProductTypeTruthMapping:
    return CatalogProductTypeTruthMapping(
        cluster=cluster,
        product_type_group=product_type_group,
        display_name=display_name,
        specific_scene_strategy_id=scene_strategy_id,
        auto_classification_enabled=False,
        include_in_registry=include_in_registry,
        reviewer_id=P58_REVIEWER_ID,
        reviewer_note=P58_REVIEWER_NOTE,
    )


# Product-ID authority is used only where an APPROVED Product Truth snapshot,
# or an exact duplicate source signature, proves the product type but the source
# category path is too broad or contradictory. It is never a runtime title rule.
P58_PRODUCT_TRUTH_OVERRIDES = {
    # ── Mission-07G: five ARCHIVED products left on the generic fallback ──────────
    # Each carries a source triple that does not describe the product, so a reusable
    # triple rule would mis-map its neighbours. Bound per product ID instead.
    # "Stiker Dinding PVC" filed under Tools & Hardware / Fasteners & Hooks — it is a
    # self-adhesive wall covering.
    "3bedd53f-4910-4c5b-945f-4aa7e56d18b4": _p07g_mapping(
        "home_improvement", "wall_covering", "Wall Covering", "WALL_COVERING"
    ),
    # "Chenille Stems Pipe Cleaners" filed under Slime & Squishy Toys — craft material.
    "9c1a1843-6d1d-48e0-97df-a4b493e12d56": _p07g_mapping(
        "craft_hobby", "craft_material", "Craft Material", "CRAFT_MATERIAL"
    ),
    # "Non-Stick Korean BBQ Grill Pan" filed under Household Appliances / Electric Grills
    # — it is stovetop cookware, not an appliance.
    "4e0d386d-af76-49ef-b670-1679056e46c8": _p07g_mapping(
        "kitchen_cookware", "grill_pan", "Grill Pan", "COOKWARE"
    ),
    # "SAMPUL DUIT RAYA" — festive money packets.
    "7a88c55d-82a6-4045-88b2-f635f772cd05": _p07g_mapping(
        "stationery", "money_packet", "Money Packet", "STATIONERY"
    ),
    # "Pelapik Sangkar Pet Cage Floor Mat Plastic" filed under Dog & Cat Furniture /
    # Beds, Sofas & Mats. Owner ruling: this is a HARD-PLASTIC CAGE LINER, not bedding,
    # not litter and not food. New minimum authority registered for it.
    "0d58bd3c-b1f9-49d0-a83b-0165fc821bfa": _p07g_mapping(
        "pet_care", "pet_cage_accessory", "Pet Cage Accessory", "PET_CAGE_ACCESSORY"
    ),
    # ── Mission-07G round 3: two products stuck on the beauty generic-fallback pair ──
    # Both carry category "Beauty" with NO subcategory/type, so they fell to
    # beauty_personal_care_other -> GENERIC_FALLBACK -> PARTIAL coverage. Their titles
    # name the product class unambiguously, and both target pairs already exist
    # ACTIVE + COVERED in the registry, so no new authority is created here.
    # "INAIYA EASY HERBAL HAIR COLOUR 400ml | Tutup Uban Cepat" -> hair colour.
    "canonical-inaiya-hair-colour": _p07g_mapping(
        "beauty_personal_care", "hair_color", "Hair Color", "HAIR_COLOR"
    ),
    # "BeFocusPro+ Bantu Tidur Lena, Lebih Bertenaga & Kekal Fokus" -> an ingestible
    # sleep/focus supplement, which belongs to the sensitive_wellness claim regime rather
    # than generic beauty; WELLNESS_SUPPLEMENT keeps its stricter claim handling.
    "cc69a4ae-4ab5-4c7c-93e1-87eb796eeed1": _p07g_mapping(
        "sensitive_wellness", "wellness_supplement", "Wellness Supplement",
        "WELLNESS_SUPPLEMENT"
    ),
    # "6pcs Combo Herbal Cream BTFL Organic Yellow Cream". Title states a form but no
    # function, and both truth fields are empty, so it also sat on the beauty fallback.
    # The packaging resolves it: 百肤灵 草本乳膏 / BAIFULING CAOBENRUGAO, a 15g herbal
    # cream marked 外 (external use) from a pharmaceutical manufacturer. That is a
    # traditional herbal preparation by its own label, and SENSITIVE_WELLNESS is the
    # claim-suppressing scene grammar such a product must run under. The canonical pair
    # is clustered under sensitive_wellness, not beauty_personal_care, so no new registry
    # authority is created. Binding it does NOT release it: it stays REVIEW_REQUIRED with
    # no approved Product Truth.
    "8e75f1a8-ba43-444e-8b40-c71d140c76c5": _p07g_mapping(
        "sensitive_wellness", "traditional_herbal_preparation",
        "Traditional Herbal Preparation", "SENSITIVE_WELLNESS"
    ),
    "b4b0f581-f1aa-4677-beaa-54268199c377": _p58_mapping(
        "home_textiles", "bedding", "Bedding", "BEDDING"
    ),
    "753d305a-4133-40db-aa2d-56791f7c1d08": _p58_mapping(
        "home_textiles", "curtain", "Curtain", "CURTAIN"
    ),
    "d3830470-9019-490b-8362-87245b24b917": _p58_mapping(
        "home_textiles", "bath_linen", "Bath Linen", "BATH_LINEN"
    ),
    "013b7710-a55e-4053-9224-e1149f052f57": _p58_mapping(
        "home_improvement", "wall_covering", "Wall Covering", "WALL_COVERING"
    ),
    "8014da71-6b87-4476-9eb2-a91baf7fc0dd": _p58_mapping(
        "outdoor_equipment", "headlamp", "Headlamp", "OUTDOOR_LIGHTING"
    ),
    "733aa9ad-1ade-4fb3-a9f2-e4d70a841127": _p58_mapping(
        "outdoor_equipment", "fishing_reel", "Fishing Reel", "FISHING_GEAR"
    ),
    "ec58c4af-78a8-49ab-9a3f-7ab3bcdf76c4": _p58_mapping(
        "fitness_equipment",
        "pull_up_bar",
        "Pull Up Bar",
        "FITNESS_EQUIPMENT",
    ),
    "aae1b6f9-6d8f-43e3-9723-0d517ae8daec": _p58_mapping(
        "automotive_care", "car_surface_coating", "Car Surface Coating", "CAR_CARE"
    ),
    "d7df7ab0-09fe-42b5-9d5c-3211988a75a3": _p58_mapping(
        "automotive_accessory",
        "phone_mount",
        "Automotive Phone Mount",
        "AUTOMOTIVE_ACCESSORY",
    ),
    "21dcae04-86de-4af7-9698-eb2a3331614b": _p58_mapping(
        "consumer_audio", "wireless_earbuds", "Wireless Earbuds", "AUDIO_DEVICE"
    ),
    "6388605e-9bb3-43e2-beef-c07f89500a50": _p58_mapping(
        "consumer_audio", "radio", "Radio", "AUDIO_DEVICE"
    ),
    "1d970a08-8477-44c2-b514-35b05011e9c7": _p58_mapping(
        "baby_care",
        "baby_feeding_accessory",
        "Baby Feeding Accessory",
        "BABY_FEEDING",
    ),
    "6a6efac9-63a0-4cb1-a7ec-34cc78030ba7": _p58_mapping(
        "craft_hobby", "sewing_tool", "Sewing Tool", "SEWING_TOOL"
    ),
    "1925cb8e-7fed-4bdf-9e1c-e738abe19194": _p58_mapping(
        "kitchen_cookware", "grill_pan", "Grill Pan", "COOKWARE"
    ),
    "303f796d-5935-4f18-90f2-47f5e8037f6f": _p58_mapping(
        "pet_care", "cat_litter", "Cat Litter", "PET_LITTER"
    ),
    "038434f0-97ea-4d8d-afcf-52db4d85c434": _p58_mapping(
        "home_improvement", "wall_covering", "Wall Covering", "WALL_COVERING"
    ),
    "f93df31c-ac2c-4d76-8342-27aef23ca549": _p58_mapping(
        "craft_hobby", "epoxy_resin", "Epoxy Resin", "CRAFT_MATERIAL"
    ),
    "efcc1f31-c91b-46fb-acc6-d736a5271884": _p58_mapping(
        "beauty_personal_care",
        "hair_treatment",
        "Hair Treatment",
        "HAIR_TREATMENT",
    ),
    "666ca472-5045-4781-a2a4-c39292a3a617": _p58_mapping(
        "beauty_personal_care", "oral_care", "Oral Care", "ORAL_CARE"
    ),
    "35f19456-907c-414b-a631-f2d742facb8c": _p58_mapping(
        "beauty_personal_care",
        "personal_care_device",
        "Personal Care Device",
        "PERSONAL_CARE_DEVICE",
    ),
    "1512b029-ba11-407d-bc87-d2f7990b0315": _p58_mapping(
        "beauty_makeup",
        "complexion_makeup",
        "Complexion Makeup",
        "COMPLEXION_MAKEUP",
    ),
    "f722256e-ba18-47c9-a2ae-dcb007656775": _p58_mapping(
        "beauty_personal_care",
        "body_moisturizer",
        "Body Moisturizer",
        "BODY_MOISTURIZER",
    ),
    "3c34f3a1-ba39-4eb5-903d-815b96bf84e8": _p58_mapping(
        "sensitive_wellness",
        "traditional_herbal_preparation",
        "Traditional Herbal Preparation",
        "SENSITIVE_WELLNESS",
    ),
    "f67305f1-3786-4727-96c4-7e972cf50129": _p58_mapping(
        "traditional_wellness",
        "traditional_herbal_oil",
        "Traditional Herbal Oil",
        "TRADITIONAL_HERBAL_OIL",
        include_in_registry=False,
    ),
    "85ddc17a-ba47-4e03-a0a6-bc1e62f46436": _p58_mapping(
        "sensitive_wellness",
        "feminine_hygiene",
        "Feminine Hygiene",
        "FEMININE_HYGIENE",
    ),
    "b6d3b5b7-b61b-4537-b148-5f00b968e567": _p58_mapping(
        "beauty_personal_care",
        "personal_care_device",
        "Personal Care Device",
        "PERSONAL_CARE_DEVICE",
    ),
    "20f2352c-0f62-41c9-b1d9-8ee9c77d887f": _p58_mapping(
        "beauty_skincare", "moisturizer", "Moisturizer", "MOISTURIZER"
    ),
    "1ed2a06c-d579-4ebd-b227-d414cac6a356": _p58_mapping(
        "beauty_personal_care",
        "bath_salt",
        "Bath Salt",
        "BODY_BATH",
    ),
    "ddee46a2-367d-4fb5-897e-76730804f5a6": _p58_mapping(
        "beauty_skincare", "moisturizer", "Moisturizer", "MOISTURIZER"
    ),
    "61d52713-af50-4195-8b04-9c2b266ed3ea": _p58_mapping(
        "beauty_skincare", "sunscreen", "Sunscreen", "SUNSCREEN"
    ),
    "69f37eee-aff0-4084-b8b6-3f64ba87271b": _p58_mapping(
        "beauty_personal_care",
        "hair_treatment",
        "Hair Treatment",
        "HAIR_TREATMENT",
    ),
    "25c6f610-8360-4b11-9a78-1ed6f16b928d": _p58_mapping(
        "beauty_makeup",
        "makeup_setting_spray",
        "Makeup Setting Spray",
        "MAKEUP_SETTING_SPRAY",
    ),
    "3e7e7411-9b50-4005-acf6-d99d85e4d7e1": _p58_mapping(
        "beauty_makeup", "nail_color", "Nail Color", "NAIL_COLOR"
    ),
    "54017efd-5d1c-40b5-9875-ec1bdde88536": _p58_mapping(
        "beauty_makeup", "blush", "Blush", "BLUSH"
    ),
    "626a87b3-3cc7-4b61-8859-9f976ec9d15c": _p58_mapping(
        "beauty_makeup",
        "makeup_setting_spray",
        "Makeup Setting Spray",
        "MAKEUP_SETTING_SPRAY",
    ),
    "b60fb472-0a9a-4717-9751-6bf6d6e92344": _p58_mapping(
        "fashion_apparel", "sleepwear", "Sleepwear", "SLEEPWEAR"
    ),
    "7e4ea3ee-a37d-4ddd-b460-a6938cbd89e9": _p58_mapping(
        "fashion_apparel",
        "bottom_apparel",
        "Bottom Apparel",
        "BOTTOM_APPAREL",
    ),
    "4bab2b57-da68-482c-9f31-3d700ac0ac6b": _p58_mapping(
        "household_cleaning",
        "baby_bottle_cleanser",
        "Baby Bottle Cleanser",
        "HOUSEHOLD_CLEANER",
    ),
    "a54125d1-385c-4a78-92b5-273bc9aa1cf1": _p58_mapping(
        "fashion_footwear", "footwear", "Footwear", "FOOTWEAR"
    ),
    "b0919477-44ed-4518-9cb1-241ad26a4f00": _p58_mapping(
        "fashion_apparel", "top_apparel", "Top Apparel", "TOP_APPAREL"
    ),
    "129e569c-73a1-494c-bcf1-4ec0b90b1fbf": _p58_mapping(
        "household_cleaning",
        "cleaning_tool",
        "Cleaning Tool",
        "CLEANING_TOOL",
    ),
    "447debb4-7ed1-4536-aa7b-42719a8b378c": _p58_mapping(
        "home_storage",
        "storage_organizer",
        "Storage Organizer",
        "HOUSEHOLD_STORAGE",
    ),
    "1a5f4257-6711-42e4-8dcf-d61345fda1bd": _p58_mapping(
        "kitchen_drinkware",
        "insulated_bottle",
        "Insulated Bottle",
        "DRINKWARE",
    ),
    "ee5f12c2-d249-487a-b3f6-694d26a82356": _p58_mapping(
        "household_cleaning",
        "pressure_washer",
        "Pressure Washer",
        "CLEANING_EQUIPMENT",
    ),
    "0ddfd65c-6ffc-43fe-aa3f-8fff0a13a886": _p58_mapping(
        "garden_care", "plant_support", "Plant Support", "PLANT_CARE"
    ),
    "96616701-0020-4430-97f0-1d4001c40ae7": _p58_mapping(
        "household_cleaning", "trash_bag", "Trash Bag", "CLEANING_TOOL"
    ),
    "aaa1f472-b2d4-4fe3-a095-a8ccf0313360": _p58_mapping(
        "household_cleaning",
        "cleaning_cloth",
        "Cleaning Cloth",
        "CLEANING_TOOL",
    ),
    "bfc4c9c0-64b1-4104-82ad-8c0409ef8e93": _p58_mapping(
        "kitchen_cookware", "pan_wok", "Pan And Wok", "COOKWARE"
    ),
    "0dd690d7-e3d5-4155-a354-9a8c1476b9c9": _p58_mapping(
        "craft_hobby", "craft_material", "Craft Material", "CRAFT_MATERIAL"
    ),
    "ae47b55b-58d4-441e-97d3-0d6c785bb530": _p58_mapping(
        "household_pest_control",
        "pest_control",
        "Pest Control",
        "PEST_CONTROL",
    ),
    "6869a834-6fda-442a-8d51-394fccca3267": _p58_mapping(
        "stationery", "gift_bag", "Gift Bag", "STATIONERY"
    ),
    "40655de2-037e-48a0-8708-160831d120b4": _p58_mapping(
        "household_cleaning", "trash_bag", "Trash Bag", "CLEANING_TOOL"
    ),
    "2270741c-17ff-4915-86b3-aedde625452d": _p58_mapping(
        "fashion_footwear", "footwear", "Footwear", "FOOTWEAR"
    ),
    "e6f07364-c8e0-4839-b99a-7195578163ac": _p58_mapping(
        "fragrance", "fragrance", "Fragrance", "FRAGRANCE"
    ),
    "fdb9d59b-c971-4f6e-b81c-5a6731e32093": _p58_mapping(
        "fashion_apparel", "modestwear", "Modestwear", "MODESTWEAR"
    ),
    "9dbd8102-700c-4b84-bc1d-9d7d6e616918": _p58_mapping(
        "beauty_personal_care", "oral_care", "Oral Care", "ORAL_CARE"
    ),
    "e3e3819f-c312-4e73-9db8-477471860616": _p58_mapping(
        "pet_care", "pet_food", "Pet Food", "PET_FOOD"
    ),
    "5fcb8133-d048-4b2d-8493-08aba78ab9e2": _p58_mapping(
        "baby_care",
        "baby_feeding_accessory",
        "Baby Feeding Accessory",
        "BABY_FEEDING",
    ),
    "3be06f47-a156-4d5f-8d8c-91c786e89012": _p58_mapping(
        "sensitive_wellness",
        "wellness_supplement",
        "Wellness Supplement",
        "WELLNESS_SUPPLEMENT",
    ),
    "e9f06816-46b1-421d-8921-3ea183ed4760": _p58_mapping(
        "sensitive_wellness",
        "wellness_supplement",
        "Wellness Supplement",
        "WELLNESS_SUPPLEMENT",
    ),
    "4d491c01-2c5a-40c0-869e-54c50050d95d": _p58_mapping(
        "beauty_personal_care",
        "body_moisturizer",
        "Body Moisturizer",
        "BODY_MOISTURIZER",
    ),
    "2ccd3036-61d8-4e01-a35b-e9569dace960": _p58_mapping(
        "beauty_personal_care",
        "lip_treatment",
        "Lip Treatment",
        "LIP_TREATMENT",
    ),
    "b2ac8af7-80c2-4082-a222-6a47b92272c2": _p58_mapping(
        "baby_care",
        "baby_feeding_accessory",
        "Baby Feeding Accessory",
        "BABY_FEEDING",
    ),
    "867bd162-ef79-46ef-a7aa-97fb2387c058": _p58_mapping(
        "books_media", "book", "Book", "BOOK"
    ),
    "9c2af744-87d2-4cb0-b60a-e81dbbb761dd": _p58_mapping(
        "fashion_apparel", "apparel_set", "Apparel Set", "APPAREL"
    ),
    "baf8e9ea-fa91-4257-a980-413384ac5509": _p58_mapping(
        "household_cleaning",
        "air_duster",
        "Air Duster",
        "CLEANING_EQUIPMENT",
    ),
    "931829bd-0e0d-40db-9dcf-495a4dcc8329": _p58_mapping(
        "kitchen_drinkware",
        "insulated_bottle",
        "Insulated Bottle",
        "DRINKWARE",
    ),
}


P58_INSUFFICIENT_PRODUCT_TRUTH_REASONS = {
    "8e75f1a8-ba43-444e-8b40-c71d140c76c5": (
        "APPROVED_PRODUCT_TRUTH_DESCRIPTION_ABSENT"
    ),
    "5d298e84-2dc2-4747-9a0b-77499f5c8569": (
        "APPROVED_DESCRIPTION_IDENTIFIES_SAMPLE_SIZE_NOT_PRODUCT_SUBSTANCE"
    ),
    "60c65d01-5d27-465b-8b9b-20d3a8cd8b99": (
        "PRODUCT_TITLE_ONLY_WITHOUT_APPROVED_PRODUCT_TRUTH"
    ),
}


P58_PRODUCT_AUTHORITY_BLOCKERS = {
    "7712a709-d9eb-4203-a07f-249bceff9213": (
        "UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM",
        "ELECTRICAL_SAFETY_REVIEW_REQUIRED",
    ),
    "8014da71-6b87-4476-9eb2-a91baf7fc0dd": (
        "UNVERIFIED_LIGHT_OUTPUT_AND_RUNTIME_CLAIMS",
    ),
}


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _matches(value: str, candidates: tuple[str, ...]) -> bool:
    return not candidates or value in {_normalize(candidate) for candidate in candidates}


def resolve_catalog_product_type_truth(
    product: Mapping[str, object],
) -> CatalogProductTypeTruthMapping | None:
    """Resolve an exact source-authority mapping without title inference."""

    product_id = str(product.get("id") or product.get("product_id") or "")
    reviewed_override = P58_PRODUCT_TRUTH_OVERRIDES.get(product_id)
    if reviewed_override is not None:
        return reviewed_override
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


def catalog_product_type_truth_provenance(
    product: Mapping[str, object],
) -> str:
    product_id = str(product.get("id") or product.get("product_id") or "")
    if product_id in P58_PRODUCT_TRUTH_OVERRIDES:
        return "P5_8_PRODUCT_TRUTH_REVIEW"
    if resolve_catalog_product_type_truth(product) is not None:
        return "SOURCE_TAXONOMY"
    return "UNRESOLVED"


def iter_catalog_product_type_truth_registry_entries() -> tuple[
    CatalogProductTypeTruthMapping, ...
]:
    """Return one deterministic registry row per exact product-type pair."""

    by_pair: dict[tuple[str, str], CatalogProductTypeTruthMapping] = {}
    for mapping in (
        *CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS,
        *(
            mapping
            for mapping in P58_PRODUCT_TRUTH_OVERRIDES.values()
            if mapping.include_in_registry
        ),
    ):
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
