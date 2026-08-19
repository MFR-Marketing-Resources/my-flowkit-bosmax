"""Product Mascot Key Visual — a creative-derivative character anchor per product.

Authority separation (LOCKED V1):
- The Official Product Visual (``product_visual_truth_lock`` + the
  ``product_visual_grounding_resolver`` ladder) remains the sole Product-Truth
  visual authority. The mascot is a CREATIVE DERIVATIVE and must NEVER replace,
  mutate, or masquerade as it.
- The mascot is stored as a ``creative_asset`` with
  ``semantic_role='CHARACTER_REFERENCE'`` and
  ``asset_subtype='PRODUCT_MASCOT_KEY_VISUAL'`` — deliberately NOT
  ``PRODUCT_REFERENCE``, because the Official Product Visual resolver sweeps in
  approved+active ``PRODUCT_REFERENCE`` creative assets
  (``_find_linked_approved_creative_asset``). CHARACTER_REFERENCE keeps the
  mascot out of that ladder.
- A tiny product-scoped pointer table (``product_mascot_key_visual``, PK
  product_id) enforces exactly zero-or-one CURRENT mascot per product.

This module reuses the existing Creative Asset store for bytes/metadata — it does
NOT introduce a new generic media subsystem.
"""
from __future__ import annotations

from typing import Any, Optional

from agent.db import crud
from agent.models.creative_asset import CreativeAssetCreateRequest, CreativeAssetRecord
from agent.services.creative_asset_service import (
    archive_creative_asset,
    create_creative_asset,
    get_creative_asset,
    get_creative_asset_file_path,
)

MASCOT_SEMANTIC_ROLE = "CHARACTER_REFERENCE"
MASCOT_ASSET_SUBTYPE = "PRODUCT_MASCOT_KEY_VISUAL"
ERR_MASCOT_REQUIRED = "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED"


class ProductMascotUnavailableError(Exception):
    """Raised when a product has no resolvable current Product Mascot Key Visual.

    Carries the fail-closed contract code the Montage lane surfaces to operators.
    """

    code = ERR_MASCOT_REQUIRED

    def __init__(self, product_id: str, detail: str = "") -> None:
        self.product_id = product_id
        self.detail = detail
        message = (
            f"{self.code}: no current Product Mascot Key Visual for product "
            f"{product_id!r}"
        )
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


def _mascot_public(asset: CreativeAssetRecord, pointer: dict[str, Any]) -> dict[str, Any]:
    """Compact, transport-friendly view of the current mascot."""
    return {
        "product_id": pointer.get("product_id"),
        "asset_id": asset.asset_id,
        "creative_asset_id": asset.asset_id,
        "media_id": asset.media_id,
        "local_file_path": asset.local_file_path,
        "display_name": asset.display_name,
        "preview_url": asset.preview_url,
        "download_url": asset.download_url,
        "asset_subtype": asset.asset_subtype,
        "semantic_role": asset.semantic_role,
        "review_status": asset.review_status,
        "status": asset.status,
        "created_at": pointer.get("created_at"),
        "updated_at": pointer.get("updated_at"),
    }


async def _bytes_available(asset: CreativeAssetRecord) -> bool:
    """Fail-closed durability check: the mascot must have real, reachable bytes.

    A stale pointer or a missing/empty local file means the mascot is
    unavailable — never silently treated as present.
    """
    path = await get_creative_asset_file_path(asset.asset_id)
    if path is not None:
        try:
            if path.stat().st_size > 0:
                return True
        except OSError:
            return False
    # A resolved Flow media_id is a valid transport even without a local file.
    return bool(asset.media_id)


async def get_current_product_mascot(product_id: str) -> Optional[dict[str, Any]]:
    """Resolve the product's CURRENT mascot, or None if absent/stale/unavailable.

    Fail-closed: a dangling pointer (asset missing or archived) or missing bytes
    resolves to None rather than a phantom mascot.
    """
    pointer = await crud.get_product_mascot_key_visual(product_id)
    if not pointer:
        return None
    asset_id = pointer.get("creative_asset_id")
    if not asset_id:
        return None
    asset = await get_creative_asset(asset_id)
    if asset is None or asset.status == "ARCHIVED":
        return None
    if not await _bytes_available(asset):
        return None
    return _mascot_public(asset, pointer)


async def set_product_mascot(
    product_id: str,
    *,
    image_base64: str,
    file_name: Optional[str] = None,
    display_name: Optional[str] = None,
) -> dict[str, Any]:
    """Upload/replace the product's mascot.

    Creates a fresh product-bound CHARACTER_REFERENCE creative_asset, atomically
    repoints the current-mascot pointer to it, then archives the prior mascot
    asset. Guarantees exactly one current mascot per product.
    """
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    if not (image_base64 or "").strip():
        raise ValueError("MASCOT_IMAGE_REQUIRED")

    prior = await crud.get_product_mascot_key_visual(product_id)
    prior_asset_id = prior.get("creative_asset_id") if prior else None

    label = display_name or (
        f"Product Mascot — {product.get('product_display_name') or product.get('raw_product_title') or product_id}"
    )
    request = CreativeAssetCreateRequest(
        semantic_role=MASCOT_SEMANTIC_ROLE,
        display_name=label[:200],
        description="Product Mascot Key Visual (creative derivative; not the Official Product Visual)",
        source_type="UPLOAD",
        storage_kind="LOCAL_FILE",
        product_id=product_id,
        asset_subtype=MASCOT_ASSET_SUBTYPE,
        review_status="APPROVED",
        image_base64=image_base64,
        file_name=file_name,
    )
    asset = await create_creative_asset(request)

    # Atomic repoint FIRST so the pointer always references a valid asset.
    await crud.upsert_product_mascot_key_visual(
        product_id,
        creative_asset_id=asset.asset_id,
        media_id=asset.media_id,
    )
    # Supersede the prior mascot asset (never the Official Product Visual).
    if prior_asset_id and prior_asset_id != asset.asset_id:
        try:
            await archive_creative_asset(prior_asset_id)
        except ValueError:
            pass  # already gone — pointer already moved

    pointer = await crud.get_product_mascot_key_visual(product_id)
    return _mascot_public(asset, pointer or {"product_id": product_id})


async def remove_product_mascot(product_id: str) -> bool:
    """Clear the current mascot pointer and archive the prior mascot asset."""
    pointer = await crud.get_product_mascot_key_visual(product_id)
    if not pointer:
        return False
    asset_id = pointer.get("creative_asset_id")
    await crud.delete_product_mascot_key_visual(product_id)
    if asset_id:
        try:
            await archive_creative_asset(asset_id)
        except ValueError:
            pass
    return True


async def resolve_mascot_for_montage(product_id: str) -> dict[str, Any]:
    """Montage-facing fail-closed resolver.

    Returns the current mascot reference, or raises
    ``ProductMascotUnavailableError`` (contract code
    ``PRODUCT_MASCOT_KEY_VISUAL_REQUIRED``). NEVER falls back to the Official
    Product Visual.
    """
    mascot = await get_current_product_mascot(product_id)
    if mascot is None:
        raise ProductMascotUnavailableError(product_id)
    return mascot
