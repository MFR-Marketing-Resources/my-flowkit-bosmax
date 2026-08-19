"""Product Mascot Key Visual API — a minimal per-product sibling of the Official
Product Visual. Preview / Upload / Replace / Remove only. No generation, no
provider/model selection, no prompt editor, no job history.

Routes (mounted under /api): /api/products/{product_id}/mascot-key-visual
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.services import product_mascot_service as svc

router = APIRouter(prefix="/products", tags=["product-mascot"])


class MascotSetRequest(BaseModel):
    image_base64: str
    file_name: Optional[str] = None
    display_name: Optional[str] = None


@router.get("/{product_id}/mascot-key-visual")
async def get_product_mascot(product_id: str) -> dict[str, Any]:
    """Return the current mascot (fail-closed: absent/stale/missing bytes → null)."""
    mascot = await svc.get_current_product_mascot(product_id)
    return {"product_id": product_id, "available": mascot is not None, "mascot": mascot}


@router.post("/{product_id}/mascot-key-visual")
async def set_product_mascot(product_id: str, body: MascotSetRequest) -> dict[str, Any]:
    """Upload or replace the product's mascot (creates a fresh product-bound asset)."""
    try:
        mascot = await svc.set_product_mascot(
            product_id,
            image_base64=body.image_base64,
            file_name=body.file_name,
            display_name=body.display_name,
        )
    except ValueError as exc:
        code = str(exc)
        status = 404 if code == "PRODUCT_NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail=code) from exc
    return {"product_id": product_id, "available": True, "mascot": mascot}


@router.delete("/{product_id}/mascot-key-visual")
async def remove_product_mascot(product_id: str) -> dict[str, Any]:
    """Remove the current mascot pointer and archive the prior mascot asset."""
    removed = await svc.remove_product_mascot(product_id)
    return {"product_id": product_id, "available": False, "removed": removed, "mascot": None}
