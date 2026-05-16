from __future__ import annotations

from collections import Counter
from typing import Any

from agent.db import crud
from agent.models.product_intelligence import (
    AllProductMappingAuditExample,
    AllProductMappingAuditResponse,
)
from agent.services.product_intelligence import resolve_image_readiness
from agent.services.product_intelligence_service import resolve_product_intelligence_profile


BEAUTY_KEYWORDS = (
    "lip balm",
    "lipstick",
    "lip tint",
    "foundation",
    "serum",
    "mascara",
    "maskara",
    "eyeliner",
    "blusher",
    "perfume",
    "body mist",
    "fragrance mist",
)
BABY_WIPES_KEYWORDS = ("baby wipes", "wet wipes", "wet tissue", "tisu basah")
FASHION_KEYWORDS = (
    "pants",
    "seluar",
    "legging",
    "jeans",
    "bra",
    "jersi",
    "jersey",
    "baju",
    "hijab",
    "blouse",
)
HOME_ELECTRONICS_KEYWORDS = (
    "fan",
    "kipas",
    "storage",
    "organizer",
    "hanger",
    "rack",
    "kitchen",
    "dapur",
    "electronic",
    "charger",
    "adapter",
)
MALE_HEALTH_KEYWORDS = (
    "vital lelaki",
    "kuat lelaki",
    "tahan lama",
    "intim",
    "kelamin",
    "batin",
    "nafsu",
)

BEAUTY_TAXONOMY_KEYWORDS = ("beauty", "fragrance", "cosmetic", "bath body", "body care", "skin care")
FASHION_TAXONOMY_KEYWORDS = ("fashion", "womenswear", "muslim fashion", "underwear", "sportswear")
BABY_TAXONOMY_KEYWORDS = ("baby", "diaper")
HOME_TEXTILE_FAMILIES = {"HOME_TEXTILE"}
HOUSEHOLD_GROUPS = {"HOUSEHOLD_CARE", "LAUNDRY_CARE", "HOME_ORGANIZATION"}
SEMANTIC_UNAVAILABLE_STATUSES = {"NOT_ANALYZED", "VISION_PROVIDER_NOT_CONFIGURED"}


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def _dist(values: list[str]) -> dict[str, int]:
    counter = Counter(value or "UNKNOWN" for value in values)
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _source_taxonomy_blob(product: dict[str, Any]) -> str:
    return " ".join(
        _normalize(product.get(field))
        for field in ("category", "subcategory", "type")
        if _normalize(product.get(field))
    )


def _title_blob(product: dict[str, Any], profile: dict[str, Any]) -> str:
    values = [
        product.get("raw_product_title"),
        product.get("product_display_name"),
        product.get("product_short_name"),
        profile.get("normalized_title"),
    ]
    return " ".join(_normalize(value) for value in values if _normalize(value))


