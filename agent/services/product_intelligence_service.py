from __future__ import annotations

import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from agent.config import BASE_DIR, OPERATOR_PACK_DIR
from agent.db import crud
from agent.models.product_intelligence import (
    ProductIntelligenceBackfillPreviewResponse,
    ProductIntelligenceImageAnalysis,
    ProductIntelligenceProfile,
    ProductIntelligenceResolveRequest,
    ProductIntelligenceSalesMetrics,
    ProductIntelligenceSummaryResponse,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_mapping import normalize_mapping_text


REVIEW_CLAIM_TOKENS = {
    "antibakteria",
    "antibaktiria",
    "antibacterial",
    "anti bacterial",
    "antibacteria",
    "whitening",
    "white",
    "mencerahkan",
    "brightening",
    "anti aging",
    "anti-aging",
    "anti jerawat",
    "jerawat",
    "acne",
    "eczema",
    "resdung",
    "supplement",
    "supplements",
    "vitamin",
    "capsule",
    "capsules",
    "detox",
    "slimming",
    "kurus",
    "fat burner",
    "weight loss",
    "pain relief",
    "relief",
    "wellness",
    "immune",
    "hair growth",
    "growth",
    "anti gugur",
    "gugur",
    "medical",
    "health",
}
BLOCKED_CLAIM_TOKENS = {
    "cure",
    "cures",
    "menyembuhkan",
    "merawat",
}


FAMILY_PROFILES: dict[str, dict[str, str]] = {
    "LAUNDRY_DETERGENT_LIQUID_REFILL": {
        "group": "LAUNDRY_CARE",
        "sub_group": "LAUNDRY_CARE",
        "type_of_product": "LIQUID_LAUNDRY_DETERGENT",
        "package_form": "bottle_or_refill_pack",
        "physical_state": "liquid",
        "product_scale_class": "liquid_bottle_or_refill_pack",
        "handling_profile": "stable bottle/refill grip, cap/nozzle/label visibility, pour-angle demonstration",
        "scene_profile": "laundry_routine_utility_demo",
        "camera_profile": "label_forward_pour_ready_ugc",
        "copy_route": "DIRECT",
        "copy_formula": "UTILITY_DEMO",
    },
    "FABRIC_SOFTENER_LIQUID": {
        "group": "LAUNDRY_CARE",
        "sub_group": "LAUNDRY_CARE",
        "type_of_product": "LIQUID_FABRIC_SOFTENER",
        "package_form": "bottle_or_refill_pack",
        "physical_state": "liquid",
        "product_scale_class": "liquid_bottle_or_refill_pack",
        "handling_profile": "stable bottle/refill grip, cap/nozzle/label visibility, pour-angle demonstration",
        "scene_profile": "laundry_routine_utility_demo",
        "camera_profile": "label_forward_pour_ready_ugc",
        "copy_route": "DIRECT",
        "copy_formula": "SOFTNESS_ROUTINE",
    },
    "HOUSEHOLD_CLEANER_GENERAL": {
        "group": "HOUSEHOLD_CARE",
        "sub_group": "HOUSEHOLD_CARE",
        "type_of_product": "HOUSEHOLD_CLEANER",
        "package_form": "bottle_or_refill_pack",
        "physical_state": "liquid",
        "product_scale_class": "utility_container",
        "handling_profile": "grip_trigger_or_cap_label_visibility",
        "scene_profile": "household_cleaning_demo",
        "camera_profile": "utility_closeup_function_demo",
        "copy_route": "DIRECT",
        "copy_formula": "UTILITY_DEMO",
    },
    "HOUSEHOLD_STORAGE_ORGANIZER": {
        "group": "HOME_ORGANIZATION",
        "sub_group": "STORAGE_ORGANIZER",
        "type_of_product": "HOME_STORAGE_ORGANIZER",
        "package_form": "rigid_container",
        "physical_state": "solid",
        "product_scale_class": "medium_rigid_object",
        "handling_profile": "two_hand_open_close_shape_visibility",
        "scene_profile": "organization_before_after_demo",
        "camera_profile": "countertop_reveal_stackability_demo",
        "copy_route": "DIRECT",
        "copy_formula": "ORGANIZATION_UTILITY",
    },
    "HOME_TEXTILE": {
        "group": "HOUSEHOLD_CARE",
        "sub_group": "HOME_TEXTILE",
        "type_of_product": "HOME_TEXTILE",
        "package_form": "folded_textile",
        "physical_state": "textile",
        "product_scale_class": "large_soft_good",
        "handling_profile": "spread_fold_drape_texture_visibility",
        "scene_profile": "home_textile_texture_demo",
        "camera_profile": "texture_closeup_with_broad_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "TEXTURE_COMFORT",
    },
    "APPAREL_SLEEPWEAR": {
        "group": "FASHION_AND_APPAREL",
        "sub_group": "SLEEPWEAR_AND_LOUNGEWEAR",
        "type_of_product": "SLEEPWEAR",
        "package_form": "garment",
        "physical_state": "textile",
        "product_scale_class": "wearable_garment",
        "handling_profile": "drape_seam_shoulder_hanger_visibility",
        "scene_profile": "relaxed_homewear_demo",
        "camera_profile": "fabric_fall_and_fit_demo",
        "copy_route": "DIRECT",
        "copy_formula": "COMFORT_STYLE",
    },
    "fashion_modestwear": {
        "group": "FASHION_AND_APPAREL",
        "sub_group": "MODESTWEAR",
        "type_of_product": "MODESTWEAR",
        "package_form": "garment",
        "physical_state": "textile",
        "product_scale_class": "wearable_garment",
        "handling_profile": "drape_coverage_edge_visibility",
        "scene_profile": "modestwear_styling_demo",
        "camera_profile": "coverage_and_texture_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "MODEST_STYLE",
    },
    "fashion_sportswear": {
        "group": "FASHION_AND_APPAREL",
        "sub_group": "SPORTSWEAR",
        "type_of_product": "SPORTSWEAR",
        "package_form": "garment",
        "physical_state": "textile",
        "product_scale_class": "wearable_garment",
        "handling_profile": "fit_seam_texture_visibility",
        "scene_profile": "activewear_styling_demo",
        "camera_profile": "fit_and_texture_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "FIT_STYLE",
    },
    "fashion_apparel": {
        "group": "FASHION_AND_APPAREL",
        "sub_group": "GENERAL_APPAREL",
        "type_of_product": "APPAREL",
        "package_form": "garment",
        "physical_state": "textile",
        "product_scale_class": "wearable_garment",
        "handling_profile": "drape_fold_seam_visibility",
        "scene_profile": "fashion_styling_demo",
        "camera_profile": "fit_and_texture_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "STYLE_DIRECT",
    },
    "BEAUTY_PERSONAL_CARE": {
        "group": "BEAUTY_AND_PERSONAL_CARE",
        "sub_group": "PERSONAL_CARE",
        "type_of_product": "BEAUTY_PERSONAL_CARE_PRODUCT",
        "package_form": "small_bottle_tube_or_compact",
        "physical_state": "liquid_or_semi_liquid",
        "product_scale_class": "small_handheld",
        "handling_profile": "small_bottle_cap_label_closeup_visibility",
        "scene_profile": "beauty_routine_demo",
        "camera_profile": "closeup_handheld_detail_demo",
        "copy_route": "DIRECT",
        "copy_formula": "ROUTINE_BEAUTY",
    },
    "beauty_fragrance": {
        "group": "BEAUTY_AND_PERSONAL_CARE",
        "sub_group": "FRAGRANCE",
        "type_of_product": "FRAGRANCE",
        "package_form": "small_bottle_or_mist",
        "physical_state": "liquid",
        "product_scale_class": "small_handheld",
        "handling_profile": "small_bottle_nozzle_label_visibility",
        "scene_profile": "fragrance_closeup_demo",
        "camera_profile": "reflective_bottle_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "FRESHNESS_DIRECT",
    },
    "ACCESSORY_SMALL_ITEM": {
        "group": "ACCESSORIES_AND_SMALL_ITEMS",
        "sub_group": "SMALL_ACCESSORY",
        "type_of_product": "ACCESSORY",
        "package_form": "small_rigid_item",
        "physical_state": "solid",
        "product_scale_class": "small_fingertip",
        "handling_profile": "pinch_edge_detail_visibility",
        "scene_profile": "styling_closeup_demo",
        "camera_profile": "macro_detail_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "DETAIL_STYLE",
    },
    "BABY_DIAPER": {
        "group": "BABY_AND_MATERNITY",
        "sub_group": "BABY_DIAPERING",
        "type_of_product": "BABY_DIAPER",
        "package_form": "soft_pack",
        "physical_state": "soft_packaged_goods",
        "product_scale_class": "medium_soft_pack",
        "handling_profile": "front_pack_support_label_visibility",
        "scene_profile": "babycare_trust_demo",
        "camera_profile": "front_pack_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "TRUST_BABYCARE",
    },
    "BABY_WIPES": {
        "group": "BABY_AND_MATERNITY",
        "sub_group": "BABY_HYGIENE",
        "type_of_product": "BABY_WIPES",
        "package_form": "soft_pack",
        "physical_state": "soft_packaged_goods",
        "product_scale_class": "small_soft_pack",
        "handling_profile": "front_pack_seal_visibility",
        "scene_profile": "babycare_trust_demo",
        "camera_profile": "front_pack_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "TRUST_BABYCARE",
    },
    "food_packaged": {
        "group": "FOOD_AND_BEVERAGE",
        "sub_group": "PACKAGED_FOOD",
        "type_of_product": "PACKAGED_FOOD_OR_SAUCE",
        "package_form": "jar_sachet_or_food_pack",
        "physical_state": "solid_or_sauce",
        "product_scale_class": "small_food_pack",
        "handling_profile": "sealed_pack_front_label_visibility",
        "scene_profile": "food_serving_demo",
        "camera_profile": "appetite_led_pack_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "TASTE_CONVENIENCE",
    },
    "stationery_paper": {
        "group": "STATIONERY_AND_GIFTING",
        "sub_group": "PAPER_PACKET",
        "type_of_product": "PAPER_PACKET_OR_ENVELOPE",
        "package_form": "flat_packet",
        "physical_state": "paper",
        "product_scale_class": "small_flat_packet",
        "handling_profile": "flat_packet_pinch_edge_visibility",
        "scene_profile": "flatlay_or_fanout_demo",
        "camera_profile": "topdown_or_macro_paper_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "DETAIL_GIFTING",
    },
    "electronics_wearable": {
        "group": "ELECTRONICS_AND_GADGETS",
        "sub_group": "WEARABLE_DEVICE",
        "type_of_product": "WEARABLE_ELECTRONIC",
        "package_form": "small_rigid_device",
        "physical_state": "solid",
        "product_scale_class": "small_handheld",
        "handling_profile": "device_screen_port_visibility",
        "scene_profile": "tech_closeup_demo",
        "camera_profile": "feature_detail_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "FEATURE_UTILITY",
    },
    "HEALTH_SUPPLEMENT": {
        "group": "HEALTH_AND_WELLNESS",
        "sub_group": "SUPPLEMENT",
        "type_of_product": "SUPPLEMENT_BOTTLE",
        "package_form": "small_bottle",
        "physical_state": "solid_capsule_or_powder",
        "product_scale_class": "small_handheld",
        "handling_profile": "bottle_cap_label_visibility",
        "scene_profile": "wellness_routine_demo",
        "camera_profile": "trust_led_closeup",
        "copy_route": "REVIEW_REQUIRED",
        "copy_formula": "WELLNESS_REVIEW",
    },
    "MALE_HEALTH_SENSITIVE": {
        "group": "MALE_HEALTH_SENSITIVE",
        "sub_group": "MALE_HEALTH_SENSITIVE",
        "type_of_product": "SENSITIVE_MALE_HEALTH_PRODUCT",
        "package_form": "small_bottle_or_box",
        "physical_state": "solid_or_liquid_container",
        "product_scale_class": "small_handheld",
        "handling_profile": "bottle_box_label_visibility",
        "scene_profile": "literal_product_demo_review_required",
        "camera_profile": "literal_product_closeup_review_required",
        "copy_route": "STEALTH",
        "copy_formula": "STEALTH_DIALOGUE_SAFE",
    },
    "PET_CARE_GENERAL": {
        "group": "PET_CARE",
        "sub_group": "PET_CARE",
        "type_of_product": "PET_CARE_PRODUCT",
        "package_form": "bag_pack_or_can",
        "physical_state": "solid_or_kibble",
        "product_scale_class": "small_to_medium_pack",
        "handling_profile": "front_pack_label_visibility",
        "scene_profile": "petcare_product_demo",
        "camera_profile": "pack_reveal_and_detail",
        "copy_route": "DIRECT",
        "copy_formula": "PETCARE_DIRECT",
    },
    "AUTO_TOOL_GENERAL": {
        "group": "AUTO_AND_TOOLS",
        "sub_group": "AUTO_AND_TOOLS",
        "type_of_product": "AUTO_OR_TOOL_ITEM",
        "package_form": "rigid_tool_or_pack",
        "physical_state": "solid",
        "product_scale_class": "small_to_medium_tool",
        "handling_profile": "function_grip_visibility",
        "scene_profile": "utility_tool_demo",
        "camera_profile": "feature_function_reveal",
        "copy_route": "DIRECT",
        "copy_formula": "UTILITY_DIRECT",
    },
    "REAL_ESTATE_OR_SERVICE": {
        "group": "REAL_ESTATE_OR_SERVICE",
        "sub_group": "REAL_ESTATE_OR_SERVICE",
        "type_of_product": "SERVICE_OR_INTANGIBLE",
        "package_form": "not_applicable",
        "physical_state": "not_applicable",
        "product_scale_class": "not_applicable",
        "handling_profile": "review_required",
        "scene_profile": "review_required",
        "camera_profile": "review_required",
        "copy_route": "REVIEW_REQUIRED",
        "copy_formula": "REVIEW_REQUIRED",
    },
    "UNKNOWN_REVIEW_REQUIRED": {
        "group": "UNKNOWN_REVIEW_REQUIRED",
        "sub_group": "UNKNOWN_REVIEW_REQUIRED",
        "type_of_product": "UNKNOWN_REVIEW_REQUIRED",
        "package_form": "unknown",
        "physical_state": "unknown",
        "product_scale_class": "unknown",
        "handling_profile": "review_required",
        "scene_profile": "review_required",
        "camera_profile": "review_required",
        "copy_route": "REVIEW_REQUIRED",
        "copy_formula": "REVIEW_REQUIRED",
    },
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_key(value: Any) -> str:
    return normalize_mapping_text(value)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        normalized = _normalize_text(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _joined_title_text(product: dict[str, Any]) -> str:
    return " ".join(
        _normalize_key(product.get(field))
        for field in (
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "product_type",
            "brand",
        )
        if product.get(field)
    )


def _joined_product_text(product: dict[str, Any]) -> str:
    return " ".join(
        _normalize_key(product.get(field))
        for field in (
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "category",
            "subcategory",
            "type",
            "product_type",
            "brand",
        )
        if product.get(field)
    )


def _contains_any(haystack: str, keywords: list[str]) -> bool:
    return any(_normalize_key(keyword) in haystack for keyword in keywords)


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = _normalize_text(value)
        if text:
            return text
    return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = _normalize_text(value).replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _coerce_source(value: Any) -> str:
    source = _normalize_text(value).upper()
    if source in {"FASTMOSS", "MANUAL", "TIKTOKSHOP", "TEST"}:
        return source
    if not source:
        return "UNKNOWN"
    return source


def _product_names(product: dict[str, Any]) -> list[str]:
    return _unique(
        [
            product.get("raw_product_title"),
            product.get("product_display_name"),
            product.get("product_short_name"),
        ]
    )


def _find_sheet_header(ws) -> list[str]:
    for row in ws.iter_rows(values_only=True, max_row=10):
        values = [str(value).strip() if value is not None else "" for value in row]
        lowered = {value.lower() for value in values if value}
        if (
            "product name" in lowered
            or "product title" in lowered
            or "rank" in lowered
        ):
            return values
    return []


def _row_mapping(headers: list[str], values: list[Any]) -> dict[str, Any]:
    return {
        headers[index]: values[index]
        for index in range(min(len(headers), len(values)))
        if headers[index]
    }


def _iter_sales_workbook_records() -> list[dict[str, Any]]:
    path = OPERATOR_PACK_DIR / "FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx"
    if not path.exists():
        return []

    configs = [
        {
            "sheet": "Product Sales Rank",
            "name_fields": ["Product Name"],
            "shop_fields": ["Shop Name"],
            "source_fields": ["FastMoss Product Detail", "FastMoss Shop Detail"],
            "tiktok_fields": ["TikTok Product Detail"],
            "sold_fields": ["Total Units Sold", "Orders", "Shop Total Units Sold"],
        },
        {
            "sheet": "Most Promoted Products",
            "name_fields": ["Product Name"],
            "shop_fields": ["Shop Name"],
            "source_fields": ["FastMoss Product Detail", "FastMoss Shop Detail"],
            "tiktok_fields": ["TikTok Product Detail"],
            "sold_fields": ["Total Units Sold", "Shop Units Sold"],
        },
        {
            "sheet": "Video Product List",
            "name_fields": ["Product Title"],
            "shop_fields": [],
            "source_fields": ["FastMoss Product Detail Page Link"],
            "tiktok_fields": ["TikTok Product Link"],
            "sold_fields": ["Video Total Units Sold", "Video Units Sold"],
        },
        {
            "sheet": "Product Search Data",
            "name_fields": ["Product Name"],
            "shop_fields": ["Store Name"],
            "source_fields": ["FastMoss", "FastMoss Shop"],
            "tiktok_fields": ["TikTok"],
            "sold_fields": ["Total Sales Volume", "7-Day Sales Volume"],
        },
        {
            "sheet": "New Products Ranking",
            "name_fields": ["Product Name"],
            "shop_fields": ["Shop"],
            "source_fields": [],
            "tiktok_fields": [],
            "sold_fields": ["Units Sold", "Shop Units Sold"],
        },
        {
            "sheet": "Copywriting_Product_Map",
            "name_fields": ["Product Name"],
            "shop_fields": ["Shop Name"],
            "source_fields": [],
            "tiktok_fields": [],
            "sold_fields": ["Total Units Sold", "Orders"],
        },
    ]

    workbook = load_workbook(path, read_only=True, data_only=True)
    rows: list[dict[str, Any]] = []
    for config in configs:
        if config["sheet"] not in workbook.sheetnames:
            continue
        ws = workbook[config["sheet"]]
        headers = _find_sheet_header(ws)
        if not headers:
            continue
        for row in ws.iter_rows(values_only=True):
            values = list(row)
            if not any(value is not None and str(value).strip() for value in values):
                continue
            if headers and values[: len(headers)] == headers[: len(values[: len(headers)])]:
                continue
            data = _row_mapping(headers, values)
            names = _unique([data.get(field) for field in config["name_fields"]])
            if not names:
                continue
            shop_names = _unique([data.get(field) for field in config["shop_fields"]])
            sold_values = [
                value
                for field in config["sold_fields"]
                if (value := _to_int(data.get(field))) is not None
            ]
            source_urls = _unique([data.get(field) for field in config["source_fields"]])
            tiktok_urls = _unique([data.get(field) for field in config["tiktok_fields"]])
            rows.append(
                {
                    "sheet": config["sheet"],
                    "names": names,
                    "shop_names": shop_names,
                    "sold_values": sold_values,
                    "source_urls": source_urls,
                    "tiktok_urls": tiktok_urls,
                }
            )
    return rows


@lru_cache(maxsize=1)
def _sales_metrics_index() -> dict[str, Any]:
    records = _iter_sales_workbook_records()
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_source_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tiktok_url: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for name in record["names"]:
            by_name[_normalize_key(name)].append(record)
        for url in record["source_urls"]:
            by_source_url[_normalize_text(url)].append(record)
        for url in record["tiktok_urls"]:
            by_tiktok_url[_normalize_text(url)].append(record)
    return {
        "records": records,
        "by_name": by_name,
        "by_source_url": by_source_url,
        "by_tiktok_url": by_tiktok_url,
    }


def _resolve_sales_metrics(product: dict[str, Any]) -> tuple[ProductIntelligenceSalesMetrics, list[str]]:
    index = _sales_metrics_index()
    matched: list[dict[str, Any]] = []
    provenance: list[str] = []

    source_url = _normalize_text(product.get("source_url"))
    tiktok_url = _normalize_text(product.get("tiktok_product_url"))
    if source_url and source_url in index["by_source_url"]:
        matched.extend(index["by_source_url"][source_url])
        provenance.append("sales_metrics:matched_source_url")
    if tiktok_url and tiktok_url in index["by_tiktok_url"]:
        matched.extend(index["by_tiktok_url"][tiktok_url])
        provenance.append("sales_metrics:matched_tiktok_product_url")

    if not matched:
        for name in _product_names(product):
            normalized = _normalize_key(name)
            if normalized in index["by_name"]:
                matched.extend(index["by_name"][normalized])
                provenance.append("sales_metrics:matched_exact_name")
                break

    if not matched:
        raw_names = [name for name in _product_names(product) if len(_normalize_key(name)) >= 10]
        for candidate in raw_names:
            normalized = _normalize_key(candidate)
            fuzzy = [
                record
                for record in index["records"]
                if any(
                    normalized in _normalize_key(record_name)
                    or _normalize_key(record_name) in normalized
                    for record_name in record["names"]
                )
            ]
            if len(fuzzy) == 1:
                matched.extend(fuzzy)
                provenance.append("sales_metrics:matched_unique_fuzzy_name")
                break

    if not matched:
        return (
            ProductIntelligenceSalesMetrics(
                sold_count=None,
                shop_count=None,
                shop_names=[],
                source_status="NOT_FOUND",
            ),
            provenance,
        )

    unique_records: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, tuple[str, ...]]] = set()
    for record in matched:
        record_key = (
            record["sheet"],
            tuple(sorted(_normalize_key(name) for name in record["names"])),
        )
        if record_key in seen_keys:
            continue
        seen_keys.add(record_key)
        unique_records.append(record)

    sold_candidates = [
        value
        for record in unique_records
        for value in record["sold_values"]
        if value is not None
    ]
    shop_names = _unique(
        shop_name
        for record in unique_records
        for shop_name in record["shop_names"]
    )
    sheets = sorted({record["sheet"] for record in unique_records})
    if sheets:
        provenance.append("sales_metrics:sheets=" + ",".join(sheets))
    return (
        ProductIntelligenceSalesMetrics(
            sold_count=max(sold_candidates) if sold_candidates else None,
            shop_count=len(shop_names) if shop_names else None,
            shop_names=shop_names,
            source_status="FOUND",
        ),
        provenance,
    )


def _resolve_image_analysis(product: dict[str, Any]) -> ProductIntelligenceImageAnalysis:
    image_url = _normalize_text(product.get("image_url")) or None
    local_image_path = _normalize_text(product.get("local_image_path")) or None
    metadata: dict[str, Any] = {}
    if local_image_path:
        candidate = Path(local_image_path)
        if not candidate.is_absolute():
            candidate = BASE_DIR / candidate
        metadata["local_file_exists"] = candidate.exists()
        if candidate.exists():
            metadata["local_file_size_bytes"] = candidate.stat().st_size

    if not image_url and not local_image_path:
        return ProductIntelligenceImageAnalysis(
            status="NOT_AVAILABLE",
            image_url=None,
            local_image_path=None,
            detected_package=None,
            detected_text=None,
            confidence="NOT_VERIFIED",
            metadata=metadata,
        )
    return ProductIntelligenceImageAnalysis(
        status="NOT_ANALYZED",
        image_url=image_url,
        local_image_path=local_image_path,
        detected_package=None,
        detected_text=None,
        confidence="NOT_VERIFIED",
        metadata=metadata,
    )


def _resolve_claim_gate(
    product: dict[str, Any],
    family: str,
    copy_route: str,
) -> tuple[str, list[str], list[str]]:
    haystack = _joined_product_text(product)
    matched_review = sorted(
        {
            token
            for token in REVIEW_CLAIM_TOKENS
            if _normalize_key(token) in haystack
        }
    )
    matched_blocked = sorted(
        {
            token
            for token in BLOCKED_CLAIM_TOKENS
            if _normalize_key(token) in haystack
        }
    )
    warnings: list[str] = []
    if family == "MALE_HEALTH_SENSITIVE":
        if "male_health_sensitive" not in matched_review:
            matched_review.append("male_health_sensitive")
        warnings.append("claim_gate:male_health_sensitive")
        return "CLAIM_REVIEW_REQUIRED", matched_review, warnings
    if matched_blocked:
        warnings.append("claim_gate:blocked_tokens_present")
        return "CLAIM_BLOCKED", matched_review + matched_blocked, warnings
    if matched_review:
        if any(token in matched_review for token in ["antibakteria", "antibaktiria", "antibacterial", "anti bacterial", "antibacteria"]):
            if "antibacterial_claim" not in matched_review:
                matched_review.append("antibacterial_claim")
        warnings.append("claim_gate:review_tokens_present")
        return "CLAIM_REVIEW_REQUIRED", matched_review, warnings
    if copy_route in {"STEALTH", "REVIEW_REQUIRED"}:
        warnings.append("claim_gate:route_requires_review")
        return "CLAIM_REVIEW_REQUIRED", matched_review, warnings
    return "CLAIM_SAFE", [], warnings


def _resolve_family_from_title(product: dict[str, Any]) -> tuple[str | None, str | None]:
    haystack = _joined_title_text(product)
    if _contains_any(
        haystack,
        [
            "sabun dobi",
            "liquid laundry detergent",
            "laundry detergent",
            "detergen",
            "detergent refill",
            "pencuci baju",
            "isi ulang",
        ],
    ):
        return (
            "LAUNDRY_DETERGENT_LIQUID_REFILL",
            "title_evidence:laundry_detergent_keywords",
        )
    if _contains_any(
        haystack,
        ["softener", "fabric softener", "pelembut", "pewangi pakaian"],
    ):
        return ("FABRIC_SOFTENER_LIQUID", "title_evidence:fabric_softener_keywords")
    if _contains_any(
        haystack,
        ["male health", "lelaki", "suami isteri", "batin", "tahan lama", "kuat lelaki"],
    ):
        return ("MALE_HEALTH_SENSITIVE", "title_evidence:male_health_sensitive_keywords")
    if _contains_any(
        haystack,
        ["supplement", "capsule", "vitamin", "wellness supplement", "beauty supplement"],
    ):
        return ("HEALTH_SUPPLEMENT", "title_evidence:supplement_keywords")
    if _contains_any(
        haystack,
        ["organizer", "storage", "rak", "bekas simpan", "container set"],
    ):
        return ("HOUSEHOLD_STORAGE_ORGANIZER", "title_evidence:storage_keywords")
    if _contains_any(
        haystack,
        ["cleaner", "all purpose cleaner", "floor cleaner", "toilet cleaner", "sabun pencuci"],
    ):
        return ("HOUSEHOLD_CLEANER_GENERAL", "title_evidence:cleaner_keywords")
    if _contains_any(
        haystack,
        ["sleepwear", "loungewear", "nightdress", "baju tidur", "kelawar", "nightie"],
    ):
        return ("APPAREL_SLEEPWEAR", "title_evidence:sleepwear_keywords")
    if _contains_any(
        haystack,
        ["instant sarung", "sarung syria", "khimar", "telekung", "tudung labuh", "moscrepe"],
    ):
        return ("fashion_modestwear", "title_evidence:modestwear_keywords")
    if _contains_any(
        haystack,
        ["jersey", "jersi", "athleisure", "baju sukan", "quick dry"],
    ):
        return ("fashion_sportswear", "title_evidence:sportswear_keywords")
    if _contains_any(
        haystack,
        ["body spray", "perfume", "fragrance", "body mist", "mist"],
    ):
        return ("beauty_fragrance", "title_evidence:fragrance_keywords")
    if _contains_any(
        haystack,
        [
            "lip balm",
            "lip gloss",
            "lipstick",
            "serum",
            "cleanser",
            "moisturizer",
            "foundation",
            "concealer",
            "body wash",
            "soap",
            "skincare",
            "beauty",
        ],
    ):
        return ("BEAUTY_PERSONAL_CARE", "title_evidence:beauty_keywords")
    if _contains_any(
        haystack,
        ["envelope", "duit raya", "money packet", "angpow", "red packet", "sampul"],
    ):
        return ("stationery_paper", "title_evidence:paper_packet_keywords")
    if _contains_any(
        haystack,
        ["towel", "tuala", "blanket", "comforter", "selimut", "bedsheet", "cadar", "curtain", "pillow", "mat-rug", "rug", "mat", "bedding"],
    ):
        return ("HOME_TEXTILE", "title_evidence:home_textile_keywords")
    if _contains_any(haystack, ["baby wipes", "wet wipes", "wet tissue", "tisu basah"]):
        return ("BABY_WIPES", "title_evidence:baby_wipes_keywords")
    if _contains_any(haystack, ["diaper", "lampin", "pull ups", "pull-ups", "baby diaper"]):
        return ("BABY_DIAPER", "title_evidence:baby_diaper_keywords")
    if _contains_any(haystack, ["cat food", "cat treat", "pet", "kucing"]):
        return ("PET_CARE_GENERAL", "title_evidence:petcare_keywords")
    if _contains_any(haystack, ["sauce", "sambal", "popcorn", "chocolate", "biscuits", "cookies", "food"]):
        return ("food_packaged", "title_evidence:food_keywords")
    if _contains_any(haystack, ["smartwatch", "wearable", "charger", "adapter", "cable"]):
        return ("electronics_wearable", "title_evidence:electronics_keywords")
    if _contains_any(haystack, ["brooch", "earring", "pin", "charm", "pendant", "clip", "accessory"]):
        return ("ACCESSORY_SMALL_ITEM", "title_evidence:accessory_keywords")
    if _contains_any(haystack, ["tool", "hardware", "automotive", "motorcycle", "car care"]):
        return ("AUTO_TOOL_GENERAL", "title_evidence:auto_tool_keywords")
    if _contains_any(haystack, ["service", "consultation", "homestay", "property", "rumah untuk dijual"]):
        return ("REAL_ESTATE_OR_SERVICE", "title_evidence:service_keywords")
    return None, None


def _resolve_family_from_taxonomy(product: dict[str, Any]) -> tuple[str, str]:
    category = _normalize_key(product.get("category"))
    subcategory = _normalize_key(product.get("subcategory"))
    type_name = _normalize_key(product.get("type"))
    taxonomy = " ".join(part for part in [category, subcategory, type_name] if part)

    if any(token in taxonomy for token in ["laundry detergent", "household cleaners", "home care supplies"]):
        return "LAUNDRY_DETERGENT_LIQUID_REFILL", "taxonomy_fallback:laundry_or_cleaner"
    if any(token in taxonomy for token in ["beauty and personal care", "cosmetics", "fragrance", "bath and body"]):
        if "fragrance" in taxonomy:
            return "beauty_fragrance", "taxonomy_fallback:fragrance"
        return "BEAUTY_PERSONAL_CARE", "taxonomy_fallback:beauty_personal_care"
    if any(token in taxonomy for token in ["womenswear and underwear", "fashion", "muslim fashion", "menswear and underwear"]):
        return "fashion_apparel", "taxonomy_fallback:fashion_apparel"
    if any(token in taxonomy for token in ["textiles and soft furnishings", "bedding", "carpet", "curtains"]):
        return "HOME_TEXTILE", "taxonomy_fallback:home_textile"
    if any(token in taxonomy for token in ["kitchen storage", "food container", "home organization"]):
        return "HOUSEHOLD_STORAGE_ORGANIZER", "taxonomy_fallback:storage"
    if any(token in taxonomy for token in ["stationery", "envelope"]):
        return "stationery_paper", "taxonomy_fallback:stationery"
    if any(token in taxonomy for token in ["baby & maternity", "baby care", "diapers"]):
        if "wipes" in taxonomy:
            return "BABY_WIPES", "taxonomy_fallback:baby_wipes"
        return "BABY_DIAPER", "taxonomy_fallback:baby_diaper"
    if any(token in taxonomy for token in ["food & beverage", "food & beverages", "kitchenware"]):
        return "food_packaged", "taxonomy_fallback:food"
    if any(token in taxonomy for token in ["health", "supplements"]):
        return "HEALTH_SUPPLEMENT", "taxonomy_fallback:health_supplement"
    if any(token in taxonomy for token in ["pet supplies"]):
        return "PET_CARE_GENERAL", "taxonomy_fallback:petcare"
    if any(token in taxonomy for token in ["tools & hardware", "automotive & motorcycle", "home improvement"]):
        return "AUTO_TOOL_GENERAL", "taxonomy_fallback:auto_tools"
    if any(token in taxonomy for token in ["phones & electronics", "electronics", "computers & office equipment", "household appliances"]):
        return "electronics_wearable", "taxonomy_fallback:electronics"
    return "UNKNOWN_REVIEW_REQUIRED", "taxonomy_fallback:unknown"


def _resolve_family(product: dict[str, Any]) -> tuple[str, str, bool, str | None]:
    title_family, title_reason = _resolve_family_from_title(product)
    family_context = derive_bosmax_product_family(product)

    if title_family:
        family = title_family
        reason = title_reason or "title_evidence"
    elif family_context["bosmax_product_family"] != "GENERIC_UNCLASSIFIED":
        family = str(family_context["bosmax_product_family"])
        reason = "family_resolver:" + str(family_context["bosmax_product_family_reason"])
    else:
        family, reason = _resolve_family_from_taxonomy(product)

    taxonomy_conflict = bool(family_context["bosmax_source_taxonomy_conflict"])
    conflict_reason = (
        str(family_context["bosmax_source_taxonomy_conflict_reason"]).strip() or None
    )
    category = _normalize_key(product.get("category"))
    if family == "LAUNDRY_DETERGENT_LIQUID_REFILL" and "baby" in category:
        taxonomy_conflict = True
        conflict_reason = (
            conflict_reason
            or "Title evidence indicates laundry detergent, but source taxonomy is under baby-care lanes."
        )
    if family == "HOUSEHOLD_STORAGE_ORGANIZER" and _contains_any(
        _joined_title_text(product), ["sabun dobi", "detergent", "laundry"]
    ):
        taxonomy_conflict = True
        conflict_reason = conflict_reason or "Storage taxonomy conflicts with laundry detergent title evidence."

    return family, reason, taxonomy_conflict, conflict_reason


def _profile_for_family(family: str) -> dict[str, str]:
    return dict(FAMILY_PROFILES.get(family) or FAMILY_PROFILES["UNKNOWN_REVIEW_REQUIRED"])


def _resolve_confidence(
    reason: str,
    taxonomy_conflict: bool,
    family: str,
    source_taxonomy: dict[str, str | None],
) -> str:
    if family == "UNKNOWN_REVIEW_REQUIRED":
        return "LOW"
    if reason.startswith("title_evidence:"):
        return "MEDIUM" if taxonomy_conflict else "HIGH"
    if reason.startswith("family_resolver:"):
        return "MEDIUM" if taxonomy_conflict else "HIGH"
    if not any(source_taxonomy.values()):
        return "LOW"
    return "LOW" if taxonomy_conflict else "MEDIUM"


def _destination_readiness(
    *,
    copy_route: str,
    claim_gate: str,
    confidence: str,
    image_analysis_status: str,
) -> dict[str, str]:
    review_required = copy_route != "DIRECT" or claim_gate != "CLAIM_SAFE" or confidence == "LOW"
    text_to_video = "READY" if not review_required else "NEEDS_REVIEW"
    image_capable = image_analysis_status != "NOT_AVAILABLE"
    frames = "READY" if image_capable and not review_required else "NEEDS_REVIEW"
    ingredients = "READY" if image_capable and confidence in {"HIGH", "MEDIUM"} else "NEEDS_REVIEW"
    image = "READY" if not review_required else "NEEDS_REVIEW"
    return {
        "TEXT_TO_VIDEO": text_to_video,
        "FRAMES": frames,
        "INGREDIENTS": ingredients,
        "IMAGE": image,
    }


def resolve_product_intelligence_profile(product: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product)
    family, family_reason, taxonomy_conflict, taxonomy_conflict_reason = _resolve_family(payload)
    profile = _profile_for_family(family)
    source = _coerce_source(payload.get("source"))
    copy_route = profile["copy_route"]
    claim_gate, claim_tokens, claim_warnings = _resolve_claim_gate(payload, family, copy_route)
    image_analysis = _resolve_image_analysis(payload)
    sales_metrics, sales_provenance = _resolve_sales_metrics(payload)
    source_taxonomy = {
        "category": _first_non_empty(payload.get("category")),
        "subcategory": _first_non_empty(payload.get("subcategory")),
        "type": _first_non_empty(payload.get("type")),
    }
    confidence = _resolve_confidence(
        family_reason,
        taxonomy_conflict,
        family,
        source_taxonomy,
    )
    readiness = _destination_readiness(
        copy_route=copy_route,
        claim_gate=claim_gate,
        confidence=confidence,
        image_analysis_status=image_analysis.status,
    )

    warnings: list[str] = []
    provenance = [
        "resolver:product_intelligence_service",
        "evidence_priority:title_then_taxonomy_then_workbook_then_fallback",
        f"family:{family}",
        family_reason,
    ]
    if taxonomy_conflict:
        warnings.append("TAXONOMY_CONFLICT")
        provenance.append("taxonomy_conflict:source_taxonomy_overridden")
    warnings.extend(
        warning
        for warning in claim_warnings
        if warning not in warnings
    )
    if sales_metrics.source_status == "NOT_FOUND":
        warnings.append("SALES_METRICS_NOT_FOUND")
    else:
        provenance.extend(sales_provenance)
    if image_analysis.status == "NOT_ANALYZED":
        warnings.append("IMAGE_ANALYSIS_NOT_WIRED")
        provenance.append("image_analysis:metadata_only_no_semantic_vision")
    elif image_analysis.status == "NOT_AVAILABLE":
        warnings.append("IMAGE_NOT_AVAILABLE")
    if confidence == "LOW":
        warnings.append("INTELLIGENCE_LOW_CONFIDENCE")

    intelligence_status = "READY" if confidence in {"HIGH", "MEDIUM"} and family != "UNKNOWN_REVIEW_REQUIRED" else "NEEDS_REVIEW"
    if family == "UNKNOWN_REVIEW_REQUIRED":
        warnings.append("UNKNOWN_REVIEW_REQUIRED")

    return ProductIntelligenceProfile(
        product_id=_first_non_empty(payload.get("id"), payload.get("product_id")),
        source=source,
        normalized_title=_first_non_empty(
            payload.get("product_short_name"),
            payload.get("product_display_name"),
            payload.get("raw_product_title"),
        )
        or "",
        brand=_first_non_empty(payload.get("brand")),
        group=profile["group"],
        sub_group=profile["sub_group"],
        type_of_product=profile["type_of_product"],
        bosmax_product_family=family,
        package_form=profile["package_form"],
        physical_state=profile["physical_state"],
        product_scale_class=profile["product_scale_class"],
        handling_profile=profile["handling_profile"],
        scene_profile=profile["scene_profile"],
        camera_profile=profile["camera_profile"],
        copy_route=copy_route,
        claim_gate=claim_gate,
        claim_tokens=claim_tokens,
        copy_formula=profile["copy_formula"],
        destination_readiness=readiness,
        sales_metrics=sales_metrics,
        image_analysis=image_analysis,
        confidence=confidence,
        warnings=_unique(warnings),
        provenance=_unique(provenance),
        intelligence_status=intelligence_status,
        taxonomy_conflict=taxonomy_conflict,
        taxonomy_conflict_reason=taxonomy_conflict_reason,
        source_taxonomy=source_taxonomy,
    ).model_dump()


def inject_product_intelligence_fields(product: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product)
    payload["product_intelligence"] = profile
    payload["group"] = profile["group"]
    payload["sub_group"] = profile["sub_group"]
    payload["type_of_product"] = profile["type_of_product"]
    payload["bosmax_product_family"] = profile["bosmax_product_family"]
    payload["package_form"] = profile["package_form"]
    payload["physical_state"] = profile["physical_state"]
    payload["product_scale_class"] = profile["product_scale_class"]
    payload["handling_profile"] = profile["handling_profile"]
    payload["scene_profile"] = profile["scene_profile"]
    payload["camera_profile"] = profile["camera_profile"]
    payload["copy_route"] = profile["copy_route"]
    payload["claim_gate"] = profile["claim_gate"]
    payload["claim_tokens"] = profile["claim_tokens"]
    payload["copy_formula"] = profile["copy_formula"]
    payload["destination_readiness"] = profile["destination_readiness"]
    payload["sales_metrics"] = profile["sales_metrics"]
    payload["image_analysis"] = profile["image_analysis"]
    payload["intelligence_confidence"] = profile["confidence"]
    payload["intelligence_status"] = profile["intelligence_status"]
    payload["intelligence_warnings"] = profile["warnings"]
    payload["intelligence_provenance"] = profile["provenance"]
    payload["taxonomy_conflict"] = profile["taxonomy_conflict"]
    payload["taxonomy_conflict_reason"] = profile["taxonomy_conflict_reason"]
    payload["bosmax_source_taxonomy_conflict"] = profile["taxonomy_conflict"]
    payload["bosmax_source_taxonomy_conflict_reason"] = profile["taxonomy_conflict_reason"]
    payload["bosmax_product_family_reason"] = next(
        (
            entry
            for entry in profile["provenance"]
            if entry.startswith("title_evidence:")
            or entry.startswith("family_resolver:")
            or entry.startswith("taxonomy_fallback:")
        ),
        None,
    )
    payload["shop_count"] = profile["sales_metrics"]["shop_count"]
    payload["shop_names"] = profile["sales_metrics"]["shop_names"]
    payload["sold_count"] = profile["sales_metrics"]["sold_count"]
    payload["image_analysis_status"] = profile["image_analysis"]["status"]
    return payload


async def _load_profile_for_row(product: dict[str, Any]) -> dict[str, Any]:
    return resolve_product_intelligence_profile(product)


async def resolve_product_intelligence_request(
    request_input: ProductIntelligenceResolveRequest | dict[str, Any],
) -> dict[str, Any]:
    request = (
        request_input
        if isinstance(request_input, ProductIntelligenceResolveRequest)
        else ProductIntelligenceResolveRequest.model_validate(request_input)
    )
    if request.product_id:
        product = await crud.get_product(request.product_id)
        if not product:
            return {
                "status": "PRODUCT_NOT_FOUND",
                "product_id": request.product_id,
            }
        merged = dict(product)
        if request.product_payload:
            merged.update(request.product_payload)
        return resolve_product_intelligence_profile(merged)
    if request.product_payload:
        return resolve_product_intelligence_profile(dict(request.product_payload))
    return {
        "status": "PRODUCT_CONTEXT_REQUIRED",
        "warnings": ["PRODUCT_CONTEXT_REQUIRED"],
    }


async def get_product_intelligence_by_id(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        return {
            "status": "PRODUCT_NOT_FOUND",
            "product_id": product_id,
        }
    return resolve_product_intelligence_profile(product)


def _distribution(profiles: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = Counter(str(profile.get(key) or "UNKNOWN") for profile in profiles)
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


async def get_product_intelligence_summary() -> dict[str, Any]:
    products = await crud.list_products(limit=10000)
    profiles = [resolve_product_intelligence_profile(product) for product in products]
    products_by_source = Counter(_coerce_source(product.get("source")) for product in products)
    products_by_current_category = Counter(
        _first_non_empty(product.get("category")) or "__MISSING__"
        for product in products
    )
    products_by_current_type = Counter(
        _first_non_empty(product.get("type")) or "__MISSING__"
        for product in products
    )
    summary = ProductIntelligenceSummaryResponse(
        total_products=len(products),
        products_by_source=dict(sorted(products_by_source.items(), key=lambda item: (-item[1], item[0]))),
        products_by_current_category=dict(sorted(products_by_current_category.items(), key=lambda item: (-item[1], item[0]))),
        products_by_current_type=dict(sorted(products_by_current_type.items(), key=lambda item: (-item[1], item[0]))),
        products_with_missing_category_or_type=sum(
            1
            for product in products
            if not _first_non_empty(product.get("category")) or not _first_non_empty(product.get("type"))
        ),
        products_with_source_taxonomy_conflict_risk=sum(1 for profile in profiles if profile["taxonomy_conflict"]),
        products_with_image_available=sum(1 for profile in profiles if profile["image_analysis"]["status"] == "AVAILABLE"),
        products_with_image_not_available=sum(1 for profile in profiles if profile["image_analysis"]["status"] == "NOT_AVAILABLE"),
        products_with_image_not_analyzed=sum(1 for profile in profiles if profile["image_analysis"]["status"] == "NOT_ANALYZED"),
        products_with_sold_count_available=sum(1 for profile in profiles if profile["sales_metrics"]["sold_count"] is not None),
        products_with_shop_count_available=sum(1 for profile in profiles if profile["sales_metrics"]["shop_count"] is not None),
        products_with_shop_names_available=sum(1 for profile in profiles if bool(profile["sales_metrics"]["shop_names"])),
        group_distribution=_distribution(profiles, "group"),
        copy_route_distribution=_distribution(profiles, "copy_route"),
        claim_gate_distribution=_distribution(profiles, "claim_gate"),
        confidence_distribution=_distribution(profiles, "confidence"),
        sample_conflicts=[
            {
                "product_id": profile.get("product_id"),
                "normalized_title": profile.get("normalized_title"),
                "group": profile.get("group"),
                "bosmax_product_family": profile.get("bosmax_product_family"),
                "taxonomy_conflict_reason": profile.get("taxonomy_conflict_reason"),
            }
            for profile in profiles
            if profile["taxonomy_conflict"]
        ][:10],
    )
    return summary.model_dump()


async def get_product_intelligence_backfill_preview() -> dict[str, Any]:
    products = await crud.list_products(limit=10000)
    profiles = [resolve_product_intelligence_profile(product) for product in products]
    failures = [
        {
            "product_id": profile.get("product_id"),
            "normalized_title": profile.get("normalized_title"),
            "group": profile.get("group"),
            "warnings": profile.get("warnings", []),
            "confidence": profile.get("confidence"),
        }
        for profile in profiles
        if profile["confidence"] == "LOW"
    ]
    conflicts = [
        {
            "product_id": profile.get("product_id"),
            "normalized_title": profile.get("normalized_title"),
            "group": profile.get("group"),
            "bosmax_product_family": profile.get("bosmax_product_family"),
            "taxonomy_conflict_reason": profile.get("taxonomy_conflict_reason"),
        }
        for profile in profiles
        if profile["taxonomy_conflict"]
    ]
    payload = ProductIntelligenceBackfillPreviewResponse(
        total_products=len(products),
        resolved=sum(1 for profile in profiles if profile["group"] != "UNKNOWN_REVIEW_REQUIRED"),
        high_confidence=sum(1 for profile in profiles if profile["confidence"] == "HIGH"),
        medium_confidence=sum(1 for profile in profiles if profile["confidence"] == "MEDIUM"),
        low_confidence=sum(1 for profile in profiles if profile["confidence"] == "LOW"),
        needs_review=sum(1 for profile in profiles if profile["intelligence_status"] == "NEEDS_REVIEW"),
        taxonomy_conflicts=len(conflicts),
        copy_route_distribution=_distribution(profiles, "copy_route"),
        claim_gate_distribution=_distribution(profiles, "claim_gate"),
        group_distribution=_distribution(profiles, "group"),
        sample_failures=failures[:10],
        sample_conflicts=conflicts[:10],
        write_back_status="READ_ONLY_NO_DB_WRITES",
    )
    return payload.model_dump()
