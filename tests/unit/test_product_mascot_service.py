"""Feature A — Product Mascot Key Visual: storage, single-current invariant,
authority separation, and fail-closed durability."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.db import crud
from agent.services import product_mascot_service as svc
from agent.services.creative_asset_service import (
    get_creative_asset,
    get_creative_asset_file_path,
    list_creative_assets,
)
from agent.services.product_visual_grounding_resolver import (
    _find_linked_approved_creative_asset,
)

# 1x1 transparent PNG.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)


async def _seed_product(title: str = "Mascot Test Product") -> str:
    row = await crud.create_product(
        raw_product_title=title,
        product_display_name=title,
        product_short_name=title[:20],
    )
    return row["id"]


async def _set(product_id: str, name: str = "mascot.png") -> dict:
    return await svc.set_product_mascot(
        product_id, image_base64=PNG_B64, file_name=name, display_name=None
    )


async def test_upload_creates_product_bound_mascot_with_correct_role_and_subtype():
    product_id = await _seed_product()
    mascot = await _set(product_id)

    assert mascot["product_id"] == product_id
    asset = await get_creative_asset(mascot["asset_id"])
    assert asset is not None
    assert asset.product_id == product_id
    # LOCKED: mascot is a CHARACTER_REFERENCE, never PRODUCT_REFERENCE.
    assert asset.semantic_role == "CHARACTER_REFERENCE"
    assert asset.semantic_role != "PRODUCT_REFERENCE"
    assert asset.asset_subtype == "PRODUCT_MASCOT_KEY_VISUAL"


async def test_current_pointer_resolves_exactly_one_mascot():
    product_id = await _seed_product()
    await _set(product_id)
    pointer = await crud.get_product_mascot_key_visual(product_id)
    assert pointer is not None
    current = await svc.get_current_product_mascot(product_id)
    assert current is not None
    assert current["asset_id"] == pointer["creative_asset_id"]


async def test_replace_switches_current_and_supersedes_prior():
    product_id = await _seed_product()
    first = await _set(product_id, name="first.png")
    second = await _set(product_id, name="second.png")

    assert first["asset_id"] != second["asset_id"]
    pointer = await crud.get_product_mascot_key_visual(product_id)
    assert pointer["creative_asset_id"] == second["asset_id"]

    current = await svc.get_current_product_mascot(product_id)
    assert current["asset_id"] == second["asset_id"]

    # The previous mascot asset is archived and no longer current.
    prior = await get_creative_asset(first["asset_id"])
    assert prior is not None
    assert prior.status == "ARCHIVED"

    # Exactly one ACTIVE mascot asset remains for this product.
    active = await list_creative_assets(
        semantic_role="CHARACTER_REFERENCE", status="ACTIVE", product_id=product_id
    )
    mascots = [a for a in active if a.asset_subtype == "PRODUCT_MASCOT_KEY_VISUAL"]
    assert len(mascots) == 1
    assert mascots[0].asset_id == second["asset_id"]


async def test_remove_clears_current_and_archives_prior():
    product_id = await _seed_product()
    m = await _set(product_id)
    removed = await svc.remove_product_mascot(product_id)
    assert removed is True

    assert await crud.get_product_mascot_key_visual(product_id) is None
    assert await svc.get_current_product_mascot(product_id) is None
    asset = await get_creative_asset(m["asset_id"])
    assert asset.status == "ARCHIVED"

    # Removing when there is no mascot is a no-op, not an error.
    assert await svc.remove_product_mascot(product_id) is False


async def test_two_products_have_independent_mascots():
    p1 = await _seed_product("Product One")
    p2 = await _seed_product("Product Two")
    m1 = await _set(p1)
    m2 = await _set(p2)

    assert m1["asset_id"] != m2["asset_id"]
    a1 = await get_creative_asset(m1["asset_id"])
    a2 = await get_creative_asset(m2["asset_id"])
    # Each mascot asset is bound to its own product — never cross-bound.
    assert a1.product_id == p1
    assert a2.product_id == p2
    assert (await svc.get_current_product_mascot(p1))["asset_id"] == m1["asset_id"]
    assert (await svc.get_current_product_mascot(p2))["asset_id"] == m2["asset_id"]


async def test_missing_bytes_fail_closed():
    product_id = await _seed_product()
    m = await _set(product_id)
    # Simulate a stranded byte store: delete the on-disk file.
    path = await get_creative_asset_file_path(m["asset_id"])
    assert path is not None and path.exists()
    Path(path).unlink()

    # Resolution must fail closed — a stale pointer is NOT a phantom mascot.
    assert await svc.get_current_product_mascot(product_id) is None
    with pytest.raises(svc.ProductMascotUnavailableError) as exc:
        await svc.resolve_mascot_for_montage(product_id)
    assert exc.value.code == "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED"


async def test_resolve_for_montage_fail_closed_when_absent():
    product_id = await _seed_product()
    with pytest.raises(svc.ProductMascotUnavailableError) as exc:
        await svc.resolve_mascot_for_montage(product_id)
    assert exc.value.code == "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED"


async def test_mascot_never_enters_official_product_visual_ladder():
    product_id = await _seed_product()
    await _set(product_id)

    # The Official Product Visual resolver only sweeps APPROVED+ACTIVE
    # PRODUCT_REFERENCE creative assets. A mascot (CHARACTER_REFERENCE) must be
    # invisible to it.
    assert _find_linked_approved_creative_asset(product_id) is None

    # And no PRODUCT_REFERENCE row was created for this product.
    product_refs = await list_creative_assets(
        semantic_role="PRODUCT_REFERENCE", product_id=product_id
    )
    assert product_refs == []

    # No Official Product Visual truth-lock was created as a side effect.
    assert await crud.get_product_mascot_key_visual(product_id) is not None
    lock = await crud._get("product_visual_truth_lock", "product_id", product_id)
    assert lock is None


async def test_set_mascot_unknown_product_raises():
    with pytest.raises(ValueError) as exc:
        await _set("nonexistent-product-id")
    assert str(exc.value) == "PRODUCT_NOT_FOUND"
