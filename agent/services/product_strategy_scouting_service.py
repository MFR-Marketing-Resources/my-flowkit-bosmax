"""Deterministic cluster scouting for Scene Strategy expansion.

This service is a read-only planning layer. It groups catalog products by a
stable high-level cluster and product-use pattern, then measures current
coverage through the existing Scene Strategy Library resolver. It does not
mutate taxonomy, product rows, scene strategies, or generation state.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal, Mapping, TypedDict

from agent.authority.catalog_product_type_truth import (
    iter_catalog_product_type_truth_registry_entries,
    resolve_catalog_product_type_truth,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.scene_strategy_library import (
    ResolvedSceneStrategy,
    resolve_scene_strategy,
)


CoverageStatus = Literal["COVERED", "PARTIAL", "FALLBACK_ONLY"]


class ProductSample(TypedDict):
    product_id: str
    product_name: str


class DirectCopyNotes(TypedDict):
    hook: list[str]
    benefit: list[str]
    cta: list[str]


class ProductStrategyTag(TypedDict):
    cluster: str
    product_type_group: str
    product_id: str
    product_name: str
    matched_scene_strategy_id: str
    fallback_used: bool
    specific_strategy: bool
    direct_copy_notes: DirectCopyNotes


class ProductTypeGroupCoverage(TypedDict):
    cluster: str
    product_type_group: str
    product_count: int
    sample_products: list[ProductSample]
    matched_scene_strategy_id: str
    fallback_count: int
    specific_strategy_count: int
    coverage_status: CoverageStatus
    recommended_next_action: str
    direct_copy_notes: DirectCopyNotes


class ClusterCoverage(TypedDict):
    cluster: str
    product_count: int
    product_type_groups: list[ProductTypeGroupCoverage]
    next_product_type_group: str | None


class StrategyWorkItem(TypedDict):
    cluster: str
    product_type_group: str
    coverage_status: CoverageStatus
    recommended_next_action: str


class ProductStrategyScoutingReport(TypedDict):
    report_version: str
    product_total: int
    clusters: list[ClusterCoverage]
    ranked_work_queue: list[StrategyWorkItem]
    recommended_next_work: StrategyWorkItem | None
    note: str


@dataclass(frozen=True, slots=True)
class _ScoutingRule:
    cluster: str
    product_type_group: str
    terms: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    specific_strategy_ids: tuple[str, ...] = ()
    display_name: str | None = None
    auto_classification_enabled: bool = True
    reviewer_id: str | None = None
    reviewer_note: str | None = None


SCOUTING_CLUSTER_ORDER = (
    "beauty_makeup",
    "beauty_personal_care",
    "beauty_skincare",
    "fragrance",
    "food_cooking",
    "food_ready_to_eat",
    "food_beverage",
    "pet_care",
    "household_laundry",
    "household_cleaning",
    "home_equipment",
    "home_storage",
    "home_textiles",
    "home_improvement",
    "books_media",
    "craft_hobby",
    "baby_care",
    "fashion_apparel",
    "fashion_footwear",
    "electronics_accessory",
    "traditional_wellness",
    "sensitive_wellness",
    "generic_unclassified",
)


_PRODUCT_TEXT_FIELDS = (
    "raw_product_title",
    "product_display_name",
    "product_short_name",
    "category",
    "subcategory",
    "type",
    "product_type",
    "product_type_id",
    "silo",
)


_SCOUTING_RULES = (
    _ScoutingRule(
        "traditional_wellness",
        "traditional_herbal_oil",
        specific_strategy_ids=("TRADITIONAL_HERBAL_OIL",),
        display_name="Traditional Herbal Oil",
        auto_classification_enabled=False,
        reviewer_id="owner:Faris",
        reviewer_note=(
            "Owner-approved activation under "
            "BOSMAX-P5-CANONICAL-CLOSURE-AND-PRODUCT-ACTIVATION-20260729"
        ),
    ),
    _ScoutingRule(
        "traditional_wellness",
        "herbal_roll_on_oil",
        specific_strategy_ids=("HERBAL_ROLL_ON_OIL",),
        display_name="Herbal Roll-On Oil",
        auto_classification_enabled=False,
        reviewer_id="owner:Faris",
        reviewer_note=(
            "Owner-approved activation under "
            "BOSMAX-P5-CANONICAL-CLOSURE-AND-PRODUCT-ACTIVATION-20260729"
        ),
    ),
    _ScoutingRule(
        "sensitive_wellness",
        "male_wellness",
        terms=(
            "male wellness",
            "male health",
            "kesihatan lelaki",
            "batin lelaki",
            "kuat lelaki",
        ),
        families=("MALE_HEALTH_SENSITIVE",),
        specific_strategy_ids=("SENSITIVE_WELLNESS",),
    ),
    _ScoutingRule(
        "sensitive_wellness",
        "female_wellness",
        terms=(
            "female wellness",
            "female health",
            "kesihatan wanita",
            "jamu wanita",
            "kewanitaan",
            "feminine wellness",
        ),
        families=("FEMALE_HEALTH_SENSITIVE",),
        specific_strategy_ids=("SENSITIVE_WELLNESS",),
    ),
    _ScoutingRule(
        "beauty_makeup",
        "lipstick_lip_tint",
        terms=(
            "lipstick",
            "lipstik",
            "lip tint",
            "liptint",
            "lip gloss",
            "lipgloss",
            "lip liner",
            "lip colour",
            "lip color",
        ),
        specific_strategy_ids=("LIP_COLOR",),
    ),
    _ScoutingRule(
        "beauty_makeup",
        "mascara",
        terms=("mascara",),
    ),
    _ScoutingRule(
        "beauty_makeup",
        "eyeliner",
        terms=("eyeliner", "eye liner", "celak"),
    ),
    _ScoutingRule(
        "beauty_personal_care",
        "cleanser",
        terms=(
            "cleanser",
            "facial wash",
            "face wash",
            "pencuci muka",
            "cleansing gel",
        ),
        specific_strategy_ids=("CLEANSER",),
    ),
    _ScoutingRule(
        "beauty_personal_care",
        "serum",
        terms=("serum", "face essence", "facial essence"),
        specific_strategy_ids=("SERUM",),
    ),
    _ScoutingRule(
        "fragrance",
        "fragrance",
        terms=(
            "fragrance",
            "perfume",
            "body mist",
            "body spray",
            "eau de parfum",
        ),
        families=("beauty_fragrance",),
        specific_strategy_ids=("FRAGRANCE",),
    ),
    _ScoutingRule(
        "food_cooking",
        "rempah_seasoning",
        terms=(
            "rempah",
            "spice",
            "seasoning",
            "serbuk perasa",
            "perencah",
            "cooking powder",
        ),
        specific_strategy_ids=("SPICE_SEASONING",),
    ),
    _ScoutingRule(
        "food_cooking",
        "sambal",
        terms=("sambal", "chili paste"),
        specific_strategy_ids=("PACKAGED_SAUCE_SAMBAL",),
    ),
    _ScoutingRule(
        "food_cooking",
        "sauce",
        terms=("sauce", "sos", "cooking paste", "pes masakan"),
        specific_strategy_ids=("PACKAGED_SAUCE_SAMBAL",),
    ),
    _ScoutingRule(
        "food_ready_to_eat",
        "instant_food",
        terms=(
            "instant food",
            "instant noodle",
            "mee segera",
            "ready to eat",
            "ready meal",
            "makanan segera",
        ),
        specific_strategy_ids=("PACKAGED_FOOD",),
    ),
    _ScoutingRule(
        "food_ready_to_eat",
        "packaged_food",
        families=("food_packaged",),
        specific_strategy_ids=("PACKAGED_FOOD",),
    ),
    _ScoutingRule(
        "household_laundry",
        "detergent",
        terms=(
            "laundry detergent",
            "detergent",
            "detergen",
            "sabun dobi",
            "pencuci baju",
        ),
        families=("LAUNDRY_DETERGENT_LIQUID_REFILL",),
        specific_strategy_ids=("LAUNDRY_DETERGENT",),
    ),
    _ScoutingRule(
        "household_laundry",
        "softener",
        terms=("fabric softener", "softener", "pelembut", "pewangi pakaian"),
        families=("FABRIC_SOFTENER_LIQUID",),
        specific_strategy_ids=("FABRIC_SOFTENER",),
    ),
    # Home equipment must be tested before household cleaner because a vacuum
    # is commonly titled "vacuum cleaner" but is an appliance, not a liquid or
    # surface-cleaning product.
    _ScoutingRule(
        "home_equipment",
        "vacuum_sealer",
        terms=("vacuum sealer", "food sealer"),
        specific_strategy_ids=("VACUUM_SEALER",),
    ),
    _ScoutingRule(
        "home_equipment",
        "vacuum",
        terms=(
            "vacuum",
            "vacuum cleaner",
            "cordless vacuum",
            "robot vacuum",
        ),
        specific_strategy_ids=("VACUUM_CLEANER",),
    ),
    _ScoutingRule(
        "home_equipment",
        "blender",
        terms=("blender", "portable blender"),
        specific_strategy_ids=("ELECTRONICS_SMALL_DEVICE",),
    ),
    _ScoutingRule(
        "home_equipment",
        "chopper",
        terms=("chopper", "mini chopper", "food chopper"),
        specific_strategy_ids=("ELECTRONICS_SMALL_DEVICE",),
    ),
    _ScoutingRule(
        "home_equipment",
        "home_appliance",
        terms=(
            "home appliance",
            "kitchen appliance",
            "rice cooker",
            "air fryer",
            "electric kettle",
            "mixer",
        ),
    ),
    _ScoutingRule(
        "household_cleaning",
        "household_cleaner",
        terms=(
            "household cleaner",
            "floor cleaner",
            "toilet cleaner",
            "surface cleaner",
            "pencuci rumah",
            "pencuci lantai",
        ),
        families=("HOUSEHOLD_CLEANER_GENERAL",),
        specific_strategy_ids=("HOUSEHOLD_CLEANER",),
    ),
    _ScoutingRule(
        "home_storage",
        "storage_organizer",
        terms=(
            "organizer",
            "storage",
            "bekas simpan",
            "rak simpan",
            "storage box",
        ),
        families=("HOUSEHOLD_STORAGE_ORGANIZER",),
        specific_strategy_ids=("HOUSEHOLD_STORAGE",),
    ),
    _ScoutingRule(
        "baby_care",
        "baby_wipes",
        terms=("baby wipes", "wet wipes", "tisu basah"),
        families=("BABY_WIPES",),
        specific_strategy_ids=("BABY_WIPES",),
    ),
    _ScoutingRule(
        "baby_care",
        "baby_diaper",
        terms=("baby diaper", "diaper", "lampin", "pull ups"),
        families=("BABY_DIAPER",),
        specific_strategy_ids=("BABY_DIAPER",),
    ),
    _ScoutingRule(
        "fashion_apparel",
        "modestwear",
        terms=("modestwear", "tudung", "telekung", "khimar", "jubah"),
        families=("fashion_modestwear",),
        specific_strategy_ids=("MODESTWEAR",),
    ),
    _ScoutingRule(
        "fashion_apparel",
        "sportswear",
        terms=("sportswear", "activewear", "jersi", "jersey", "baju sukan"),
        families=("fashion_sportswear",),
        specific_strategy_ids=("SPORTSWEAR",),
    ),
    _ScoutingRule(
        "fashion_apparel",
        "apparel",
        terms=("apparel", "sleepwear", "baju tidur", "blouse", "dress"),
        families=("APPAREL_SLEEPWEAR", "fashion_apparel"),
        specific_strategy_ids=("APPAREL",),
    ),
    _ScoutingRule(
        "electronics_accessory",
        "electronics_accessory",
        terms=(
            "usb cable",
            "cable",
            "kabel",
            "charger",
            "pengecas",
            "power bank",
            "earphone",
            "earbuds",
            "phone holder",
        ),
        specific_strategy_ids=("ELECTRONICS_ACCESSORY",),
    ),
    _ScoutingRule(
        "electronics_accessory",
        "electronics_wearable",
        terms=("smartwatch", "smart watch", "fitness band"),
        families=("electronics_wearable",),
        specific_strategy_ids=("ELECTRONICS_SMALL_DEVICE",),
    ),
    _ScoutingRule(
        "beauty_personal_care",
        "beauty_personal_care_other",
        families=("BEAUTY_PERSONAL_CARE",),
    ),
)


def product_strategy_type_registry_seed_entries() -> list[dict[str, object]]:
    """Expose the existing P2 rule pairs as an explicit, reviewable seed plan."""

    entries: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in iter_catalog_product_type_truth_registry_entries():
        pair = (mapping.cluster, mapping.product_type_group)
        seen.add(pair)
        has_specific_strategy = mapping.specific_scene_strategy_id is not None
        entries.append(
            {
                "cluster": mapping.cluster,
                "product_type_group": mapping.product_type_group,
                "display_name": mapping.display_name,
                "matched_scene_strategy_id": (
                    mapping.specific_scene_strategy_id
                    if has_specific_strategy
                    else "GENERIC_FALLBACK"
                ),
                "scene_coverage_status": (
                    "COVERED" if has_specific_strategy else "FALLBACK_ONLY"
                ),
                "registry_status": (
                    "ACTIVE" if has_specific_strategy else "REVIEW_REQUIRED"
                ),
                "auto_classification_enabled": (
                    mapping.auto_classification_enabled
                ),
                "authority_source": "SYSTEM_SEED",
                "reviewer_id": (
                    mapping.reviewer_id if has_specific_strategy else None
                ),
                "reviewer_note": (
                    mapping.reviewer_note if has_specific_strategy else None
                ),
            }
        )
    for rule in _SCOUTING_RULES:
        key = (rule.cluster, rule.product_type_group)
        if key in seen:
            continue
        seen.add(key)
        has_specific_strategy = bool(rule.specific_strategy_ids)
        entries.append(
            {
                "cluster": rule.cluster,
                "product_type_group": rule.product_type_group,
                "display_name": (
                    rule.display_name
                    or rule.product_type_group.replace("_", " ").title()
                ),
                "matched_scene_strategy_id": (
                    rule.specific_strategy_ids[0]
                    if has_specific_strategy
                    else "GENERIC_FALLBACK"
                ),
                "scene_coverage_status": (
                    "COVERED" if has_specific_strategy else "FALLBACK_ONLY"
                ),
                "registry_status": (
                    "ACTIVE" if has_specific_strategy else "REVIEW_REQUIRED"
                ),
                "auto_classification_enabled": rule.auto_classification_enabled,
                "authority_source": "SYSTEM_SEED",
                "reviewer_id": rule.reviewer_id,
                "reviewer_note": rule.reviewer_note,
            }
        )
    entries.append(
        {
            "cluster": "generic_unclassified",
            "product_type_group": "unknown_product_type",
            "display_name": "Unknown Product Type",
            "matched_scene_strategy_id": "GENERIC_FALLBACK",
            "scene_coverage_status": "FALLBACK_ONLY",
            "registry_status": "REVIEW_REQUIRED",
            "auto_classification_enabled": False,
            "authority_source": "SYSTEM_SEED",
        }
    )
    return entries


_STRATEGY_FALLBACK_TAGS = {
    "LIP_COLOR": ("beauty_makeup", "lipstick_lip_tint", ("LIP_COLOR",)),
    "BEAUTY_PERSONAL_CARE": (
        "beauty_personal_care",
        "beauty_personal_care_other",
        ("BEAUTY_PERSONAL_CARE",),
    ),
    "FRAGRANCE": ("fragrance", "fragrance", ("FRAGRANCE",)),
    "SPICE_SEASONING": (
        "food_cooking",
        "rempah_seasoning",
        ("SPICE_SEASONING",),
    ),
    "PACKAGED_SAUCE_SAMBAL": (
        "food_cooking",
        "sauce",
        ("PACKAGED_SAUCE_SAMBAL",),
    ),
    "PACKAGED_FOOD": (
        "food_ready_to_eat",
        "packaged_food",
        ("PACKAGED_FOOD",),
    ),
    "LAUNDRY_DETERGENT": (
        "household_laundry",
        "detergent",
        ("LAUNDRY_DETERGENT",),
    ),
    "FABRIC_SOFTENER": (
        "household_laundry",
        "softener",
        ("FABRIC_SOFTENER",),
    ),
    "BABY_WIPES": ("baby_care", "baby_wipes", ("BABY_WIPES",)),
    "BABY_DIAPER": ("baby_care", "baby_diaper", ("BABY_DIAPER",)),
    "APPAREL": ("fashion_apparel", "apparel", ("APPAREL",)),
    "MODESTWEAR": ("fashion_apparel", "modestwear", ("MODESTWEAR",)),
    "SPORTSWEAR": ("fashion_apparel", "sportswear", ("SPORTSWEAR",)),
    "HOUSEHOLD_CLEANER": (
        "household_cleaning",
        "household_cleaner",
        ("HOUSEHOLD_CLEANER",),
    ),
    "HOUSEHOLD_STORAGE": (
        "home_storage",
        "storage_organizer",
        ("HOUSEHOLD_STORAGE",),
    ),
    "ELECTRONICS_ACCESSORY": (
        "electronics_accessory",
        "electronics_accessory",
        ("ELECTRONICS_ACCESSORY",),
    ),
    "ELECTRONICS_SMALL_DEVICE": (
        "home_equipment",
        "home_appliance",
        ("ELECTRONICS_SMALL_DEVICE",),
    ),
    "SENSITIVE_WELLNESS": (
        "sensitive_wellness",
        "sensitive_wellness",
        ("SENSITIVE_WELLNESS",),
    ),
}


# ---------------------------------------------------------------------------
# Category-aware LAST-RESORT layer (BOSMAX category coverage).
#
# The proven rules above key off PRODUCT-TYPE keywords + family, never the
# TikTok `category`. Bulk-imported products whose TITLE uses a term not yet in a
# rule (fishing "pancing", curtains "langsir", supplements, pet food) therefore
# fall through to generic_unclassified even though their category maps cleanly to
# a real cluster. The two structures below add a last-resort layer that runs ONLY
# after every proven rule has missed, so nothing that already classifies is
# affected (provably no regression to proven classifications).
#
# `product_type_group` reuses the existing free-form vocabulary where one fits;
# new labels are accurate categorisation FROM THE TITLE, never invented product
# facts. Every cluster below is a member of the 40 strategy clusters.

# 1) Precise TITLE-keyword rules — these WIN over the coarse category map, so a
#    mis-categorised item (e.g. a wardrobe "dehumidifier" listed under
#    Automotive, or a "raincoat" under Automotive) maps to what its TITLE says,
#    not to its noisy category.
_CATEGORY_KEYWORD_RULES: tuple[_ScoutingRule, ...] = (
    # noise corrections first (items commonly mis-filed under a wrong category)
    _ScoutingRule(
        "home_equipment", "dehumidifier",
        terms=("dehumidifier", "moisture absorber", "penyerap lembapan"),
    ),
    _ScoutingRule(
        "fashion_apparel", "outerwear",
        terms=("raincoat", "rainsuit", "baju hujan", "windbreaker"),
    ),
    # fishing gear (dominates Sports & Outdoor)
    _ScoutingRule(
        "outdoor_equipment", "fishing_gear",
        terms=(
            "pancing", "memancing", "kekili", "baitcasting", "spinning reel",
            "fishing reel", "fishing line", "fishing rod",
        ),
    ),
    _ScoutingRule(
        "fashion_apparel", "sportswear",
        terms=("sports bra", "baju sukan", "jersey"),
    ),
    # curtains / blankets (Textiles & Soft Furnishings)
    _ScoutingRule(
        "home_textiles", "curtain",
        terms=("langsir", "curtain", "blackout"),
    ),
    _ScoutingRule(
        "home_textiles", "bedding",
        terms=("selimut", "blanket", "bedsheet", "cadar", "comforter"),
    ),
    # aromatherapy / scent oils are fragrance, NOT wellness — keeps foreign scent
    # products out of BOSMAX's flagship traditional_wellness cluster.
    _ScoutingRule(
        "fragrance", "fragrance",
        terms=("aromatherapy", "essential oil", "minyak wangi"),
    ),
    # wellness supplements (Health). auto_classification_enabled=False so a
    # THIRD-PARTY nutraceutical folded here for grouping never auto-activates
    # generation under the flagship cluster (adversarial review, flagship gate).
    _ScoutingRule(
        "traditional_wellness", "wellness_supplement",
        terms=(
            "supplement", "suplemen", "kapsul", "capsule", "vitamin",
            "glutathione", "astaxanthin", "gummies", "collagen", "kolagen",
        ),
        auto_classification_enabled=False,
    ),
    # pet
    _ScoutingRule(
        "pet_care", "pet_food",
        terms=("cat food", "makanan kucing", "makanan anjing", "kibbles"),
    ),
    _ScoutingRule(
        "pet_care", "pet_supply",
        terms=("cat litter", "tandas kucing", "mainan kucing", "kucing"),
    ),
    # baby (runs before the generic towel rule so a "baby bath towel" stays baby)
    _ScoutingRule(
        "baby_care", "baby_care_item",
        terms=("pacifier", "puting", "swaddle", "baby bath", "baby towel", "stroller"),
    ),
    # plain towels are home textiles
    _ScoutingRule(
        "home_textiles", "towel",
        terms=("bath towel", "tuala mandi", "towel", "tuala"),
    ),
    # garden (fertiliser / lawn tools that land under Home Improvement / Tools)
    _ScoutingRule(
        "garden_care", "garden_supply",
        terms=("baja", "fertilizer", "pupuk", "lawn mower", "mesin rumput"),
    ),
    # bags / wallets (Luggage & Bags)
    _ScoutingRule(
        "fashion_accessory", "bag_wallet",
        terms=("wallet", "dompet", "sling bag", "beg silang", "backpack", "luggage"),
    ),
    # books
    _ScoutingRule(
        "books_media", "book",
        terms=("buku", "skema jawapan", "magazine", "majalah"),
    ),
)

# 2) Coarse category -> (cluster, product_type_group). Fires only if NO keyword
#    rule (proven OR category) matched. Every cluster is one of the 40. Keys are
#    the _normalize()d form of the TikTok category (casefold, non-alphanumerics
#    collapsed to single spaces) so the lookup in _category_aware_rule matches;
#    _TIKTOK_CATEGORY_FALLBACK_RAW is the human-readable source, asserted equal by
#    test so the two never drift.
_TIKTOK_CATEGORY_FALLBACK_RAW: dict[str, tuple[str, str]] = {
    "Sports & Outdoor": ("outdoor_equipment", "sports_outdoor_gear"),
    "Health": ("traditional_wellness", "wellness_supplement"),
    "Pet Supplies": ("pet_care", "pet_supply"),
    "Home Improvement": ("home_improvement", "home_improvement_supply"),
    "Textiles & Soft Furnishings": ("home_textiles", "home_textile"),
    "Automotive & Motorcycle": ("automotive_accessory", "automotive_accessory"),
    "Toys & Hobbies": ("craft_hobby", "toy_hobby"),
    "Baby & Maternity": ("baby_care", "baby_care_item"),
    "Luggage & Bags": ("fashion_accessory", "bag_wallet"),
    "Tools & Hardware": ("home_improvement", "hardware_tool"),
    # Home Supplies residual is dominated by organisers/hooks -> home_storage
    # (adversarial review: home_equipment mislabelled the wall-hook organiser).
    "Home Supplies": ("home_storage", "storage_organizer"),
    "Books, Magazines & Audio": ("books_media", "book"),
    # The lone item is a book-shaped savings box / the lone collectible is a set
    # of Raya money envelopes — both paper/desk goods, not electronics/craft
    # (adversarial review).
    "Computers & Office Equipment": ("stationery", "office_supply"),
    "Collectibles": ("stationery", "gift_stationery"),
}
# Built below _normalize() is defined, so use the same collapse here (inline) to
# avoid a forward reference at module load.
_TIKTOK_CATEGORY_FALLBACK: dict[str, tuple[str, str]] = {
    re.sub(r"[^a-z0-9]+", " ", raw.casefold()).strip(): value
    for raw, value in _TIKTOK_CATEGORY_FALLBACK_RAW.items()
}


def _category_aware_rule(product: Mapping[str, object], haystack: str) -> _ScoutingRule | None:
    """Last-resort category layer. Returns None so the caller keeps its final
    generic behaviour when neither a keyword rule nor the category map matches."""
    for rule in _CATEGORY_KEYWORD_RULES:
        if any(_contains_term(haystack, term) for term in rule.terms):
            return rule
    coarse = _TIKTOK_CATEGORY_FALLBACK.get(_normalize(product.get("category")))
    if coarse:
        return _ScoutingRule(coarse[0], coarse[1], auto_classification_enabled=False)
    return None


_GROUP_ORDER = {
    (rule.cluster, rule.product_type_group): index
    for index, rule in enumerate(_SCOUTING_RULES)
}
_CLUSTER_ORDER = {
    cluster: index for index, cluster in enumerate(SCOUTING_CLUSTER_ORDER)
}


def _normalize(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _contains_term(haystack: str, term: str) -> bool:
    return f" {_normalize(term)} " in f" {haystack} "


def _product_text(product: Mapping[str, object]) -> str:
    return " ".join(
        normalized
        for field in _PRODUCT_TEXT_FIELDS
        if (normalized := _normalize(product.get(field)))
    )


def _product_name(product: Mapping[str, object]) -> str:
    for field in (
        "product_display_name",
        "product_short_name",
        "raw_product_title",
    ):
        value = str(product.get(field) or "").strip()
        if value:
            return value
    return "Unnamed product"


def _empty_copy_notes() -> DirectCopyNotes:
    return {"hook": [], "benefit": [], "cta": []}


def _direct_copy_notes(
    strategy: ResolvedSceneStrategy,
    *,
    specific_strategy: bool,
) -> DirectCopyNotes:
    if not specific_strategy:
        return _empty_copy_notes()
    slots = strategy["direct_script_slots"]
    return {
        "hook": list(slots["hook"]),
        "benefit": list(slots["benefit"]),
        "cta": list(slots["cta"]),
    }


def _matched_rule(
    product: Mapping[str, object],
    strategy: ResolvedSceneStrategy,
) -> _ScoutingRule:
    truth_mapping = resolve_catalog_product_type_truth(product)
    if truth_mapping is not None:
        return _ScoutingRule(
            truth_mapping.cluster,
            truth_mapping.product_type_group,
            specific_strategy_ids=(
                (truth_mapping.specific_scene_strategy_id,)
                if truth_mapping.specific_scene_strategy_id
                else ()
            ),
            display_name=truth_mapping.display_name,
            reviewer_id=(
                truth_mapping.reviewer_id
                if truth_mapping.specific_scene_strategy_id
                else None
            ),
            reviewer_note=(
                truth_mapping.reviewer_note
                if truth_mapping.specific_scene_strategy_id
                else None
            ),
        )

    haystack = _product_text(product)
    family = _normalize(
        derive_bosmax_product_family(dict(product))["bosmax_product_family"]
    )

    # Product-type text is stronger than a broad family. This is load-bearing
    # for cases such as "vacuum cleaner", which must remain home equipment.
    for rule in _SCOUTING_RULES:
        if any(_contains_term(haystack, term) for term in rule.terms):
            return rule

    for rule in _SCOUTING_RULES:
        if family and any(family == _normalize(value) for value in rule.families):
            return rule

    strategy_tag = _STRATEGY_FALLBACK_TAGS.get(strategy["strategy_id"])
    if strategy_tag:
        cluster, product_type_group, strategy_ids = strategy_tag
        return _ScoutingRule(
            cluster,
            product_type_group,
            specific_strategy_ids=strategy_ids,
        )

    # Last resort: use the TikTok category (a known, real signal) before giving
    # up. Only reached when every proven rule above has already missed.
    category_rule = _category_aware_rule(product, haystack)
    if category_rule is not None:
        return category_rule

    return _ScoutingRule("generic_unclassified", "unknown_product_type")


def classify_product_strategy_tag(
    product: Mapping[str, object],
) -> ProductStrategyTag:
    """Classify one product without mutating or enriching its stored fields."""

    strategy = resolve_scene_strategy(product)
    rule = _matched_rule(product, strategy)
    specific_strategy = (
        not strategy["fallback_used"]
        and strategy["strategy_id"] in rule.specific_strategy_ids
    )
    return {
        "cluster": rule.cluster,
        "product_type_group": rule.product_type_group,
        "product_id": str(product.get("id") or product.get("product_id") or ""),
        "product_name": _product_name(product),
        "matched_scene_strategy_id": strategy["strategy_id"],
        "fallback_used": strategy["fallback_used"],
        "specific_strategy": specific_strategy,
        "direct_copy_notes": _direct_copy_notes(
            strategy,
            specific_strategy=specific_strategy,
        ),
    }


def _append_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _dominant_strategy_id(tags: list[ProductStrategyTag]) -> str:
    counts = Counter(tag["matched_scene_strategy_id"] for tag in tags)
    return sorted(counts, key=lambda strategy_id: (-counts[strategy_id], strategy_id))[0]


def _coverage_status(
    *,
    product_count: int,
    fallback_count: int,
    specific_strategy_count: int,
) -> CoverageStatus:
    if fallback_count == product_count:
        return "FALLBACK_ONLY"
    if specific_strategy_count == product_count:
        return "COVERED"
    return "PARTIAL"


def _recommended_next_action(
    *,
    cluster: str,
    product_type_group: str,
    product_count: int,
    matched_scene_strategy_id: str,
    fallback_count: int,
    specific_strategy_count: int,
    coverage_status: CoverageStatus,
) -> str:
    target = f"{cluster} -> {product_type_group}"
    if coverage_status == "COVERED":
        return (
            f"Maintain {target}; all {product_count} products resolve to "
            f"product-type-specific strategy {matched_scene_strategy_id}."
        )
    if coverage_status == "FALLBACK_ONLY":
        return (
            f"Build one dedicated scene strategy for {target}; all "
            f"{product_count} products currently use GENERIC_FALLBACK."
        )
    if fallback_count:
        return (
            f"Expand {target} as one scoped strategy; {fallback_count} of "
            f"{product_count} products use fallback and "
            f"{specific_strategy_count} have product-type-specific coverage."
        )
    return (
        f"Expand {target} as one scoped strategy; the current resolver uses "
        f"{matched_scene_strategy_id}, but product-type-specific coverage is "
        f"{specific_strategy_count}/{product_count}."
    )


def _build_group_coverage(
    cluster: str,
    product_type_group: str,
    tags: list[ProductStrategyTag],
    *,
    sample_limit: int,
) -> ProductTypeGroupCoverage:
    ordered_tags = sorted(
        tags,
        key=lambda tag: (
            _normalize(tag["product_name"]),
            tag["product_id"],
        ),
    )
    product_count = len(ordered_tags)
    fallback_count = sum(1 for tag in ordered_tags if tag["fallback_used"])
    specific_strategy_count = sum(
        1 for tag in ordered_tags if tag["specific_strategy"]
    )
    matched_scene_strategy_id = _dominant_strategy_id(ordered_tags)
    coverage_status = _coverage_status(
        product_count=product_count,
        fallback_count=fallback_count,
        specific_strategy_count=specific_strategy_count,
    )
    copy_notes = _empty_copy_notes()
    for tag in ordered_tags:
        for slot in ("hook", "benefit", "cta"):
            _append_unique(copy_notes[slot], tag["direct_copy_notes"][slot])

    return {
        "cluster": cluster,
        "product_type_group": product_type_group,
        "product_count": product_count,
        "sample_products": [
            {
                "product_id": tag["product_id"],
                "product_name": tag["product_name"],
            }
            for tag in ordered_tags[:sample_limit]
        ],
        "matched_scene_strategy_id": matched_scene_strategy_id,
        "fallback_count": fallback_count,
        "specific_strategy_count": specific_strategy_count,
        "coverage_status": coverage_status,
        "recommended_next_action": _recommended_next_action(
            cluster=cluster,
            product_type_group=product_type_group,
            product_count=product_count,
            matched_scene_strategy_id=matched_scene_strategy_id,
            fallback_count=fallback_count,
            specific_strategy_count=specific_strategy_count,
            coverage_status=coverage_status,
        ),
        "direct_copy_notes": copy_notes,
    }


def _group_sort_key(
    cluster: str,
    product_type_group: str,
) -> tuple[int, str]:
    return (
        _GROUP_ORDER.get((cluster, product_type_group), len(_GROUP_ORDER)),
        product_type_group,
    )


def build_product_strategy_scouting_report(
    products: list[Mapping[str, object]],
    *,
    sample_limit: int = 3,
) -> ProductStrategyScoutingReport:
    """Build a deterministic cluster-first Scene Strategy work report."""

    resolved_sample_limit = max(int(sample_limit), 1)
    grouped: dict[str, dict[str, list[ProductStrategyTag]]] = {
        cluster: {} for cluster in SCOUTING_CLUSTER_ORDER
    }
    for product in products:
        tag = classify_product_strategy_tag(product)
        grouped[tag["cluster"]].setdefault(tag["product_type_group"], []).append(tag)

    cluster_reports: list[ClusterCoverage] = []
    ranked_work_queue: list[StrategyWorkItem] = []
    for cluster in SCOUTING_CLUSTER_ORDER:
        type_groups = grouped[cluster]
        group_reports = [
            _build_group_coverage(
                cluster,
                product_type_group,
                tags,
                sample_limit=resolved_sample_limit,
            )
            for product_type_group, tags in sorted(
                type_groups.items(),
                key=lambda item: _group_sort_key(cluster, item[0]),
            )
        ]
        uncovered_groups = [
            group
            for group in group_reports
            if group["coverage_status"] != "COVERED"
        ]
        cluster_reports.append(
            {
                "cluster": cluster,
                "product_count": sum(
                    group["product_count"] for group in group_reports
                ),
                "product_type_groups": group_reports,
                "next_product_type_group": (
                    uncovered_groups[0]["product_type_group"]
                    if uncovered_groups
                    else None
                ),
            }
        )
        ranked_work_queue.extend(
            {
                "cluster": group["cluster"],
                "product_type_group": group["product_type_group"],
                "coverage_status": group["coverage_status"],
                "recommended_next_action": group["recommended_next_action"],
            }
            for group in uncovered_groups
        )

    ranked_work_queue.sort(
        key=lambda item: (
            _CLUSTER_ORDER[item["cluster"]],
            _group_sort_key(item["cluster"], item["product_type_group"]),
        )
    )
    return {
        "report_version": "product_strategy_scouting_v1",
        "product_total": len(products),
        "clusters": cluster_reports,
        "ranked_work_queue": ranked_work_queue,
        "recommended_next_work": (
            dict(ranked_work_queue[0]) if ranked_work_queue else None
        ),
        "note": (
            "Read-only cluster-first scouting. Each work item targets exactly "
            "one cluster and one product type; no product rows are mutated."
        ),
    }


async def get_product_strategy_scouting_report(
    *,
    sample_limit: int = 3,
) -> ProductStrategyScoutingReport:
    """Load active catalog products and build the read-only scouting report."""

    from agent.db import crud

    products = await crud.list_products(limit=10000, include_archived=False)
    return build_product_strategy_scouting_report(
        products,
        sample_limit=sample_limit,
    )
