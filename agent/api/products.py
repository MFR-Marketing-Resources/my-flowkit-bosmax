import base64
import aiohttp
import json
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agent.config import BASE_DIR
from agent.db import crud
from agent.services.product_intelligence import generate_product_prompt, resolve_product_assets, upload_product_to_flow
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import evaluate_prompt_readiness, resolve_product_physics
from agent.utils.paths import product_image_path

router = APIRouter(prefix="/products", tags=["products"])


class ProductMapRequest(BaseModel):
    product_id: str | None = None
    product_name: str | None = None
    raw_product_title: str | None = None
    source: str | None = None
    category: str | None = None
    subcategory: str | None = None
    type: str | None = None
    override_category: str | None = None
    override_subcategory: str | None = None
    override_type: str | None = None
    persist: bool = False


class ProductPhysicsRequest(BaseModel):
    product_id: str | None = None
    product_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    type: str | None = None
    persist: bool = False


class ManualProductRequest(BaseModel):
    raw_product_title: str | None = None
    product_name: str | None = None
    product_display_name: str | None = None
    product_short_name: str | None = None
    brand: str | None = None
    category: str | None = None
    subcategory: str | None = None
    type: str | None = None
    shop_name: str | None = None
    price: float | None = None
    currency: str | None = "MYR"
    commission_amount: float | None = None
    commission_rate: str | None = None
    image_url: str | None = None
    source_url: str | None = None
    tiktok_product_url: str | None = None
    image_base64: str | None = None
    image_filename: str | None = None


class ProductPatchRequest(BaseModel):
    source: str | None = None
    source_url: str | None = None
    brand: str | None = None
    raw_product_title: str | None = None
    product_display_name: str | None = None
    product_short_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    type: str | None = None
    shop_name: str | None = None
    price: float | None = None
    currency: str | None = None
    commission_amount: float | None = None
    commission_rate: str | None = None
    image_url: str | None = None
    tiktok_product_url: str | None = None
    image_asset_status: str | None = None
    image_failure_detail: str | None = None
    asset_status: str | None = None
    local_image_path: str | None = None
    product_type: str | None = None
    silo: str | None = None
    trigger_id: str | None = None
    formula: str | None = None
    copywriting_angle: str | None = None
    claim_risk_level: str | None = None
    physics_class: str | None = None
    product_scale: str | None = None
    hand_object_interaction: str | None = None
    recommended_grip: str | None = None
    air_gap_rule: str | None = None
    material_behavior: str | None = None
    surface_behavior: str | None = None
    fragility_level: str | None = None
    camera_handling_notes: str | None = None
    section_5_product_physics_prompt: str | None = None
    image_base64: str | None = None
    image_filename: str | None = None


class ImportTikTokShopRequest(BaseModel):
    url: str
    raw_product_title: str | None = None
    product_display_name: str | None = None
    product_short_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    type: str | None = None
    image_url: str | None = None
    price: float | None = None
    currency: str | None = "MYR"
    commission_amount: float | None = None
    commission_rate: str | None = None


PRODUCT_LOOKUP_FIELDS = ["product_short_name", "product_display_name", "raw_product_title"]


def _normalize_source(source: str | None) -> str:
    normalized = (source or "FASTMOSS").strip().upper()
    if normalized == "MANUAL_PROJECT":
        return "MANUAL"
    if normalized in {"FASTMOSS", "TIKTOKSHOP", "MANUAL", "IMPORTED"}:
        return normalized
    return "MANUAL"


def _json_load_list(value: Any) -> list[str]:
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


def _json_dump_list(values: list[str]) -> str:
    return json.dumps([value for value in values if value], ensure_ascii=True)


