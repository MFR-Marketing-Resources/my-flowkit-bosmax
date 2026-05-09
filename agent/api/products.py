from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agent.db import crud
from agent.services.product_intelligence import generate_product_prompt, resolve_product_assets, upload_product_to_flow
from agent.services.product_mapping import resolve_product_mapping

router = APIRouter(prefix="/products", tags=["products"])


class ProductMapRequest(BaseModel):
    product_id: str | None = None
    product_name: str | None = None
    raw_product_title: str | None = None
    product_short_name: str | None = None
    source: str | None = None
    category: str | None = None
    subcategory: str | None = None
    type: str | None = None
    override_category: str | None = None
    override_subcategory: str | None = None
    override_type: str | None = None
    persist: bool = False


def _serialize_mapping(product: dict[str, Any] | None, mapping: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product or {})
    payload.update(mapping)
    return payload


async def _persist_mapping(product_id: str, mapping: dict[str, Any]) -> None:
    await crud.update_product(
        product_id,
        product_short_name=mapping.get("product_short_name") or None,
        category=mapping.get("category") or None,
        subcategory=mapping.get("subcategory") or None,
        type=mapping.get("type") or None,
    )


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
    if persist and product and product.get("id"):
        await _persist_mapping(product["id"], mapping)
    return mapping

@router.get("/search")
async def search_products(q: str = Query(None)):
    """Search for products in the catalog."""
    products = await crud.list_products(query=q)
    return [
        _serialize_mapping(
            product,
            resolve_product_mapping(product=product, source_hint=product.get("source")),
        )
        for product in products
    ]


@router.post("/map")
async def map_product(data: ProductMapRequest):
    product = await crud.get_product(data.product_id) if data.product_id else None
    if data.product_id and not product:
        raise HTTPException(status_code=404, detail="Product not found")

    raw_product_title = data.raw_product_title or data.product_name
    if not product and not raw_product_title:
        raise HTTPException(status_code=400, detail="Missing product_name or product_id")

    mapping = await _resolve_mapping_for_product(
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
            raw_product_title=mapping["raw_product_title"],
            source="MANUAL_PROJECT",
            product_display_name=" ".join(mapping["raw_product_title"].split()[:9]).strip(),
            product_short_name=mapping["product_short_name"],
            category=mapping.get("category") or None,
            subcategory=mapping.get("subcategory") or None,
            type=mapping.get("type") or None,
        )
        mapping["product_id"] = created["id"]
        return _serialize_mapping(created, mapping)

    return _serialize_mapping(product, mapping)


@router.get("/{product_id}/mapping")
async def get_product_mapping(product_id: str):
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    mapping = await _resolve_mapping_for_product(
        product,
        source_hint=product.get("source"),
        persist=True,
    )
    return _serialize_mapping(product, mapping)

@router.get("/{product_id}")
async def get_product(product_id: str):
    """Get product details by ID."""
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    mapping = resolve_product_mapping(product=product, source_hint=product.get("source"))
    return _serialize_mapping(product, mapping)

@router.post("/manual")
async def create_manual_product(data: dict):
    """Manually create a custom product."""
    raw_product_title = data.get("raw_product_title") or data.get("product_name")
    if not raw_product_title:
        raise HTTPException(status_code=400, detail="Missing raw_product_title")

    mapping = resolve_product_mapping(
        product_name=raw_product_title,
        source_hint="MANUAL_PROJECT",
        overrides={
            "category": data.get("category"),
            "subcategory": data.get("subcategory"),
            "type": data.get("type"),
        },
    )

    created = await crud.create_product(
        raw_product_title=raw_product_title,
        source="MANUAL_PROJECT",
        product_display_name=" ".join(raw_product_title.split()[:9]).strip(),
        product_short_name=mapping["product_short_name"],
        category=mapping.get("category") or None,
        subcategory=mapping.get("subcategory") or None,
        type=mapping.get("type") or None,
        **{k: v for k, v in data.items() if k not in {"raw_product_title", "product_name", "category", "subcategory", "type"}}
    )
    mapping["product_id"] = created["id"]
    return _serialize_mapping(created, mapping)

@router.post("/{product_id}/resolve-assets")
async def resolve_assets(product_id: str):
    """Download product image and prepare local assets."""
    return await resolve_product_assets(product_id)

