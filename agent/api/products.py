import base64
import aiohttp
import csv
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent.config import BASE_DIR
from agent.db import crud
from agent.services.product_intelligence import (
    enrich_product, resolve_product_assets, upload_product_to_flow,
    normalize_source as _normalize_source,
    json_load_list as _json_load_list,
    json_dump_list as _json_dump_list,
    derive_commission_amount as _derive_commission_amount,
    display_name as _display_name,
    generate_product_prompt,
    resolve_cached_image_path,
    is_test_product as _is_test_product,
)
from agent.services.product_catalog_audit import build_mapping_summary
from agent.services.product_lifecycle_service import (
    archive_product as archive_product_row,
    delete_test_row as delete_test_product_row,
    delete_product_permanent as delete_product_permanent_row,
    get_product_lifecycle,
    is_archived as is_product_archived,
    lifecycle_status as resolve_lifecycle_status,
    unarchive_product as unarchive_product_row,
)
from agent.services.product_preflight import build_product_preflight
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import resolve_product_physics, evaluate_prompt_readiness
from agent.services.prompt_pipeline_readiness_service import PromptPipelineReadinessService
from agent.services.claim_safe_rewrite_service import (
    APPROVAL_PHRASE as CLAIM_SAFE_APPROVAL_PHRASE,
    approve_claim_safe_rewrite,
    refresh_claim_safe_package_if_stale,
    preview_claim_safe_rewrite,
)
from agent.services.production_prompt_approval_service import (
    APPROVAL_PHRASE as PRODUCTION_PROMPT_APPROVAL_PHRASE,
    approve_production_prompt_package,
)
from agent.services.approved_product_package_service import get_approved_product_package
from agent.services.prompt_package_dryrun_service import generate_prompt_dryrun
from agent.services.fastmoss_product_reference_service import (
    FASTMOSS_REFERENCE_LANE,
    is_fastmoss_reference_product_id,
    list_fastmoss_reference_products,
)
from agent.utils.paths import product_image_path

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/catalog-state/{identifier:path}")
async def get_product_catalog_state(identifier: str):
    """Product Truth Gateway read-model endpoint.

    Returns the ONE normalized, lifecycle-aware product-state view for any
    identifier (canonical product UUID or ``fastmoss-ref:*``). Every consumer
    surface can call this to agree on whether an id is REFERENCE_ONLY,
    READY_FOR_APPROVAL_PREVIEW_ONLY, APPROVED_CANONICAL, blocked, or unknown —
    instead of each lane re-deriving identity differently.

    ``authority_ids`` is sourced from the same ``product`` table the BOSMAX
    authority registry iterates, so ``authority_context_available`` reflects the
    truth: within one bound storage the catalog and authority cannot silently
    disagree, and a cross-worktree storage split surfaces as zero authority ids.
    """
    from agent.services import product_catalog_read_model as _prm

    authority_ids = {p["id"] for p in await crud.list_products(limit=5000)}
    return await _prm.resolve_product_state(identifier, authority_ids=authority_ids)


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
    product_type_id: str | None = None
    silo: str | None = None
    trigger_id: str | None = None
    formula: str | None = None
    copywriting_angle: str | None = None
    claim_risk_level: str | None = None
    physics_class: str | None = None
    product_scale: str | None = None
    hand_object_interaction: str | None = None
    recommended_grip: str | None = None
    handling_notes: str | None = None
    air_gap_rule: str | None = None
    material_behavior: str | None = None
    surface_behavior: str | None = None
    fragility_level: str | None = None
    camera_handling_notes: str | None = None
    scene_context: str | None = None
    camera_style: str | None = None
    camera_behavior: str | None = None
    camera_shot: str | None = None
    section_5_product_physics_prompt: str | None = None
    section_4_hint: str | None = None
    section_5_physics_hint: str | None = None
    section_6_copy_hint: str | None = None
    section_9_overlay_hint: str | None = None
    image_base64: str | None = None
    image_filename: str | None = None


class ProductLifecycleActionRequest(BaseModel):
    reason: str
    confirmation_phrase: str