def _display_name(raw_title: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    return " ".join(raw_title.split()[:9]).strip()


async def _save_manual_image(product_id: str, image_base64: str | None, image_filename: str | None) -> tuple[str | None, str | None]:
    if not image_base64:
        return None, None
    payload = image_base64.split(",", 1)[-1]
    try:
        data = base64.b64decode(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image_base64 payload: {exc}") from exc
    ext = "jpg"
    if image_filename and "." in image_filename:
        ext = image_filename.rsplit(".", 1)[-1].lower() or "jpg"
    dest = product_image_path(product_id, ext=ext)
    dest.write_bytes(data)
    return str(dest), "DOWNLOADED"


async def _persist_intelligence(product_id: str, payload: dict[str, Any]) -> None:
    await crud.update_product(
        product_id,
        source=_normalize_source(payload.get("source")),
        source_url=payload.get("source_url") or None,
        brand=payload.get("brand") or None,
        raw_product_title=payload.get("raw_product_title") or None,
        product_display_name=payload.get("product_display_name") or None,
        product_short_name=payload.get("product_short_name") or None,
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
        mode_recommendations=_json_dump_list(payload.get("mode_recommendations") or []),
        physics_class=payload.get("physics_class") or None,
        product_scale=payload.get("product_scale") or None,
        hand_object_interaction=payload.get("hand_object_interaction") or None,
        recommended_grip=payload.get("recommended_grip") or None,
        air_gap_rule=payload.get("air_gap_rule") or None,
        material_behavior=payload.get("material_behavior") or None,
        surface_behavior=payload.get("surface_behavior") or None,
        fragility_level=payload.get("fragility_level") or None,
        camera_handling_notes=payload.get("camera_handling_notes") or None,
        unsafe_handling_rules=_json_dump_list(payload.get("unsafe_handling_rules") or []),
        section_5_product_physics_prompt=payload.get("section_5_product_physics_prompt") or None,
        mapping_source=payload.get("mapping_source") or None,
        mapping_confidence=payload.get("mapping_confidence") or None,
        mapping_review_status=payload.get("mapping_review_status") or None,
        prompt_readiness_status=payload.get("prompt_readiness_status") or None,
        prompt_missing_fields=_json_dump_list(payload.get("prompt_missing_fields") or []),
        asset_status=payload.get("asset_status") or None,
        local_image_path=payload.get("local_image_path") or None,
    )


def _resolve_image_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    image_url = (payload.get("image_url") or "").strip()
    image_status = (payload.get("image_asset_status") or "").strip().upper()
    failure_detail = (payload.get("image_failure_detail") or "").strip()
    local_image_path = (payload.get("local_image_path") or "").strip()

    if local_image_path:
        cached_path = Path(local_image_path)
        if not cached_path.is_absolute():
            cached_path = BASE_DIR / cached_path
        if cached_path.exists():
            return {
                "image_readiness_status": "IMAGE_CACHE_READY",
                "image_readiness_detail": str(cached_path),
            }

    if image_status == "NOT_AVAILABLE":
        return {
            "image_readiness_status": "IMAGE_NOT_AVAILABLE",
            "image_readiness_detail": failure_detail or "Image marked as not available.",
        }

    if image_url and image_status == "FAILED":
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


async def _enrich_product(product: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    payload = dict(product)
    payload["source"] = _normalize_source(payload.get("source"))
    payload["source_url"] = payload.get("source_url") or payload.get("tiktok_product_url")
    payload["price"] = payload.get("price") if payload.get("price") is not None else payload.get("price_min")
    payload["currency"] = payload.get("currency") or "MYR"
    payload["commission_rate"] = payload.get("commission_rate") or payload.get("commission")
    payload["image_asset_status"] = payload.get("image_asset_status") or payload.get("asset_status")
    payload["mode_recommendations"] = _json_load_list(payload.get("mode_recommendations"))
    payload["unsafe_handling_rules"] = _json_load_list(payload.get("unsafe_handling_rules"))
    payload["prompt_missing_fields"] = _json_load_list(payload.get("prompt_missing_fields"))

    mapping = resolve_product_mapping(product=payload, source_hint=payload.get("source"))
    payload.update(mapping)
    physics = resolve_product_physics(product=payload)
    payload.update(physics)
    payload.update(_resolve_image_readiness(payload))
    readiness = evaluate_prompt_readiness(payload, physics)
    payload.update(readiness)
    payload["product_id"] = payload.get("id")
    payload["mapping_review_status"] = payload.get("mapping_review_status") or (
        "NEEDS_REVIEW" if payload.get("mapping_confidence") == "NEEDS_REVIEW" else "AUTO_MAPPED"
    )

    if persist and payload.get("id"):
        await _persist_intelligence(payload["id"], payload)
    return payload


async def _resolve_mapping_for_product(
    product: dict[str, Any] | None,
    *,
    product_name: str | None = None,
    source_hint: str | None = None,
    overrides: dict[str, str | None] | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    mapping = resolve_product_mapping(
        product=product,
        product_name=product_name,
        source_hint=source_hint,
        overrides=overrides,
    )
    seed = dict(product or {})
    seed.update(mapping)
    seed["source"] = _normalize_source(source_hint or seed.get("source"))
    enriched = await _enrich_product(seed, persist=False)
    if persist and product and product.get("id"):
        await _persist_intelligence(product["id"], enriched)
    return enriched


async def _find_product_by_lookup(product_id: str) -> dict[str, Any] | None:
    product = await crud.get_product(product_id)
    if product:
        return product
    all_products = await crud.list_products()
    search_normalized = product_id.lower().strip()
    for field_name in PRODUCT_LOOKUP_FIELDS:
        for candidate in all_products:
            field_val = candidate.get(field_name, "")
            if field_val and field_val.lower().strip() == search_normalized:
                return candidate
    if len(search_normalized) >= 4:
        for candidate in all_products:
            for field_name in PRODUCT_LOOKUP_FIELDS:
                field_val = candidate.get(field_name, "")
                if field_val and search_normalized in field_val.lower():
                    return candidate
    return None


@router.post("/{product_id}/cache-image")
async def cache_product_image(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    existing_local_path = product.get("local_image_path")
    if existing_local_path:
        cached_path = Path(existing_local_path)
        if not cached_path.is_absolute():
            cached_path = BASE_DIR / cached_path
        if cached_path.exists():
            await crud.update_product(product_id, local_image_path=str(cached_path), asset_status="DOWNLOADED", image_asset_status="READY", image_failure_detail=None)
            return {"status": "success", "local_image_path": str(cached_path), "image_asset_status": "READY"}

    image_url = product.get("image_url")
    if not image_url:
        detail = "Image URL missing from source data"
        await crud.update_product(product_id, asset_status="UNRESOLVED", image_asset_status="UNRESOLVED", image_failure_detail=detail)
        return {"status": "failed", "detail": detail, "image_asset_status": "UNRESOLVED"}

    try:
        ext = "jpg"
        if image_url.split("?")[0].split(".")[-1].lower() in ["jpg", "jpeg", "png", "webp", "gif"]:
            ext = image_url.split("?")[0].split(".")[-1].lower()

        dest = product_image_path(product_id, ext=ext)

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    detail = f"Failed to download image: {resp.status}"
                    await crud.update_product(product_id, asset_status="UNRESOLVED", image_asset_status="FAILED", image_failure_detail=detail)
                    return {"status": "failed", "detail": detail, "image_asset_status": "FAILED"}
                data = await resp.read()
                dest.write_bytes(data)

        if not dest.exists() or dest.stat().st_size == 0:
            detail = "Downloaded image was not written to disk"
            await crud.update_product(product_id, asset_status="UNRESOLVED", image_asset_status="FAILED", image_failure_detail=detail)
            return {"status": "failed", "detail": detail, "image_asset_status": "FAILED"}

        await crud.update_product(
            product_id,
            local_image_path=str(dest),
            asset_status="DOWNLOADED",
            image_asset_status="READY",
            image_failure_detail=None,
        )
        return {"status": "success", "local_image_path": str(dest), "image_asset_status": "READY"}
    except Exception as e:
        detail = str(e)
        await crud.update_product(product_id, asset_status="UNRESOLVED", image_asset_status="FAILED", image_failure_detail=detail)
        return {"status": "failed", "detail": detail, "image_asset_status": "FAILED"}


async def _list_products_response(
    *,
    q: str | None = None,
    source: str | None = None,
    readiness: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    source_norm = _normalize_source(source) if source else None
    products = await crud.list_products(source=source_norm, query=q, limit=limit, offset=offset)
    enriched = [await _enrich_product(product) for product in products]

    total = await crud.count_products(source=source_norm, query=q)
    if readiness:
        all_products = await crud.list_products(source=source_norm, query=q)
        enriched_all = [await _enrich_product(product) for product in all_products]
        filtered_all = [product for product in enriched_all if product.get("prompt_readiness_status") == readiness]
        enriched = [product for product in enriched if product.get("prompt_readiness_status") == readiness]
        total = len(filtered_all)

    return {
        "total_count": total,
        "returned_count": len(enriched),
        "has_pagination": (offset + len(enriched)) < total,
        "limit": limit,
        "offset": offset,
        "items": enriched,
    }


@router.get("")
async def list_products(
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    readiness: str | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    return await _list_products_response(q=q, source=source, readiness=readiness, limit=limit, offset=offset)


@router.get("/search")
async def search_products(
    q: str | None = Query(default=None),
    limit: int = Query(default=25),
    offset: int = Query(default=0),
):
    return await _list_products_response(q=q, limit=limit, offset=offset)


@router.post("/map")
async def map_product(data: ProductMapRequest):
    product = await crud.get_product(data.product_id) if data.product_id else None
    if data.product_id and not product:
        raise HTTPException(status_code=404, detail="Product not found")

    raw_product_title = data.raw_product_title or data.product_name
    if not product and not raw_product_title:
        raise HTTPException(status_code=400, detail="Missing product_name or product_id")

    enriched = await _resolve_mapping_for_product(
        product,
        product_name=raw_product_title,
        source_hint=data.source,
        overrides={
            "category": data.override_category or data.category,
            "subcategory": data.override_subcategory or data.subcategory,
            "type": data.override_type or data.type,
        },
        persist=bool(data.persist and product),
    )

    if data.persist and not product:
        created = await crud.create_product(
            raw_product_title=enriched["raw_product_title"],
            source=_normalize_source(data.source or "MANUAL"),
            product_display_name=_display_name(enriched["raw_product_title"]),
            product_short_name=enriched["product_short_name"],
            category=enriched.get("category") or None,
            subcategory=enriched.get("subcategory") or None,
            type=enriched.get("type") or None,
        )
        return await _enrich_product(created, persist=True)

    return enriched


@router.post("/physics-map")
async def physics_map_product(data: ProductPhysicsRequest):
    product = await crud.get_product(data.product_id) if data.product_id else None
    if data.product_id and not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product and not data.product_name:
        raise HTTPException(status_code=400, detail="Missing product_name or product_id")

    seed = dict(product or {})
    if data.product_name:
        seed.setdefault("raw_product_title", data.product_name)
        seed.setdefault("product_short_name", data.product_name)
    if data.category:
        seed["category"] = data.category
    if data.subcategory:
        seed["subcategory"] = data.subcategory
    if data.type:
        seed["type"] = data.type

    physics = resolve_product_physics(product=seed)
    readiness = evaluate_prompt_readiness(seed, physics)
    payload = dict(seed)
    payload.update(physics)
    payload.update(readiness)
    if data.persist and product and product.get("id"):
        await _persist_intelligence(product["id"], payload)
    return payload


@router.post("/manual")
async def create_manual_product(data: ManualProductRequest):
    raw_product_title = (data.raw_product_title or data.product_name or "").strip()
    if not raw_product_title:
        raise HTTPException(status_code=400, detail="Missing raw_product_title")

    mapping = resolve_product_mapping(
        product_name=raw_product_title,
        source_hint="MANUAL",
        overrides={
            "category": data.category,
            "subcategory": data.subcategory,
            "type": data.type,
        },
    )

    created = await crud.create_product(
        raw_product_title=raw_product_title,
        source="MANUAL",
        source_url=data.source_url or data.tiktok_product_url,
        brand=data.brand,
        product_display_name=_display_name(raw_product_title, data.product_display_name),
        product_short_name=data.product_short_name or mapping["product_short_name"],
        category=data.category or mapping.get("category") or None,
        subcategory=data.subcategory or mapping.get("subcategory") or None,
        type=data.type or mapping.get("type") or None,
        shop_name=data.shop_name,
        price=data.price,
        currency=data.currency,
        commission_amount=data.commission_amount,
        commission_rate=data.commission_rate,
        image_url=data.image_url,
        tiktok_product_url=data.tiktok_product_url,
        image_asset_status="DOWNLOADED" if data.image_base64 else "UNRESOLVED",
        asset_status="DOWNLOADED" if data.image_base64 else "UNRESOLVED",
    )
    local_image_path, image_asset_status = await _save_manual_image(created["id"], data.image_base64, data.image_filename)
    if local_image_path:
        created = await crud.update_product(created["id"], local_image_path=local_image_path, asset_status=image_asset_status, image_asset_status=image_asset_status)
    return await _enrich_product(created, persist=True)


@router.post("/import-tiktokshop")
async def import_tiktokshop_product(data: ImportTikTokShopRequest):
    draft_title = (data.raw_product_title or data.product_display_name or data.product_short_name or "TIKTOKSHOP_PENDING_METADATA").strip()
    created = await crud.create_product(
        raw_product_title=draft_title,
        source="TIKTOKSHOP",
        source_url=data.url,
        tiktok_product_url=data.url,
        product_display_name=_display_name(draft_title, data.product_display_name or "TikTok Shop Draft"),
        product_short_name=(data.product_short_name or "TikTok Shop Draft").strip(),
        category=data.category,
        subcategory=data.subcategory,
        type=data.type,
        price=data.price,
        currency=data.currency,
        commission_amount=data.commission_amount,
        commission_rate=data.commission_rate,
        image_url=data.image_url,
        mapping_review_status="TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED",
        prompt_readiness_status="MISSING_FIELDS",
    )
    enriched = await _enrich_product(created, persist=True)
    return {
        "ok": False,
        "error_code": "TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED",
        "manual_entry_required": True,
        "product": enriched,
    }


@router.post("/import-fastmoss")
async def import_fastmoss_catalog():
    try:
        from agent.api.operator import _load_products

        products = _load_products(limit=500)
        imported = 0
        for entry in products:
            raw_title = entry.raw_product_title or entry.product_name
            existing = await crud.list_products(query=raw_title)
            if any((candidate.get("raw_product_title") or "").strip().lower() == raw_title.strip().lower() for candidate in existing):
                continue
            created = await crud.create_product(
                raw_product_title=raw_title,
                source="FASTMOSS",
                product_display_name=entry.product_display_name,
                product_short_name=entry.product_short_name,
                category=entry.category,
                subcategory=entry.sub_category,
                type=entry.type_angle,
                shop_name=entry.shop_name,
                price=entry.avg_price_rm,
                price_min=entry.avg_price_rm,
                currency="MYR",
                product_type=entry.product_type,
                silo=entry.silo_id,
                trigger_id=entry.trigger_id,
                formula=entry.submode_formula,
                copywriting_angle=entry.copywriting_angle or entry.copy_angle,
                claim_risk_level=entry.claim_risk_level,
                mode_recommendations=json.dumps(entry.mode_recommendations or []),
                fastmoss_source_file="FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx",
                asset_status="UNRESOLVED",
                image_asset_status="UNRESOLVED",
            )
            await _enrich_product(created, persist=True)
            imported += 1
        return {"ok": True, "imported": imported, "total": len(products)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/{product_id}/mapping")
async def get_product_mapping(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    enriched = await _enrich_product(product, persist=True)
    return {
        key: enriched.get(key)
        for key in [
            "product_id", "raw_product_title", "product_short_name", "category", "subcategory", "type",
            "product_type", "silo", "trigger_id", "formula", "mode_recommendations", "copywriting_angle",
            "claim_risk_level", "mapping_source", "mapping_confidence", "mapping_review_status",
            "prompt_readiness_status", "prompt_missing_fields", "section_4_visual_action_prompt",
            "section_6_dialogue_prompt", "section_9_overlay_prompt",
        ]
    }


@router.get("/{product_id}/physics")
async def get_product_physics(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    enriched = await _enrich_product(product, persist=True)
    return {
        key: enriched.get(key)
        for key in [
            "product_id", "physics_class", "product_scale", "hand_object_interaction", "recommended_grip",
            "air_gap_rule", "material_behavior", "surface_behavior", "fragility_level",
            "camera_handling_notes", "unsafe_handling_rules", "section_5_product_physics_prompt",
            "physics_dna_status",
        ]
    }


@router.get("/{product_id}")
async def get_product(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return await _enrich_product(product, persist=True)


@router.patch("/{product_id}")
async def patch_product(product_id: str, data: ProductPatchRequest):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    update_payload = {key: value for key, value in data.model_dump().items() if value is not None and key not in {"image_base64", "image_filename"}}
    if "source" in update_payload:
        update_payload["source"] = _normalize_source(update_payload["source"])
    if "commission_rate" in update_payload:
        update_payload["commission"] = update_payload["commission_rate"]
    updated = await crud.update_product(product_id, **update_payload)
    local_image_path, image_asset_status = await _save_manual_image(product_id, data.image_base64, data.image_filename)
    if local_image_path:
        updated = await crud.update_product(product_id, local_image_path=local_image_path, asset_status=image_asset_status, image_asset_status=image_asset_status)
    return await _enrich_product(updated, persist=True)


@router.post("/{product_id}/resolve-assets")
async def resolve_assets(product_id: str):
    return await resolve_product_assets(product_id)


@router.post("/{product_id}/upload-to-flow")
async def upload_to_flow(product_id: str):
    return await upload_product_to_flow(product_id)


@router.get("/{product_id}/prompt")
async def get_generated_prompt(product_id: str, mode: str = "F2V"):
    product = await _find_product_by_lookup(product_id)
    if not product:
        mapping = resolve_product_mapping(product_name=product_id, source_hint="MANUAL")
        if mapping.get("mapping_confidence") == "NEEDS_REVIEW":
            raise HTTPException(status_code=404, detail=f"Product not found: {product_id}")
        product = {
            "raw_product_title": mapping["raw_product_title"],
            "product_display_name": mapping["raw_product_title"],
            "product_short_name": mapping["product_short_name"],
            "category": mapping["category"],
        }

    enriched = await _enrich_product(product)
    normalized_mode = {"TRUE_F2V": "F2V", "GENERATE_VIDEO": "I2V", "GENERATE_VIDEO_REFS": "I2V"}.get(mode, mode)
    prompt = await generate_product_prompt(enriched, normalized_mode)
    return {
        "product_id": enriched.get("id") or product_id,
        "mode": mode,
        "prompt": prompt,
        "prompt_length": len(prompt),
        "prompt_source": "SYSTEM",
    }