@router.post("/{product_id}/upload-to-flow")
async def upload_to_flow(product_id: str):
    """Upload product assets to Google Flow."""
    return await upload_product_to_flow(product_id)

@router.get("/{product_id}/prompt")
async def get_generated_prompt(product_id: str, mode: str = "F2V"):
    """Get a system-generated prompt for a product and mode.
    Supported modes: IMG, I2V, F2V, TRUE_F2V, GENERATE_VIDEO, GENERATE_VIDEO_REFS
    
    Product lookup order:
    1. product.id (exact)
    2. product_short_name (exact)
    3. product_display_name (exact)
    4. raw_product_title (exact)
    5. product_name (exact)
    6. Case-insensitive normalized match
    7. Contains/substring match
    """
    # First try exact ID match
    product = await crud.get_product(product_id)
    if product:
        # Found by ID
        lookup_method = "ID"
    else:
        # Get all products for fallback matching
        all_products = await crud.list_products()
        
        # Normalize search string
        search_normalized = product_id.lower().strip()
        
        # Try exact string matches first (case-insensitive)
        product = None
        lookup_method = None
        
        for field_name in ["product_short_name", "product_display_name", "raw_product_title", "product_name"]:
            for p in all_products:
                field_val = p.get(field_name, "")
                if field_val and field_val.lower().strip() == search_normalized:
                    product = p
                    lookup_method = field_name
                    break
            if product:
                break
        
        # If no exact match, try case-insensitive normalized match
        if not product:
            for p in all_products:
                for field_name in ["product_short_name", "product_display_name", "raw_product_title", "product_name"]:
                    field_val = p.get(field_name, "")
                    if not field_val:
                        continue
                    # Normalize both: lowercase, remove extra spaces
                    field_normalized = " ".join(field_val.lower().split())
                    if field_normalized == search_normalized:
                        product = p
                        lookup_method = f"{field_name} (normalized)"
                        break
                if product:
                    break
        
        # Last resort: contains/substring match
        if not product and len(search_normalized) >= 4:
            for p in all_products:
                for field_name in ["product_short_name", "product_display_name", "raw_product_title", "product_name"]:
                    field_val = p.get(field_name, "")
                    if field_val and search_normalized in field_val.lower():
                        product = p
                        lookup_method = f"{field_name} (contains)"
                        break
                if product:
                    break
    
    if not product:
        mapping = resolve_product_mapping(product_name=product_id, source_hint="MANUAL_PROJECT")
        if mapping.get("mapping_confidence") == "NEEDS_REVIEW":
            raise HTTPException(status_code=404, detail=f"Product not found: {product_id}")
        product = {
            "raw_product_title": mapping["raw_product_title"],
            "product_display_name": mapping["raw_product_title"],
            "product_short_name": mapping["product_short_name"],
            "category": mapping["category"],
        }

    # Normalize BOSMAX mode names to product intelligence modes
    mode_map = {
        "TRUE_F2V": "F2V",
        "GENERATE_VIDEO": "I2V",
        "GENERATE_VIDEO_REFS": "I2V",
    }
    normalized_mode = mode_map.get(mode, mode)

    prompt = await generate_product_prompt(product, normalized_mode)
    return {
        "product_id": product_id,
        "mode": mode,
        "prompt": prompt,
        "prompt_length": len(prompt),
        "prompt_source": "SYSTEM"
    }


@router.post("/import-fastmoss")
async def import_fastmoss_catalog():
    """Trigger the FastMoss catalog import script."""
    import subprocess
    import os
    try:
        # Run the builder script
        res = subprocess.run(["python", "scripts/build-product-catalog.py"], capture_output=True, text=True)
        if res.returncode != 0:
            return {"ok": False, "error": res.stderr}
        
        # Load the JSON and UPSERT into DB
        import json
        from agent.config import BASE_DIR
        catalog_path = BASE_DIR / "data" / "products" / "product_catalog.json"
        if not catalog_path.exists():
            return {"ok": False, "error": "Catalog file not found after script execution"}
            
        with open(catalog_path, 'r', encoding='utf-8') as f:
            products = json.load(f)
            
        count = 0
        for p in products:
            # Check if exists
            existing = await crud.list_products(query=p["raw_product_title"])
            if not existing:
                await crud.create_product(**p)
                count += 1
        
        return {"ok": True, "imported": count, "total": len(products)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
