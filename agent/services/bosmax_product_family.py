from __future__ import annotations

from typing import Any

from agent.services.product_mapping import normalize_mapping_text


def _joined_text(product: dict[str, Any]) -> str:
    parts = [
        product.get("raw_product_title"),
        product.get("product_display_name"),
        product.get("product_short_name"),
        product.get("category"),
        product.get("subcategory"),
        product.get("type"),
        product.get("product_type"),
    ]
    return " ".join(normalize_mapping_text(part) for part in parts if part)


def _contains_any(haystack: str, keywords: list[str]) -> bool:
    return any(normalize_mapping_text(keyword) in haystack for keyword in keywords)


def derive_bosmax_product_family(product: dict[str, Any]) -> dict[str, Any]:
    haystack = _joined_text(product)
    category = normalize_mapping_text(product.get("category"))
    subcategory = normalize_mapping_text(product.get("subcategory"))
    type_name = normalize_mapping_text(product.get("type"))

    family = "GENERIC_UNCLASSIFIED"
    reason = "No BOSMAX family match found. Generic fallback remains in use."

    if _contains_any(
        haystack,
        [
            "sabun dobi",
            "liquid laundry detergent",
            "laundry detergent",
            "detergen",
            "detergent refill",
            "fabric cleaner",
            "pencuci baju",
            "isi ulang",
        ],
    ):
        family = "LAUNDRY_DETERGENT_LIQUID_REFILL"
        reason = "Laundry detergent/refill keywords matched before source taxonomy fallback."
    elif _contains_any(
        haystack,
        [
            "softener",
            "pelembut",
            "fabric softener",
            "pewangi pakaian",
            "pewangi sabun baju",
        ],
    ):
        family = "FABRIC_SOFTENER_LIQUID"
        reason = "Fabric softener / pewangi pakaian keywords matched."
    elif _contains_any(
        haystack,
        [
            "organizer",
            "storage",
            "bekas simpan",
            "drawer organizer",
            "kitchen storage",
            "rak",
            "hanger storage",
            "container set",
        ],
    ):
        family = "HOUSEHOLD_STORAGE_ORGANIZER"
        reason = "Storage / organizer keywords matched."
    elif _contains_any(
        haystack,
        [
            "towel",
            "tuala",
            "blanket",
            "comforter",
            "selimut",
            "bedsheet",
            "cadar",
            "duvet",
            "curtain",
            "pillow",
            "quilt",
            "carpet",
            "karpet",
            "rug",
        ],
    ):
        # Guardrail: HOME_TEXTILE must not hijack beauty powder/matte products.
        # We check if 'matte' or 'powder' is present and if it's likely beauty.
        if _contains_any(haystack, ["matte", "powder", "compact powder", "foundation"]) and not _contains_any(haystack, ["carpet", "rug", "towel"]):
            pass # Let it fall through to beauty or unknown
        else:
            family = "HOME_TEXTILE"
            reason = "Home textile keywords matched."
    elif _contains_any(
        haystack,
        [
            "cleaner",
            "all purpose cleaner",
            "floor cleaner",
            "toilet cleaner",
            "kitchen cleaner",
            "household cleaner",
            "sabun pencuci",
        ],
    ):
        family = "HOUSEHOLD_CLEANER_GENERAL"
        reason = "General household cleaner keywords matched."
    elif _contains_any(
        haystack,
        [
            "sleepwear",
            "loungewear",
            "nightdress",
            "nightdresses",
            "nightie",
            "baju tidur",
            "kelawar",
            "women s sleepwear",
        ],
    ):
        family = "APPAREL_SLEEPWEAR"
        reason = "Sleepwear/apparel keywords matched."
    elif _contains_any(
        haystack,
        [
            "instant sarung",
            "sarung syria",
            "khimar",
            "telekung",
            "tudung labuh",
            "moscrepe",
        ],
    ):
        family = "fashion_modestwear"
        reason = "Modestwear keywords matched."
    elif _contains_any(
        haystack,
        [
            "jersey",
            "jersi",
            "athleisure",
            "baju sukan",
            "quick dry",
        ],
    ):
        family = "fashion_sportswear"
        reason = "Sportswear keywords matched."
    elif _contains_any(
        haystack,
        [
            "body spray",
            "fragrance",
            "perfume",
            "body mist",
        ],
    ):
        family = "beauty_fragrance"
        reason = "Fragrance keywords matched."
    elif _contains_any(
        haystack,
        [
            "serum",
            "skincare",
            "cosmetic",
            "lip balm",
            "personal care",
            "beauty",
            "bath and body",
            "bath body",
        ],
    ):
        family = "BEAUTY_PERSONAL_CARE"
        reason = "Beauty / personal care keywords matched."
    elif _contains_any(
        haystack,
        [
            "accessory",
            "earring",
            "brooch",
            "pin",
            "charm",
            "pendant",
            "keychain",
            "small item",
        ],
    ):
        family = "ACCESSORY_SMALL_ITEM"
        reason = "Accessory / small-item keywords matched."
    elif _contains_any(haystack, ["baby wipes", "wet wipes", "wet tissue", "tisu basah", "baby tissue"]):
        family = "BABY_WIPES"
        reason = "Baby wipes keywords matched."
    elif _contains_any(haystack, ["diaper", "lampin", "pull ups", "baby diaper"]):
        family = "BABY_DIAPER"
        reason = "Baby diaper keywords matched."
    elif _contains_any(haystack, ["sambal", "ready to eat", "sauce", "food"]):
        family = "food_packaged"
        reason = "Packaged-food keywords matched."
    elif _contains_any(haystack, ["money packet", "duit raya", "angpow", "envelope"]):
        family = "stationery_paper"
        reason = "Stationery / festive-envelope keywords matched."
    elif _contains_any(haystack, ["smartwatch", "wearable", "jam tangan"]):
        family = "electronics_wearable"
        reason = "Wearable-device keywords matched."
    elif _contains_any(haystack, ["male health", "suami isteri", "batin", "tahan lama", "kuat lelaki"]):
        # Strict Isolation: MALE_HEALTH_SENSITIVE requires specific sensitive health tokens.
        # Simple 'lelaki' or 'men' or 'pants' are handled by fashion logic below.
        family = "MALE_HEALTH_SENSITIVE"
        reason = "Sensitive male-health keywords matched."
    elif _contains_any(haystack, ["toy", "mainan"]):
        family = "toy_play"
        reason = "Toy / play keywords matched."
    elif category == "fashion" and subcategory in {"bottoms", "muslim fashion"}:
        family = "fashion_apparel"
        reason = "Fashion taxonomy fallback matched."
    elif category in {"home supplies", "home living", "home and living"}:
        family = "HOUSEHOLD_CLEANER_GENERAL"
        reason = "Home taxonomy fell back to general household cleaner family."
    elif category in {"beauty personal care", "beauty and personal care"}:
        family = "BEAUTY_PERSONAL_CARE"
        reason = "Beauty taxonomy fallback matched."
    elif category in {"womenswear and underwear", "fashion", "muslim fashion"}:
        family = "fashion_apparel"
        reason = "Apparel taxonomy fallback matched."
    elif category in {"food beverage", "food and beverage"}:
        family = "food_packaged"
        reason = "Food taxonomy fallback matched."
    elif category == "stationery":
        family = "stationery_paper"
        reason = "Stationery taxonomy fallback matched."

    source_taxonomy_conflict = False
    conflict_reason = ""
    if family in {
        "LAUNDRY_DETERGENT_LIQUID_REFILL",
        "FABRIC_SOFTENER_LIQUID",
        "HOUSEHOLD_CLEANER_GENERAL",
        "HOUSEHOLD_STORAGE_ORGANIZER",
        "HOME_TEXTILE",
    } and category in {"baby care", "baby and maternity", "baby maternity"}:
        source_taxonomy_conflict = True
        conflict_reason = (
            "Household-family product contradicted source taxonomy under baby-care lanes."
        )
    elif family == "HOUSEHOLD_STORAGE_ORGANIZER" and _contains_any(
        haystack, ["sabun dobi", "laundry detergent", "detergen"]
    ):
        source_taxonomy_conflict = True
        conflict_reason = (
            "Storage/organizer family conflicts with detergent/cleaning product cues."
        )
    elif family == "HOME_TEXTILE" and category in {"beauty personal care", "beauty and personal care"}:
        source_taxonomy_conflict = True
        conflict_reason = "Home textile family contradicted beauty taxonomy."

    return {
        "bosmax_product_family": family,
        "bosmax_product_family_reason": reason,
        "bosmax_source_taxonomy_conflict": source_taxonomy_conflict,
        "bosmax_source_taxonomy_conflict_reason": conflict_reason,
        "bosmax_family_uses_generic_fallback": family == "GENERIC_UNCLASSIFIED",
        "bosmax_family_category": category,
        "bosmax_family_subcategory": subcategory,
        "bosmax_family_type": type_name,
    }
