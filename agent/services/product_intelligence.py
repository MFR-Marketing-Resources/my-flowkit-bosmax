import logging
import httpx
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from pathlib import Path
from agent.db import crud
from agent.utils.paths import product_image_path
from agent.services.flow_client import get_flow_client
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import resolve_product_physics, evaluate_prompt_readiness
from agent.services.product_preflight import build_product_preflight, evaluate_mapping_status, resolve_creative_profile
from agent.services.product_intelligence_service import (
    inject_product_intelligence_fields,
    resolve_product_intelligence_profile,
)
from agent.config import BASE_DIR

logger = logging.getLogger(__name__)

IMAGE_READY_STATES = {"IMAGE_READY", "IMAGE_CACHE_READY"}
MODE_IMAGE_DEPENDENT = ("Images", "Ingredients", "Frames")
TEST_PRODUCT_NAMES = {"test product", "test item", "fixture product"}
_CURRENCY_QUANTUM = Decimal("0.01")


def resolve_cached_image_path(payload: dict[str, Any]) -> Path | None:
    local_image_path = (payload.get("local_image_path") or "").strip()
    if not local_image_path:
        return None

    cached_path = Path(local_image_path)
    if not cached_path.is_absolute():
        cached_path = BASE_DIR / cached_path
    return cached_path


def is_test_product(payload: dict[str, Any]) -> bool:
    product_id = str(payload.get("id") or payload.get("product_id") or "").strip().lower()
    short_name = str(payload.get("product_short_name") or "").strip().lower()
    raw_title = str(payload.get("raw_product_title") or "").strip().lower()
    local_image_path = str(payload.get("local_image_path") or "").strip().lower()

    if product_id.startswith("test_") or product_id.startswith("fixture_"):
        return True
    if short_name in TEST_PRODUCT_NAMES or raw_title in TEST_PRODUCT_NAMES:
        return True
    if short_name.startswith("test product") or raw_title.startswith("test product"):
        return True
    if local_image_path in {"test.jpg", "test.jpeg", "test.png", "test.webp", "test.gif"}:
        return True
    return False


def build_rendered_image_fields(payload: dict[str, Any]) -> dict[str, Any]:
    product_id = payload.get("id") or payload.get("product_id")
    image_url = (payload.get("image_url") or "").strip() or None
    local_image_path = (payload.get("local_image_path") or "").strip()
    readiness = payload.get("image_readiness_status")

    if product_id and local_image_path:
        return {
            "rendered_img_src": f"/api/products/{product_id}/image",
            "image_http_status": 200 if readiness == "IMAGE_CACHE_READY" else 404,
        }

    return {
        "rendered_img_src": image_url,
        "image_http_status": None,
    }

def normalize_source(source: str | None) -> str:
    normalized = (source or "FASTMOSS").strip().upper()
    if normalized == "MANUAL_PROJECT":
        return "MANUAL"
    if normalized in {"FASTMOSS", "TIKTOKSHOP", "MANUAL", "IMPORTED"}:
        return normalized
    return "MANUAL"