class ClaimSafeRewriteApprovalRequest(BaseModel):
    confirmation_phrase: str
    approval_note: str | None = None


class ProductionPromptApprovalRequest(BaseModel):
    approval_phrase: str
    approved_modes: list[str]
    reviewer_note: str | None = None
    confirm_no_google_flow_execution: bool


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

IMAGE_READY_STATES = {"IMAGE_READY", "IMAGE_CACHE_READY"}
MODE_IMAGE_DEPENDENT = ("Images", "Ingredients", "Frames")


# (Removed local helpers, now using product_intelligence service)


async def _find_product_by_exact_title(raw_title: str) -> dict[str, Any] | None:
    candidates = await crud.list_products(query=raw_title)
    normalized = _normalize_lookup_value(raw_title)
    for candidate in candidates:
        if _normalize_lookup_value(candidate.get("raw_product_title")) == normalized:
            return candidate
    return None


async def _find_image_map_match(row: dict[str, str], products: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    product_id = (row.get("product_id") or "").strip()
    if product_id:
        for product in products:
            if product.get("id") == product_id:
                return product, None
        return None, f"No product matched product_id '{product_id}'"

    raw_title = (row.get("raw_product_title") or "").strip()
    if raw_title:
        normalized = _normalize_lookup_value(raw_title)
        matches = [product for product in products if _normalize_lookup_value(product.get("raw_product_title")) == normalized]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"Ambiguous raw_product_title '{raw_title}'"

    short_name = (row.get("product_short_name") or "").strip()
    if short_name:
        normalized = _normalize_lookup_value(short_name)
        matches = [product for product in products if _normalize_lookup_value(product.get("product_short_name")) == normalized]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"Ambiguous product_short_name '{short_name}'"
        return None, f"No product matched product_short_name '{short_name}'"

    return None, "Row missing product_id, raw_product_title, and product_short_name"


async def _parse_image_map_upload(file: UploadFile) -> list[dict[str, str]]:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    content = raw.decode("utf-8-sig")
    filename = (file.filename or "").lower()
    if filename.endswith(".json"):
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="JSON image map must be an array")
        return [{str(key): "" if value is None else str(value) for key, value in row.items()} for row in parsed if isinstance(row, dict)]
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV image map is missing a header row")
    return [{str(key): "" if value is None else str(value) for key, value in row.items()} for row in reader]


