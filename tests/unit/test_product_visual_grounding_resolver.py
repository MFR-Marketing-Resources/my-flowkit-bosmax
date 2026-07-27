"""Unit tests for ProductVisualGroundingResolver service."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from agent.services.product_visual_grounding_resolver import (
    STRATEGY_FIXED_HERO_POSTER,
    STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
    STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION,
    ProductVisualReferenceRequiredError,
    _inspect_image_file,
    resolve_generation_strategy,
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


def test_resolve_generic_db_product_with_image_url(tmp_path, monkeypatch):
    # Create dummy local cached image
    test_img = tmp_path / "generic.jpg"
    im = Image.new("RGB", (600, 600), color="blue")
    im.save(test_img, format="JPEG")
    img_bytes = test_img.read_bytes()
    expected_sha = hashlib.sha256(img_bytes).hexdigest()

    def mock_materialize(image_url, product_id):
        return test_img, 600, 600, "image/jpeg", expected_sha

    monkeypatch.setattr(
        "agent.services.product_visual_grounding_resolver._materialize_image_url",
        mock_materialize,
    )

    product = {
        "id": "generic-prod-12345",
        "product_display_name": "Sambal Nyet Berapi by Khairulaming",
        "category": "Food & Beverage",
        "image_url": "https://example.com/sambal.jpg",
        "pack_size_ml": 200,
    }
    bundle = resolve_product_visual_grounding(product)
    assert bundle.product_id == "generic-prod-12345"
    assert bundle.product_reference["source_type"] == "PRODUCT_ROW_IMAGE_URL"
    assert bundle.product_reference["sha256"] == expected_sha
    assert bundle.product_reference["width"] == 600
    assert bundle.product_reference["height"] == 600
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


def test_inspect_image_file_returns_real_bytes_and_sha(tmp_path):
    img_path = tmp_path / "test.png"
    im = Image.new("RGB", (400, 300), color="red")
    im.save(img_path, format="PNG")

    meta = _inspect_image_file(img_path)
    assert meta is not None
    w, h, mime, sha = meta
    assert w == 400
    assert h == 300
    assert mime == "image/png"
    assert sha == hashlib.sha256(img_path.read_bytes()).hexdigest()


def test_resolve_generation_strategy():
    # Strategy A: Avatar / Human / UGC
    strat_a = resolve_generation_strategy(
        lane_id="AVATAR_PRODUCT_STUDIO",
        product_id="prod1",
        has_avatar=True,
        is_product_only=False,
    )
    assert strat_a == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION

    # Strategy B: Product-only hero
    strat_b = resolve_generation_strategy(
        lane_id="PRODUCT_ONLY_HERO",
        product_id="prod1",
        has_avatar=False,
        is_product_only=True,
    )
    assert strat_b == STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE

    # Strategy C: Fixed Hero Poster
    strat_c = resolve_generation_strategy(
        lane_id="POSTER_BUILDER",
        product_id="prod1",
        is_poster=True,
    )
    assert strat_c == STRATEGY_FIXED_HERO_POSTER
