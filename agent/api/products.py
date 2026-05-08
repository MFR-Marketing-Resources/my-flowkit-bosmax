from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from agent.db import crud
from agent.services.product_intelligence import generate_product_prompt, resolve_product_assets, upload_product_to_flow

router = APIRouter(prefix="/products", tags=["products"])

@router.get("/search")
async def search_products(q: str = Query(None)):
    """Search for products in the catalog."""
    return await crud.list_products(query=q)

@router.get("/{product_id}")
async def get_product(product_id: str):
    """Get product details by ID."""
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@router.post("/manual")
async def create_manual_product(data: dict):
    """Manually create a custom product."""
    if "raw_product_title" not in data:
        raise HTTPException(status_code=400, detail="Missing raw_product_title")
    
    return await crud.create_product(
        raw_product_title=data["raw_product_title"],
        source="MANUAL_PROJECT",
        **{k: v for k, v in data.items() if k != "raw_product_title"}
    )

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
    """Get a system-generated prompt for a product and mode."""
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    prompt = await generate_product_prompt(product, mode)
    return {"product_id": product_id, "mode": mode, "prompt": prompt}

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