def _reasons_for_product(product: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    title = _title_blob(product, profile)
    taxonomy = _source_taxonomy_blob(product)
    group = str(profile.get("group") or "")
    family = str(profile.get("bosmax_product_family") or "")
    confidence = str(profile.get("confidence") or "")
    reasons: list[str] = []

    has_male_health_title = _contains_any(title, MALE_HEALTH_KEYWORDS)
    has_beauty_evidence = _contains_any(title, BEAUTY_KEYWORDS) or _contains_any(taxonomy, BEAUTY_TAXONOMY_KEYWORDS)
    has_baby_wipes_evidence = _contains_any(title, BABY_WIPES_KEYWORDS) or (
        _contains_any(taxonomy, BABY_TAXONOMY_KEYWORDS) and "wipes" in taxonomy
    )
    has_fashion_evidence = _contains_any(title, FASHION_KEYWORDS) or _contains_any(taxonomy, FASHION_TAXONOMY_KEYWORDS)
    has_home_or_electronics_evidence = _contains_any(title, HOME_ELECTRONICS_KEYWORDS) or _contains_any(
        taxonomy,
        ("electronics", "kitchenware", "household appliances", "home improvement", "storage"),
    )

    if has_beauty_evidence and (group in HOUSEHOLD_GROUPS or family in HOME_TEXTILE_FAMILIES):
        reasons.append("BEAUTY_EVIDENCE_CONTRADICTS_HOUSEHOLD_OR_HOME_TEXTILE_MAPPING")

    if has_baby_wipes_evidence and family == "beauty_fragrance":
        reasons.append("BABY_WIPES_EVIDENCE_CONTRADICTS_FRAGRANCE_FAMILY")

    if has_fashion_evidence and group == "MALE_HEALTH_SENSITIVE" and not has_male_health_title:
        reasons.append("FASHION_EVIDENCE_CONTRADICTS_MALE_HEALTH_SENSITIVE_MAPPING")

    if has_home_or_electronics_evidence and group == "MALE_HEALTH_SENSITIVE" and not has_male_health_title:
        reasons.append("HOME_OR_ELECTRONICS_EVIDENCE_CONTRADICTS_MALE_HEALTH_SENSITIVE_MAPPING")

    if confidence == "HIGH" and profile.get("taxonomy_conflict"):
        reasons.append("HIGH_CONFIDENCE_WITH_TAXONOMY_CONFLICT")

    if confidence == "HIGH" and group == "UNKNOWN_REVIEW_REQUIRED":
        reasons.append("HIGH_CONFIDENCE_WITH_UNKNOWN_GROUP")

    if has_beauty_evidence and "baby wipes" not in title and family == "BABY_WIPES":
        reasons.append("BEAUTY_EVIDENCE_CONTRADICTS_BABY_WIPES_FAMILY")

    if _contains_any(taxonomy, ("beauty", "fragrance")) and group == "HOUSEHOLD_CARE":
        reasons.append("SOURCE_TAXONOMY_BEAUTY_CONTRADICTS_HOUSEHOLD_GROUP")

    if _contains_any(taxonomy, ("fashion", "womenswear", "muslim fashion")) and group == "MALE_HEALTH_SENSITIVE":
        reasons.append("SOURCE_TAXONOMY_FASHION_CONTRADICTS_MALE_HEALTH_SENSITIVE_GROUP")

    if _contains_any(taxonomy, ("electronics", "household appliances", "kitchenware")) and group == "MALE_HEALTH_SENSITIVE":
        reasons.append("SOURCE_TAXONOMY_ELECTRONICS_OR_KITCHENWARE_CONTRADICTS_MALE_HEALTH_SENSITIVE_GROUP")

    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    return deduped


def build_all_product_mapping_audit(
    raw_products: list[dict[str, Any]],
    resolved_profiles: list[dict[str, Any]] | None = None,
    *,
    sample_limit: int = 20,
) -> dict[str, Any]:
    profiles = resolved_profiles or [resolve_product_intelligence_profile(product) for product in raw_products]

    source_distribution = _dist([str(product.get("source") or "UNKNOWN") for product in raw_products])
    image_readiness_distribution = _dist(
        [str(resolve_image_readiness(product).get("image_readiness_status") or "UNKNOWN") for product in raw_products]
    )
    image_analysis_status_distribution = _dist(
        [str(profile.get("image_analysis", {}).get("status") or "UNKNOWN") for profile in profiles]
    )
    group_distribution = _dist([str(profile.get("group") or "UNKNOWN") for profile in profiles])
    sub_group_distribution = _dist([str(profile.get("sub_group") or "UNKNOWN") for profile in profiles])
    type_of_product_distribution = _dist(
        [str(profile.get("type_of_product") or "UNKNOWN") for profile in profiles]
    )
    bosmax_family_distribution = _dist(
        [str(profile.get("bosmax_product_family") or "UNKNOWN") for profile in profiles]
    )
    copy_route_distribution = _dist([str(profile.get("copy_route") or "UNKNOWN") for profile in profiles])
    claim_gate_distribution = _dist([str(profile.get("claim_gate") or "UNKNOWN") for profile in profiles])
    intelligence_confidence_distribution = _dist(
        [str(profile.get("confidence") or "UNKNOWN") for profile in profiles]
    )

    examples: list[dict[str, Any]] = []
    suspicious_high_confidence_count = 0
    for raw_product, profile in zip(raw_products, profiles):
        reasons = _reasons_for_product(raw_product, profile)
        if not reasons:
            continue

        if str(profile.get("confidence") or "") == "HIGH":
            suspicious_high_confidence_count += 1

        examples.append(
            AllProductMappingAuditExample(
                product_id=str(raw_product.get("id") or profile.get("product_id") or ""),
                title=str(
                    raw_product.get("raw_product_title")
                    or raw_product.get("product_display_name")
                    or raw_product.get("product_short_name")
                    or profile.get("normalized_title")
                    or ""
                ),
                source_category=raw_product.get("category"),
                source_subcategory=raw_product.get("subcategory"),
                source_type=raw_product.get("type"),
                bosmax_group=str(profile.get("group") or "UNKNOWN"),
                bosmax_family=str(profile.get("bosmax_product_family") or "UNKNOWN"),
                confidence=str(profile.get("confidence") or "UNKNOWN"),
                copy_route=str(profile.get("copy_route") or "UNKNOWN"),
                claim_gate=str(profile.get("claim_gate") or "UNKNOWN"),
                reason=" | ".join(reasons),
            ).model_dump()
        )

    examples.sort(
        key=lambda example: (
            0 if example["confidence"] == "HIGH" else 1,
            example["bosmax_group"] == "UNKNOWN_REVIEW_REQUIRED",
            example["title"],
        )
    )

    payload = AllProductMappingAuditResponse(
        total_products=len(raw_products),
        source_distribution=source_distribution,
        image_readiness_distribution=image_readiness_distribution,
        image_analysis_status_distribution=image_analysis_status_distribution,
        group_distribution=group_distribution,
        sub_group_distribution=sub_group_distribution,
        type_of_product_distribution=type_of_product_distribution,
        bosmax_family_distribution=bosmax_family_distribution,
        copy_route_distribution=copy_route_distribution,
        claim_gate_distribution=claim_gate_distribution,
        intelligence_confidence_distribution=intelligence_confidence_distribution,
        taxonomy_conflict_count=sum(1 for profile in profiles if profile.get("taxonomy_conflict")),
        needs_review_count=sum(
            1 for profile in profiles if str(profile.get("intelligence_status") or "") == "NEEDS_REVIEW"
        ),
        unknown_review_required_count=sum(
            1
            for profile in profiles
            if str(profile.get("group") or "") == "UNKNOWN_REVIEW_REQUIRED"
            or str(profile.get("bosmax_product_family") or "") == "UNKNOWN_REVIEW_REQUIRED"
        ),
        low_confidence_count=sum(1 for profile in profiles if str(profile.get("confidence") or "") == "LOW"),
        suspicious_high_confidence_count=suspicious_high_confidence_count,
        source_taxonomy_contradiction_count=sum(
            1 for profile in profiles if bool(profile.get("taxonomy_conflict"))
        ),
        image_missing_count=sum(
            1 for profile in profiles if str(profile.get("image_analysis", {}).get("status") or "") == "IMAGE_MISSING"
        ),
        semantic_unavailable_count=sum(
            1
            for profile in profiles
            if str(profile.get("image_analysis", {}).get("status") or "") in SEMANTIC_UNAVAILABLE_STATUSES
        ),
        missing_sales_metrics_count=sum(
            1
            for profile in profiles
            if str(profile.get("sales_metrics", {}).get("source_status") or "") == "NOT_FOUND"
        ),
        examples=examples[:sample_limit],
    )
    return payload.model_dump()


async def get_all_product_mapping_audit(*, sample_limit: int = 20) -> dict[str, Any]:
    raw_products = await crud.list_products(limit=10000, include_archived=False)
    return build_all_product_mapping_audit(raw_products, sample_limit=sample_limit)