def _detect_image_ext(data: bytes) -> str | None:
    """Return a canonical extension if ``data`` starts with real image magic
    bytes, else None. Guards the operator attach path so an empty or non-image
    payload can never be persisted and then read back as IMAGE_CACHE_READY."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


async def _save_manual_image(product_id: str, image_base64: str | None, image_filename: str | None) -> tuple[str | None, str | None]:
    if not image_base64:
        return None, None
    payload = image_base64.split(",", 1)[-1]
    try:
        data = base64.b64decode(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"INVALID_IMAGE_BASE64: {exc}") from exc
    if not data:
        raise HTTPException(status_code=422, detail="EMPTY_IMAGE: decoded image payload is empty")
    detected_ext = _detect_image_ext(data)
    if detected_ext is None:
        raise HTTPException(
            status_code=422,
            detail="UNSUPPORTED_IMAGE_TYPE: expected a real JPEG, PNG, GIF, or WEBP image",
        )
    # Prefer the detected type over a caller-supplied extension so the stored
    # file's extension always matches its real bytes.
    ext = detected_ext
    dest = product_image_path(product_id, ext=ext)
    dest.write_bytes(data)
    return str(dest), "DOWNLOADED"


async def _enrich_product(product: dict[str, Any], *, persist: bool = False) -> dict[str, Any]:
    return await enrich_product(product, persist=persist)


# Catalog enrichment is pure-deterministic per row but costs ~24ms/row, so
# enriching the whole ~500-row catalog on every GET /api/products (line-515
# loop) took ~12s and blocked the event loop — the "Loading products..." stall.
# This memoises the enriched result per row, keyed on the row's mutation markers
# (updated_at + claim-safe/lifecycle stamps), so any product write invalidates
# exactly that row with no staleness; unchanged rows are reused instantly.
_CATALOG_ENRICH_CACHE: dict[tuple, dict[str, Any]] = {}
_CATALOG_ENRICH_CACHE_MAX = 4000


def _catalog_enrich_key(product: dict[str, Any]) -> tuple | None:
    pid = product.get("id")
    if pid is None:
        return None
    return (
        pid,
        product.get("updated_at"),
        product.get("source"),
        product.get("lifecycle_status"),
        product.get("archived_at"),
        product.get("claim_safe_copy_updated_at"),
        product.get("mapping_status"),
    )


async def _enrich_product_cached(product: dict[str, Any]) -> dict[str, Any]:
    """Cache-backed enrichment for the read-only catalog list path only.

    Returns a shallow copy so downstream top-level mutations (e.g. catalog_state)
    never corrupt the cached entry. Callers that persist or need a guaranteed
    fresh compute must keep using ``_enrich_product`` directly.
    """
    key = _catalog_enrich_key(product)
    if key is not None:
        cached = _CATALOG_ENRICH_CACHE.get(key)
        if cached is not None:
            return dict(cached)
    enriched = await _enrich_product(product)
    if key is not None:
        if len(_CATALOG_ENRICH_CACHE) >= _CATALOG_ENRICH_CACHE_MAX:
            _CATALOG_ENRICH_CACHE.clear()
        _CATALOG_ENRICH_CACHE[key] = enriched
    return dict(enriched)


async def _refresh_claim_safe_product_row_if_needed(product: dict[str, Any]) -> dict[str, Any]:
    product_id = str(product.get("id") or "").strip()
    if not product_id or not product.get("claim_safe_copy_payload"):
        return product
    refreshed = await refresh_claim_safe_package_if_stale(product_id)
    if refreshed is None:
        return product
    latest = await crud.get_product(product_id)
    return latest or product

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
    enriched = await enrich_product(seed, persist=False)
    if persist and product and product.get("id"):
        from agent.services.product_intelligence import persist_intelligence
        await persist_intelligence(product["id"], enriched)
    return enriched


def _mapping_audit_payload(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "category",
        "subcategory",
        "type",
        "product_type_id",
        "silo",
        "trigger_id",
        "formula",
        "copywriting_angle",
        "claim_risk_level",
        "physics_class",
        "recommended_grip",
        "handling_notes",
        "camera_handling_notes",
        "scene_context",
        "camera_style",
        "camera_behavior",
        "camera_shot",
        "section_4_hint",
        "section_5_physics_hint",
        "section_6_copy_hint",
        "section_9_overlay_hint",
        "mapping_status",
        "mapping_missing_fields",
    ]
    return {
        field: {
            "before": before.get(field),
            "after": after.get(field),
        }
        for field in fields
    }


def _stored_mapping_snapshot(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": product.get("category"),
        "subcategory": product.get("subcategory"),
        "type": product.get("type"),
        "product_type_id": product.get("product_type_id"),
        "silo": product.get("silo"),
        "trigger_id": product.get("trigger_id"),
        "formula": product.get("formula"),
        "copywriting_angle": product.get("copywriting_angle"),
        "claim_risk_level": product.get("claim_risk_level"),
        "physics_class": product.get("physics_class"),
        "recommended_grip": product.get("recommended_grip"),
        "handling_notes": product.get("handling_notes"),
        "camera_handling_notes": product.get("camera_handling_notes"),
        "scene_context": product.get("scene_context"),
        "camera_style": product.get("camera_style"),
        "camera_behavior": product.get("camera_behavior"),
        "camera_shot": product.get("camera_shot"),
        "section_4_hint": product.get("section_4_hint"),
        "section_5_physics_hint": product.get("section_5_physics_hint"),
        "section_6_copy_hint": product.get("section_6_copy_hint"),
        "section_9_overlay_hint": product.get("section_9_overlay_hint"),
        "mapping_status": product.get("mapping_status"),
        "mapping_missing_fields": _json_load_list(product.get("mapping_missing_fields")),
    }


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
    source_lane: str | None = None,
    readiness: str | None = None,
    include_archived: bool = False,
    lifecycle_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    requested_source = (source or "").strip().upper() or None
    requested_source_lane = (source_lane or "").strip().upper() or None
    db_source = _normalize_source(requested_source) if requested_source in {"FASTMOSS", "MANUAL", "TIKTOKSHOP", "IMPORTED"} else None
    requested_lifecycle = (lifecycle_status or "").strip().upper() or None
    db_include_archived = include_archived or requested_lifecycle == "ARCHIVED"
    db_products = await crud.list_products(
        source=db_source,
        include_archived=db_include_archived,
        lifecycle_status=requested_lifecycle,
    )
    enriched_all = [await _enrich_product_cached(product) for product in db_products]
    merged_products = await _merge_catalog_products(
        enriched_all,
        requested_source=requested_source,
        requested_source_lane=requested_source_lane,
    )
    filtered_all = _filter_products_for_catalog(
        merged_products,
        query=q,
        source=requested_source,
        source_lane=requested_source_lane,
        readiness=readiness,
        include_archived=db_include_archived,
        lifecycle_status=requested_lifecycle,
    )
    total = len(filtered_all)
    enriched = []
    for product in filtered_all[offset:offset + limit]:
        refreshed_product = await _refresh_claim_safe_product_row_if_needed(product)
        if refreshed_product is product:
            enriched.append(product)
            continue
        # The claim-safe check returns a fresh DB row for EVERY row that has a
        # payload (even when nothing changed), so this branch fires for the whole
        # page. Use the cached enricher: unchanged rows keep the same mutation-key
        # and hit the cache; genuinely refreshed rows bump claim_safe_copy_updated_at
        # and re-enrich correctly.
        enriched.append(await _enrich_product_cached(refreshed_product))

    # Annotate every row with the shared Product Truth Gateway lifecycle state so
    # the catalog surface cannot silently disagree with the read model / preview.
    from agent.services.product_catalog_read_model import derive_catalog_state

    for item in enriched:
        item["catalog_state"] = derive_catalog_state(item)

    return {
        "total_count": total,
        "returned_count": len(enriched),
        "has_pagination": (offset + len(enriched)) < total,
        "limit": limit,
        "offset": offset,
        "items": enriched,
    }


def _catalog_priority(product: dict[str, Any]) -> tuple[int, int, int, int, int]:
    source = (product.get("source") or "").upper()
    prompt_status = product.get("prompt_readiness_status")
    image_status = product.get("image_readiness_status")
    lifecycle_rank = 1 if resolve_lifecycle_status(product) == "ARCHIVED" else 0

    source_rank = {
        "FASTMOSS": 0,
        "IMPORTED": 1,
        "MANUAL": 2,
        "TIKTOKSHOP": 3,
    }.get(source, 4)
    prompt_rank = {"READY": 0, "NEEDS_REVIEW": 1}.get(prompt_status, 2)
    image_rank = 0 if image_status in {"IMAGE_READY", "IMAGE_CACHE_READY"} else 1
    test_rank = 1 if product.get("is_test_product") else 0
    return (lifecycle_rank, test_rank, source_rank, prompt_rank, image_rank)


def _matches_catalog_source(product: dict[str, Any], requested_source: str | None) -> bool:
    if requested_source == "ALL":
        return True
    if requested_source == "TEST":
        return bool(product.get("is_test_product"))
    if product.get("is_test_product"):
        return False
    if not requested_source:
        return True
    return (product.get("source") or "").upper() == requested_source


def _matches_catalog_source_lane(
    product: dict[str, Any],
    requested_source_lane: str | None,
) -> bool:
    if not requested_source_lane or requested_source_lane == "ALL":
        return True
    return (product.get("source_lane") or product.get("source") or "").upper() == requested_source_lane


_SEARCH_ALIAS_PATH = BASE_DIR / "agent" / "authority" / "PRODUCT_SEARCH_ALIASES.json"
_SEARCH_ALIAS_CACHE: dict[str, list[str]] | None = None


def _load_search_aliases() -> dict[str, list[str]]:
    """Search-only synonym index: canonical ``raw_product_title`` (lowercased)
    -> extra search terms. Read once and cached. These aliases widen catalog
    search matching ONLY; they are never used for display, product identity,
    claim-safe copy, or prompt compilation."""
    global _SEARCH_ALIAS_CACHE
    if _SEARCH_ALIAS_CACHE is None:
        aliases: dict[str, list[str]] = {}
        try:
            raw = json.loads(_SEARCH_ALIAS_PATH.read_text(encoding="utf-8"))
            for title, terms in (raw.get("aliases") or {}).items():
                if isinstance(terms, list):
                    aliases[str(title).strip().lower()] = [
                        str(term).lower() for term in terms
                    ]
        except (OSError, ValueError):
            aliases = {}
        _SEARCH_ALIAS_CACHE = aliases
    return _SEARCH_ALIAS_CACHE


def _matches_catalog_query(product: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    needle = query.lower()
    haystacks = [
        product.get("raw_product_title"),
        product.get("product_display_name"),
        product.get("product_short_name"),
        product.get("shop_name"),
        product.get("source_url"),
        product.get("source_lane"),
        product.get("source_label"),
    ]
    # Search-only synonyms (e.g. the "serum" marketing alias for the BOSMAX
    # HERBS 5ML roll-on) so a canonical row is findable by names that do not
    # appear in its identity fields. Display/identity are unchanged.
    title_key = str(product.get("raw_product_title") or "").strip().lower()
    haystacks.extend(_load_search_aliases().get(title_key, []))
    return any(needle in str(value or "").lower() for value in haystacks)


def _catalog_identity_keys(product: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("source_url", "tiktok_product_url", "raw_product_title", "product_short_name"):
        value = str(product.get(field) or "").strip().lower()
        if value:
            keys.add(f"{field}:{value}")
    return keys


async def _merge_catalog_products(
    persisted_products: list[dict[str, Any]],
    *,
    requested_source: str | None,
    requested_source_lane: str | None,
) -> list[dict[str, Any]]:
    include_fastmoss_reference = (
        requested_source in {None, "ALL", "FASTMOSS"}
        and requested_source_lane in {None, "ALL", FASTMOSS_REFERENCE_LANE}
    ) or requested_source_lane == FASTMOSS_REFERENCE_LANE
    if not include_fastmoss_reference:
        return persisted_products

    reference_products = await list_fastmoss_reference_products(limit=500)
    seen_keys = {
        identity_key
        for product in persisted_products
        for identity_key in _catalog_identity_keys(product)
    }
    merged = list(persisted_products)
    for reference_product in reference_products:
        if _catalog_identity_keys(reference_product) & seen_keys:
            continue
        merged.append(reference_product)
    return merged


def _filter_products_for_catalog(
    products: list[dict[str, Any]],
    *,
    query: str | None,
    source: str | None,
    source_lane: str | None,
    readiness: str | None,
    include_archived: bool = False,
    lifecycle_status: str | None = None,
) -> list[dict[str, Any]]:
    filtered = [
        product
        for product in products
        if _matches_catalog_source(product, source)
        and _matches_catalog_source_lane(product, source_lane)
        and _matches_catalog_query(product, query)
    ]
    if lifecycle_status:
        filtered = [product for product in filtered if resolve_lifecycle_status(product) == lifecycle_status]
    elif not include_archived:
        filtered = [product for product in filtered if not is_product_archived(product)]
    if readiness:
        filtered = [product for product in filtered if product.get("prompt_readiness_status") == readiness]

    filtered.sort(key=lambda product: product.get("updated_at") or product.get("created_at") or "", reverse=True)
    filtered.sort(key=_catalog_priority)
    return filtered


@router.get("")
async def list_products(
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    source_lane: str | None = Query(default=None),
    readiness: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    lifecycle_status: str | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
):
    return await _list_products_response(
        q=q,
        source=source,
        source_lane=source_lane,
        readiness=readiness,
        include_archived=include_archived,
        lifecycle_status=lifecycle_status,
        limit=limit,
        offset=offset,
    )


@router.get("/search")
async def search_products(
    q: str | None = Query(default=None),
    source: str | None = Query(default=None),
    source_lane: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    lifecycle_status: str | None = Query(default=None),
    limit: int = Query(default=25),
    offset: int = Query(default=0),
):
    return await _list_products_response(
        q=q,
        source=source,
        source_lane=source_lane,
        include_archived=include_archived,
        lifecycle_status=lifecycle_status,
        limit=limit,
        offset=offset,
    )


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


@router.post("/backfill-mapping")
async def backfill_product_mapping(product_id: str | None = None):
    products = [await crud.get_product(product_id)] if product_id else await crud.list_products(limit=5000, include_archived=False)
    products = [product for product in products if product]
    excluded_test_fixtures = 0
    if product_id is None:
        excluded_test_fixtures = sum(1 for product in products if _is_test_product(product))
        products = [product for product in products if not _is_test_product(product)]
    processed = 0
    ready = 0
    needs_review = 0
    blocked = 0
    sample: list[dict[str, Any]] = []

    for product in products:
        enriched = await _enrich_product(product, persist=True)
        processed += 1
        status = enriched.get("mapping_status")
        if status == "READY":
            ready += 1
        elif status == "NEEDS_REVIEW":
            needs_review += 1
        else:
            blocked += 1
        if len(sample) < 10:
            sample.append({
                "product_id": enriched.get("id"),
                "product_short_name": enriched.get("product_short_name"),
                "mapping_status": status,
                "mapping_missing_fields": enriched.get("mapping_missing_fields") or [],
            })

    return {
        "ok": True,
        "total_products_processed": processed,
        "total_mapping_ready": ready,
        "total_needs_review": needs_review,
        "total_blocked": blocked,
        "excluded_test_fixtures": excluded_test_fixtures,
        "sample": sample,
    }


@router.get("/mapping-summary")
async def get_product_mapping_summary(sample_limit: int = Query(default=30, ge=1, le=100)):
    raw_products = await crud.list_products(limit=10000, include_archived=False)
    enriched_products = [await _enrich_product(product, persist=False) for product in raw_products]
    return build_mapping_summary(raw_products, enriched_products, sample_limit=sample_limit)


@router.post("/{product_id}/repair-mapping")
async def repair_product_mapping(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    enriched = await _enrich_product(product, persist=True)
    return {
        "ok": True,
        "product": enriched,
        "preflight": build_product_preflight(enriched),
    }


@router.get("/{product_id}/mapping-audit")
async def get_product_mapping_audit(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    proposed = await _enrich_product(product, persist=False)
    current = _stored_mapping_snapshot(product)
    return {
        "product_id": product_id,
        "product": product.get("raw_product_title"),
        "audit": _mapping_audit_payload(current, proposed),
        "before": current,
        "after": proposed,
    }


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
        updated = 0
        for entry in products:
            raw_title = entry.raw_product_title or entry.product_name
            commission_amount = entry.commission_amount if entry.commission_amount is not None else _derive_commission_amount(entry.avg_price_rm, entry.commission_rate)
            payload = dict(
                raw_product_title=raw_title,
                source="FASTMOSS",
                source_url=entry.source_url,
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
                image_url=entry.image_url,
                tiktok_product_url=entry.tiktok_product_url,
                commission_rate=entry.commission_rate,
                commission=entry.commission_rate,
                commission_amount=commission_amount,
            )
            existing = await _find_product_by_exact_title(raw_title)
            if existing:
                updated_product = await crud.update_product(existing["id"], **payload)
                await _enrich_product(updated_product, persist=True)
                updated += 1
                continue

            created = await crud.create_product(**payload)
            await _enrich_product(created, persist=True)
            imported += 1
        return {"ok": True, "imported": imported, "updated": updated, "total": len(products)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/import-image-map")
async def import_image_map(file: UploadFile = File(...)):
    rows = await _parse_image_map_upload(file)
    products = await crud.list_products(limit=1000)
    imported = 0
    warnings: list[str] = []

    for index, row in enumerate(rows, start=2):
        product, warning = await _find_image_map_match(row, products)
        if warning:
            warnings.append(f"row {index}: {warning}")
            continue
        if not product:
            warnings.append(f"row {index}: no product match")
            continue

        image_url = (row.get("image_url") or "").strip() or None
        source_url = (row.get("source_url") or "").strip() or product.get("source_url") or None
        commission_rate = (row.get("commission_rate") or "").strip() or product.get("commission_rate") or product.get("commission") or None
        commission_amount_raw = (row.get("commission_amount") or "").strip()
        commission_amount = product.get("commission_amount")
        if commission_amount_raw:
            try:
                commission_amount = float(commission_amount_raw)
            except ValueError:
                warnings.append(f"row {index}: invalid commission_amount '{commission_amount_raw}'")
        elif commission_amount is None:
            commission_amount = _derive_commission_amount(product.get("price") or product.get("price_min"), commission_rate)

        updated = await crud.update_product(
            product["id"],
            image_url=image_url,
            source_url=source_url,
            commission_rate=commission_rate,
            commission=commission_rate,
            commission_amount=commission_amount,
            image_asset_status="UNRESOLVED",
            image_failure_detail=None,
            asset_status=product.get("asset_status") or "UNRESOLVED",
        )
        await _enrich_product(updated, persist=True)
        imported += 1

    return {
        "ok": True,
        "imported": imported,
        "warnings": warnings,
        "total_rows": len(rows),
    }


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
            "product_type", "product_type_id", "silo", "trigger_id", "formula", "mode_recommendations", "copywriting_angle",
            "claim_risk_level", "mapping_source", "mapping_confidence", "mapping_review_status", "mapping_status",
            "mapping_missing_fields", "handling_notes", "scene_context", "camera_style", "camera_behavior", "camera_shot",
            "section_4_hint", "section_5_physics_hint", "section_6_copy_hint", "section_9_overlay_hint",
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
    product = await _refresh_claim_safe_product_row_if_needed(product)
    return await _enrich_product(product, persist=True)


@router.get("/{product_id}/lifecycle")
async def get_product_lifecycle_status(product_id: str):
    return await get_product_lifecycle(product_id)


@router.post("/{product_id}/archive")
async def archive_product_lifecycle(product_id: str, data: ProductLifecycleActionRequest):
    return await archive_product_row(
        product_id,
        reason=data.reason,
        confirmation_phrase=data.confirmation_phrase,
    )


@router.post("/{product_id}/unarchive")
async def unarchive_product_lifecycle(product_id: str, data: ProductLifecycleActionRequest):
    return await unarchive_product_row(
        product_id,
        reason=data.reason,
        confirmation_phrase=data.confirmation_phrase,
    )


@router.post("/{product_id}/delete-test-row")
async def delete_test_row(product_id: str, data: ProductLifecycleActionRequest):
    return await delete_test_product_row(
        product_id,
        reason=data.reason,
        confirmation_phrase=data.confirmation_phrase,
    )


@router.post("/{product_id}/delete")
async def delete_product(product_id: str, data: ProductLifecycleActionRequest):
    return await delete_product_permanent_row(
        product_id,
        reason=data.reason,
        confirmation_phrase=data.confirmation_phrase,
    )


@router.get("/{product_id}/image")
async def get_product_image(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    enriched = await _enrich_product(product)
    cached_path = resolve_cached_image_path(enriched)
    if cached_path and cached_path.exists():
        return FileResponse(cached_path)

    raise HTTPException(
        status_code=404,
        detail={
            "status": enriched.get("image_readiness_status") or "IMAGE_NOT_AVAILABLE",
            "reason": enriched.get("image_readiness_detail") or "No cached product image found.",
            "local_cache_present": bool(enriched.get("local_image_path")),
            "remote_image_url_present": bool(enriched.get("image_url")),
        },
    )


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
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(status_code=409, detail="PRODUCT_ARCHIVED")
    return await resolve_product_assets(product_id)


@router.post("/{product_id}/upload-to-flow")
async def upload_to_flow(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(status_code=409, detail="PRODUCT_ARCHIVED")
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
    if is_product_archived(product):
        raise HTTPException(
            status_code=409,
            detail={
                "product_id": product.get("id") or product_id,
                "lifecycle_status": resolve_lifecycle_status(product),
                "safe_to_generate_prompt": False,
                "blocker": "PRODUCT_ARCHIVED",
            },
        )

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


@router.get("/{product_id}/claim-safe-rewrite-preview")
async def get_claim_safe_rewrite_preview(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(status_code=409, detail="PRODUCT_ARCHIVED")
    return await preview_claim_safe_rewrite(product_id)


@router.post("/{product_id}/claim-safe-rewrite-approval")
async def post_claim_safe_rewrite_approval(product_id: str, request: ClaimSafeRewriteApprovalRequest):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(status_code=409, detail="PRODUCT_ARCHIVED")
    try:
        result = await approve_claim_safe_rewrite(
            product_id,
            confirmation_phrase=request.confirmation_phrase,
            approval_note=request.approval_note,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(exc),
                "approval_phrase": CLAIM_SAFE_APPROVAL_PHRASE,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    refreshed_product = await crud.get_product(product_id)
    readiness = await PromptPipelineReadinessService.get_readiness_report(refreshed_product or product)
    result["readiness_after_approval"] = readiness
    return result


@router.post("/{product_id}/production-prompt-approval")
async def post_production_prompt_approval(product_id: str, request: ProductionPromptApprovalRequest):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(status_code=409, detail="PRODUCT_ARCHIVED")
    try:
        result = await approve_production_prompt_package(
            product_id,
            approval_phrase=request.approval_phrase,
            approved_modes=request.approved_modes,
            reviewer_note=request.reviewer_note,
            confirm_no_google_flow_execution=request.confirm_no_google_flow_execution,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(exc),
                "approval_phrase": PRODUCTION_PROMPT_APPROVAL_PHRASE,
            },
        ) from exc
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc
    refreshed_product = await crud.get_product(product_id)
    readiness = await PromptPipelineReadinessService.get_readiness_report(refreshed_product or product)
    result["readiness_after_approval"] = readiness
    return result


@router.get("/{product_id}/approved-package")
async def get_product_approved_package(product_id: str, mode: str = "T2V"):
    product = await crud.get_product(product_id)
    if not product and not is_fastmoss_reference_product_id(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(
            status_code=409,
            detail={
                "product_id": product_id,
                "lifecycle_status": resolve_lifecycle_status(product),
                "blocker": "PRODUCT_ARCHIVED",
            },
        )
    try:
        return await get_approved_product_package(product_id, mode)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if message == "PRODUCT_NOT_FOUND" else 409
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.get("/{product_id}/prompt-dryrun")
async def get_prompt_dryrun(product_id: str, mode: str = "T2V"):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if is_product_archived(product):
        raise HTTPException(
            status_code=409,
            detail={
                "product_id": product_id,
                "lifecycle_status": resolve_lifecycle_status(product),
                "safe_to_generate_prompt": False,
                "blocker": "PRODUCT_ARCHIVED",
            },
        )
    result = await generate_prompt_dryrun(product_id, mode)
    if result.get("status") == "CLAIM_SAFE_COPY_REWRITE_REQUIRED":
        raise HTTPException(status_code=409, detail=result)
    if result.get("status") == "INVALID_MODE":
        raise HTTPException(status_code=400, detail=result)
    return result

@router.get("/{product_id}/prompt-readiness")
async def get_product_prompt_readiness(product_id: str):
    product = await _find_product_by_lookup(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return await PromptPipelineReadinessService.get_readiness_report(product)

@router.get("/{product_id}/truth-audit")
async def get_product_truth_audit(product_id: str):
    product = await _find_product_by_lookup(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    from agent.services.product_truth_service import ProductTruthService
    profile = ProductTruthService.build_computed_profile(dict(product))
    return profile
