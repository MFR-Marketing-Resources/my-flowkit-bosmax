"""Unit tests for ProductVisualGroundingResolver service."""
from __future__ import annotations

import pytest
from pathlib import Path
from agent.services.product_visual_grounding_resolver import (
    ProductVisualReferenceRequiredError,
    resolve_product_reference_image,
    resolve_product_visual_grounding,
)


def test_resolve_mwcb_product_visual_grounding():
    product = {
        "id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        "name": "Minyak Warisan Cap Burung 25ml",
        "product_display_name": "Minyak Warisan Cap Burung 25ml",
        "category": "Traditional Herbal Oil",
        "pack_size_ml": 25,
    }
    bundle = resolve_product_visual_grounding(product)
    assert bundle.product_id == "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    assert "MWCB" in bundle.identity_lock or "Cap Burung" in bundle.identity_lock
    assert bundle.product_reference["validation_status"] == "VALIDATED"
    assert bundle.product_reference["sha256"] != ""


def test_resolve_generic_db_product_with_image_url():
    product = {
        "id": "generic-prod-12345",
        "product_display_name": "Sambal Nyet Berapi by Khairulaming",
        "category": "Food & Beverage",
        "image_url": "https://s.500fd.com/tt_product/40dc29b52fcf4ee199856c5c702d26f1~tplv-aphluv4xwc-resize-jpeg:800:800.jpeg",
        "pack_size_ml": 200,
    }
    bundle = resolve_product_visual_grounding(product)
    assert bundle.product_id == "generic-prod-12345"
    assert bundle.product_reference["source_type"] == "PRODUCT_ROW_IMAGE_URL"
    assert bundle.product_reference["image_url"] == product["image_url"]
    assert "Sambal Nyet Berapi" in bundle.identity_lock


def test_missing_product_image_fails_closed():
    product = {
        "id": "empty-product-99999",
        "product_display_name": "Imaginary Product Without Image",
        "category": "Unknown",
    }
    with pytest.raises(ProductVisualReferenceRequiredError) as exc_info:
        resolve_product_visual_grounding(product)
    assert "PRODUCT_VISUAL_REFERENCE_REQUIRED" in str(exc_info.value)
