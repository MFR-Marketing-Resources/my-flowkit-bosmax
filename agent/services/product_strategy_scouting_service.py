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


SCOUTING_CLUSTER_ORDER = (
    "beauty_makeup",
    "beauty_personal_care",
    "fragrance",
    "food_cooking",
    "food_ready_to_eat",
    "household_laundry",
    "household_cleaning",
    "home_equipment",
    "home_storage",
    "baby_care",
    "fashion_apparel",
    "electronics_accessory",
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
    ),
    _ScoutingRule(
        "beauty_personal_care",
        "serum",
        terms=("serum", "face essence", "facial essence"),
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
        "vacuum",
        terms=(
            "vacuum",
            "vacuum cleaner",
            "cordless vacuum",
            "robot vacuum",
        ),
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
        specific_strategy_ids=("BEAUTY_PERSONAL_CARE",),
    ),
)


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