def display_name(raw_title: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    return " ".join(raw_title.split()[:9]).strip()

def _parse_decimal(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def normalize_currency_amount(value: Any) -> float | None:
    amount = _parse_decimal(value)
    if amount is None:
        return None
    return float(amount.quantize(_CURRENCY_QUANTUM, rounding=ROUND_HALF_UP))


def parse_percentage(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        percentage = Decimal(str(value).replace("%", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return percentage / Decimal("100")

def derive_commission_amount(price: Any, commission_rate: str | None) -> float | None:
    normalized_price = _parse_decimal(price)
    rate = parse_percentage(commission_rate)
    if normalized_price is None or rate is None:
        return None
    commission_amount = normalized_price * rate
    return float(commission_amount.quantize(_CURRENCY_QUANTUM, rounding=ROUND_HALF_UP))

def json_load_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
        return [item.strip() for item in stripped.split("|") if item.strip()]
    return [str(value)]

def json_dump_list(values: list[str]) -> str:
    return json.dumps([value for value in values if value], ensure_ascii=True)

def resolve_image_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    image_url = (payload.get("image_url") or "").strip()
    image_status = (payload.get("image_asset_status") or "").strip().upper()
    failure_detail = (payload.get("image_failure_detail") or "").strip()
    local_image_path = (payload.get("local_image_path") or "").strip()

    if local_image_path:
        cached_path = resolve_cached_image_path(payload)
        if cached_path.exists():
            return {
                "image_readiness_status": "IMAGE_CACHE_READY",
                "image_readiness_detail": str(cached_path),
            }
        return {
            "image_readiness_status": "LOCAL_CACHE_MISSING",
            "image_readiness_detail": failure_detail or f"Cached image file is missing: {cached_path}",
        }

    if image_status == "NOT_AVAILABLE":
        return {
            "image_readiness_status": "IMAGE_NOT_AVAILABLE",
            "image_readiness_detail": failure_detail or "Image marked as not available.",
        }

    if image_status == "FAILED":
        return {
            "image_readiness_status": "IMAGE_DOWNLOAD_FAILED",
            "image_readiness_detail": failure_detail or "Image download failed.",
        }

    if image_url:
        return {
            "image_readiness_status": "IMAGE_READY",
            "image_readiness_detail": failure_detail or "Remote image URL is available.",
        }

    missing_from_source = payload.get("source") == "FASTMOSS" and bool(payload.get("fastmoss_source_file"))
    return {
        "image_readiness_status": "IMAGE_URL_MISSING_FROM_SOURCE" if missing_from_source else "IMAGE_URL_MISSING",
        "image_readiness_detail": failure_detail or ("Image URL missing from imported source data." if missing_from_source else "Image URL missing."),
    }

def mode_readiness(payload: dict[str, Any]) -> dict[str, dict[str, str | list[str]]]:
    missing_fields = [field for field in (payload.get("prompt_missing_fields") or []) if field != "image_url"]
    has_image = payload.get("image_readiness_status") in IMAGE_READY_STATES
    text_status = "READY_OR_NEEDS_REVIEW" if not missing_fields else "MISSING_FIELDS"
    text_detail = "Product metadata is sufficient for text-to-video draft generation without an image." if text_status == "READY_OR_NEEDS_REVIEW" else f"Missing fields: {', '.join(missing_fields)}"
    readiness: dict[str, dict[str, str | list[str]]] = {
        "Text to Video": {
            "status": text_status,
            "detail": text_detail,
            "missing_fields": missing_fields,
            "asset_strategy": "WITH_IMAGE" if has_image else "NO_IMAGE",
        }
    }

    for mode in MODE_IMAGE_DEPENDENT:
        if missing_fields:
            readiness[mode] = {
                "status": "MISSING_FIELDS",
                "detail": f"Missing fields: {', '.join(missing_fields)}",
                "missing_fields": missing_fields,
            }
        elif not has_image:
            readiness[mode] = {
                "status": "BLOCKED_IMAGE_MISSING",
                "detail": "Requires image_url or local_image_path.",
                "missing_fields": ["image_url"],
            }
        else:
            readiness[mode] = {
                "status": "READY",
                "detail": "Image and product metadata are ready.",
                "missing_fields": [],
            }
    return readiness

async def enrich_product(product: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    payload = dict(product)
    payload["source"] = normalize_source(payload.get("source"))
    payload["source_url"] = payload.get("source_url") or payload.get("tiktok_product_url")
    payload["price"] = normalize_currency_amount(payload.get("price") if payload.get("price") is not None else payload.get("price_min"))
    payload["price_min"] = normalize_currency_amount(payload.get("price_min"))
    payload["price_max"] = normalize_currency_amount(payload.get("price_max"))
    payload["currency"] = payload.get("currency") or "MYR"
    payload["commission_rate"] = payload.get("commission_rate") or payload.get("commission")
    payload["commission_amount"] = normalize_currency_amount(payload.get("commission_amount"))
    if payload["commission_amount"] is None:
        payload["commission_amount"] = derive_commission_amount(payload.get("price"), payload.get("commission_rate"))
    payload["image_asset_status"] = payload.get("image_asset_status") or payload.get("asset_status")
    payload["mode_recommendations"] = json_load_list(payload.get("mode_recommendations"))
    payload["unsafe_handling_rules"] = json_load_list(payload.get("unsafe_handling_rules"))
    payload["prompt_missing_fields"] = json_load_list(payload.get("prompt_missing_fields"))

    mapping = resolve_product_mapping(product=payload, source_hint=payload.get("source"))
    payload.update(mapping)
    intelligence = resolve_product_intelligence_profile(payload)
    payload = inject_product_intelligence_fields(payload, intelligence)
    physics = resolve_product_physics(product=payload)
    payload.update(physics)
    creative_profile = resolve_creative_profile(payload)
    payload.update(creative_profile)
    payload["product_display_name"] = creative_profile.get("display_name") or payload.get("product_display_name")
    payload.update(evaluate_mapping_status(payload))
    payload.update(resolve_image_readiness(payload))
    payload.update(build_rendered_image_fields(payload))
    readiness = evaluate_prompt_readiness(payload, physics)
    payload.update(readiness)
    combined_missing = []
    for field in [*(payload.get("prompt_missing_fields") or []), *(payload.get("mapping_missing_fields") or [])]:
        if field and field not in combined_missing:
            combined_missing.append(field)
    payload["prompt_missing_fields"] = combined_missing
    if payload.get("mapping_status") == "BLOCKED":
        payload["prompt_readiness_status"] = "MISSING_FIELDS"
    elif payload.get("mapping_status") == "NEEDS_REVIEW" and payload.get("prompt_readiness_status") == "READY":
        payload["prompt_readiness_status"] = "NEEDS_REVIEW"
    payload["mode_readiness"] = mode_readiness(payload)
    payload["product_id"] = payload.get("id")
    payload["is_test_product"] = is_test_product(payload)
    payload["catalog_label"] = "TEST" if payload["is_test_product"] else payload.get("source")
    payload["mapping_review_status"] = payload.get("mapping_review_status") or payload.get("mapping_status") or (
        "NEEDS_REVIEW" if payload.get("mapping_confidence") == "NEEDS_REVIEW" else "AUTO_MAPPED"
    )
    payload["claim_gate"] = intelligence.get("claim_gate")
    payload["claim_tokens"] = intelligence.get("claim_tokens", [])
    payload["copy_route"] = intelligence.get("copy_route")
    payload["destination_readiness"] = intelligence.get("destination_readiness", {})
    payload["preflight"] = build_product_preflight(payload)

    if persist and payload.get("id"):
        await persist_intelligence(payload["id"], payload)
    return payload

async def persist_intelligence(product_id: str, payload: dict[str, Any]) -> None:
    await crud.update_product(
        product_id,
        source=normalize_source(payload.get("source")),
        source_url=payload.get("source_url") or None,
        brand=payload.get("brand") or None,
        raw_product_title=payload.get("raw_product_title") or None,
        product_display_name=payload.get("product_display_name") or None,
        product_short_name=payload.get("product_short_name") or None,
        product_type_id=payload.get("product_type_id") or None,
        category=payload.get("category") or None,
        subcategory=payload.get("subcategory") or None,
        type=payload.get("type") or None,
        shop_name=payload.get("shop_name") or None,
        price=payload.get("price"),
        currency=payload.get("currency") or None,
        commission_amount=payload.get("commission_amount"),
        commission_rate=payload.get("commission_rate") or None,
        commission=payload.get("commission_rate") or None,
        image_url=payload.get("image_url") or None,
        tiktok_product_url=payload.get("tiktok_product_url") or None,
        image_asset_status=payload.get("image_asset_status") or None,
        image_failure_detail=payload.get("image_failure_detail") or None,
        product_type=payload.get("product_type") or None,
        silo=payload.get("silo") or None,
        trigger_id=payload.get("trigger_id") or None,
        formula=payload.get("formula") or None,
        copywriting_angle=payload.get("copywriting_angle") or None,
        claim_risk_level=payload.get("claim_risk_level") or None,
        mode_recommendations=json_dump_list(payload.get("mode_recommendations") or []),
        physics_class=payload.get("physics_class") or None,
        product_scale=payload.get("product_scale") or None,
        hand_object_interaction=payload.get("hand_object_interaction") or None,
        recommended_grip=payload.get("recommended_grip") or None,
        handling_notes=payload.get("handling_notes") or None,
        air_gap_rule=payload.get("air_gap_rule") or None,
        material_behavior=payload.get("material_behavior") or None,
        surface_behavior=payload.get("surface_behavior") or None,
        fragility_level=payload.get("fragility_level") or None,
        camera_handling_notes=payload.get("camera_handling_notes") or None,
        scene_context=payload.get("scene_context") or None,
        camera_style=payload.get("camera_style") or None,
        camera_behavior=payload.get("camera_behavior") or None,
        camera_shot=payload.get("camera_shot") or None,
        unsafe_handling_rules=json_dump_list(payload.get("unsafe_handling_rules") or []),
        section_5_product_physics_prompt=payload.get("section_5_product_physics_prompt") or None,
        section_4_hint=payload.get("section_4_hint") or None,
        section_5_physics_hint=payload.get("section_5_physics_hint") or None,
        section_6_copy_hint=payload.get("section_6_copy_hint") or None,
        section_9_overlay_hint=payload.get("section_9_overlay_hint") or None,
        mapping_source=payload.get("mapping_source") or None,
        mapping_confidence=payload.get("mapping_confidence") or None,
        mapping_review_status=payload.get("mapping_review_status") or None,
        mapping_status=payload.get("mapping_status") or None,
        mapping_missing_fields=json_dump_list(payload.get("mapping_missing_fields") or []),
        prompt_readiness_status=payload.get("prompt_readiness_status") or None,
        prompt_missing_fields=json_dump_list(payload.get("prompt_missing_fields") or []),
        asset_status=payload.get("asset_status") or None,
        local_image_path=payload.get("local_image_path") or None,
    )

async def generate_product_prompt(product: dict, mode: str) -> str:
    """Generate a high-conversion prompt based on product metadata and category guardrails."""
    name = product.get("product_short_name") or product.get("product_display_name")
    category = product.get("category", "").lower()
    
    # Base descriptive prompt
    prompt = f"Product showcase of {name}. {product.get('product_display_name')}. "
    
    # Category-specific enhancements & guardrails
    if "baby" in category or "diaper" in category:
        prompt += (
            "Clean, bright, professional parenting context. "
            "Focus on product quality, soft texture, and reliable baby care. "
            "No unsafe handling, no medical claims. Product-focused demonstration."
        )
    elif "food" in category or "milk" in category:
        prompt += (
            "Appetizing, fresh, high-quality food presentation. "
            "Clean kitchen or natural setting. Professional food photography lighting."
        )
    elif "toy" in category:
        prompt += (
            "Bright, playful, educational environment. "
            "Clear focus on the toy's features and safe interactive elements."
        )
    else:
        prompt += "High-quality commercial product cinematography, studio lighting, sharp focus."

    # Mode specific adjustments
    if mode == "IMG":
        prompt = f"Professional studio product shot: {prompt}"
    elif mode in ["I2V", "F2V"]:
        prompt = f"Cinematic product commercial: {prompt} Subtle camera movement, dynamic lighting."
        
    return prompt

async def resolve_product_assets(product_id: str) -> dict:
    """Download product image from URL if UNRESOLVED."""
    product = await crud.get_product(product_id)
    if not product:
        return {"error": "Product not found"}
    
    if product.get("asset_status") != "UNRESOLVED":
        return {"status": product["asset_status"], "local_path": product.get("local_image_path")}

    image_url = product.get("image_url")
    if not image_url:
        return {"error": "No image URL for product"}

    try:
        dest = product_image_path(product_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_url, timeout=30.0)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            
        await crud.update_product(product_id, 
                                  asset_status="DOWNLOADED", 
                                  local_image_path=str(dest))
        return {"status": "DOWNLOADED", "local_path": str(dest)}
    except Exception as e:
        logger.error(f"Failed to download product image for {product_id}: {e}")
        return {"error": str(e)}

async def upload_product_to_flow(product_id: str) -> dict:
    """Upload the cached product image to Google Flow to get media_id."""
    product = await crud.get_product(product_id)
    if not product:
        return {"error": "Product not found"}
    
    if product.get("media_id"):
        return {"media_id": product["media_id"]}

    local_path = product.get("local_image_path")
    if not local_path or not Path(local_path).exists():
        # Try to resolve/download first
        res = await resolve_product_assets(product_id)
        if "error" in res:
            return res
        local_path = res["local_path"]

    try:
        client = get_flow_client()
        # Note: We need an upload_image_from_path method or similar in FlowClient
        # For now, we use upload_image which takes raw bytes or similar
        with open(local_path, "rb") as f:
            image_data = f.read()
            
        # Mocking the upload call — in real logic, FlowClient.upload_image takes name + data
        # result = await client.upload_image(product["product_short_name"], image_data)
        # media_id = result.get("name")
        
        # Actually, let's look at FlowClient.upload_image signature
        # result = await client.upload_image(f"product_{product_id}", image_data)
        
        # For now, we return NOT VERIFIED as requested if we don't have the final proof
        return {"status": "UPLOAD_PENDING_IMPLEMENTATION", "local_path": local_path}
    except Exception as e:
        logger.error(f"Failed to upload product image for {product_id}: {e}")
        return {"error": str(e)}
