"""Unit tests for ProductVisualGroundingResolver service."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from pathlib import Path

import pytest
from PIL import Image

from agent.services.product_visual_grounding_resolver import (
    STRATEGY_FIXED_HERO_POSTER,
    STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
    STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION,
    ProductVisualReferenceRequiredError,
    _inspect_image_file,
    _materialize_image_url,
    get_grounded_generation_payload,
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


def test_schema_canonical_source_reuses_matching_persisted_asset_id(tmp_path, monkeypatch):
    source = tmp_path / "canonical.jpg"
    Image.new("RGB", (120, 180), color=(20, 80, 120)).save(source, format="JPEG")
    from agent.services import product_visual_grounding_resolver as module

    monkeypatch.setattr(
        module,
        "resolve_schema_entry",
        lambda _product: {"canonical_source_path": str(source)},
    )
    monkeypatch.setattr(
        module,
        "_find_linked_approved_creative_asset",
        lambda _product_id: {
            "asset_id": "ca_persisted_canonical",
            "media_id": None,
            "local_file_path": str(source),
        },
    )

    resolved = resolve_product_reference_image({"id": "product-1"})

    assert resolved.media_id == "ca_persisted_canonical"
    assert resolved.source_type == "SCHEMA_CANONICAL_SOURCE"


def test_approved_canonical_cutout_wins_over_source_fallback(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    cutout = tmp_path / "cutout.png"
    Image.new("RGB", (120, 180), color=(20, 80, 120)).save(source, format="JPEG")
    cutout_image = Image.new("RGBA", (120, 180), color=(0, 0, 0, 0))
    cutout_image.paste((20, 80, 120, 255), (20, 20, 100, 160))
    cutout_image.save(cutout, format="PNG")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    cutout_sha = hashlib.sha256(cutout.read_bytes()).hexdigest()

    from agent.services import product_visual_grounding_resolver as module

    monkeypatch.setattr(
        module.truth_lock_service,
        "load_product_truth_lock",
        lambda _product_id: SimpleNamespace(review_status="APPROVED"),
    )
    monkeypatch.setattr(
        module.truth_lock_service,
        "resolve_approved_product_truth_lock",
        lambda _product_id: SimpleNamespace(
            canonical_media_id="source-media-1",
            canonical_source_path=str(source),
            canonical_sha256=source_sha,
            canonical_cutout_path=str(cutout),
            canonical_cutout_sha256=cutout_sha,
            canonical_cutout_media_id="cutout-media-1",
        ),
    )
    monkeypatch.setattr(module, "_is_purged_product_id", lambda _product_id: False)

    resolved = module.resolve_product_reference_image({"id": "canonical-1", "image_url": "https://example.com/source.jpg"})

    assert resolved.source_type == "PRODUCT_TRUTH_LOCK_CUTOUT"
    assert resolved.media_id == "cutout-media-1"
    assert resolved.local_path == str(cutout)
    assert resolved.sha256 == cutout_sha


def test_reference_pack_source_builder_can_explicitly_keep_canonical_source(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    cutout = tmp_path / "cutout.png"
    Image.new("RGB", (120, 180), color=(20, 80, 120)).save(source, format="JPEG")
    Image.new("RGBA", (120, 180), color=(0, 0, 0, 0)).save(cutout, format="PNG")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    cutout_sha = hashlib.sha256(cutout.read_bytes()).hexdigest()

    from agent.services import product_visual_grounding_resolver as module

    monkeypatch.setattr(
        module.truth_lock_service,
        "load_product_truth_lock",
        lambda _product_id: SimpleNamespace(review_status="APPROVED"),
    )
    monkeypatch.setattr(
        module.truth_lock_service,
        "resolve_approved_product_truth_lock",
        lambda _product_id: SimpleNamespace(
            canonical_media_id="source-media-1",
            canonical_source_path=str(source),
            canonical_sha256=source_sha,
            canonical_cutout_path=str(cutout),
            canonical_cutout_sha256=cutout_sha,
            canonical_cutout_media_id="cutout-media-1",
        ),
    )

    resolved = module.resolve_product_reference_image({"id": "canonical-1"}, prefer_approved_cutout=False)

    assert resolved.source_type == "PRODUCT_TRUTH_LOCK"
    assert resolved.local_path == str(source)
    assert resolved.sha256 == source_sha


def test_reference_pack_canonical_source_restores_missing_product_cache(tmp_path, monkeypatch):
    source = tmp_path / "canonical.jpg"
    Image.new("RGB", (800, 800), color=(40, 90, 120)).save(source, format="JPEG")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    from agent.services import product_visual_grounding_resolver as module

    monkeypatch.setattr(module, "resolve_schema_entry", lambda _product: None)
    monkeypatch.setattr(
        module,
        "_find_reference_pack_canonical_source",
        lambda _product_id: {
            "asset_id": "ca_refpack_canonical",
            "local_file_path": str(source),
            "sha256": source_sha,
        },
    )

    resolved = module.resolve_product_reference_image(
        {"id": "product-pack-source", "local_image_path": str(tmp_path / "missing.jpg")},
        prefer_approved_cutout=False,
    )

    assert resolved.source_type == "REFERENCE_PACK_CANONICAL_SOURCE"
    assert resolved.media_id == "ca_refpack_canonical"
    assert resolved.sha256 == source_sha
    assert resolved.width == 800
    assert resolved.height == 800


def test_purged_alias_cannot_receive_schema_visual_fallback(monkeypatch):
    from agent.services import product_visual_grounding_resolver as module

    monkeypatch.setattr(module, "get_product_by_id", lambda _product_id: None)
    monkeypatch.setattr(module, "_is_purged_product_id", lambda _product_id: True)

    with pytest.raises(ProductVisualReferenceRequiredError) as exc_info:
        module.resolve_product_visual_grounding("purged-alias-1")

    assert "PRODUCT_PURGED_ALIAS_NOT_ELIGIBLE" in str(exc_info.value)


def test_get_grounded_generation_payload_binds_6_locks():
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    payload = get_grounded_generation_payload(
        mwcb_id,
        "A presenter holding product in hand.",
        has_avatar=True,
    )
    assert payload["product_id"] == mwcb_id
    assert payload["selected_strategy"] == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION
    assert payload["product_reference"]["validation_status"] == "VALIDATED"

    # Full structured locks remain available for backend QA / lineage
    locks = payload["grounding_locks"]
    assert "PRODUCT IDENTITY LOCK:" in locks["identity_lock"]
    assert "PRODUCT GEOMETRY LOCK:" in locks["geometry_lock"]
    assert "PRODUCT SCALE LOCK:" in locks["scale_lock"]
    assert locks["label_lock"] != ""
    assert "HANDLING LOCK:" in locks["handling_lock"]
    assert "PRODUCT NEGATIVE MORPH RULES:" in locks["negative_rules"]

    # Model-facing full_prompt carries concise reference-first contract
    full_prompt = payload["full_prompt"]
    assert "[PRODUCT CONTRACT]" in full_prompt
    assert "Use the attached image as the sole product reference for" in full_prompt
    assert "NON_DETERMINISTIC_REFERENCE_CONDITIONED" in full_prompt
    assert "human review required" in full_prompt


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
    strat_a = resolve_generation_strategy(
        lane_id="AVATAR_PRODUCT_STUDIO",
        product_id="prod1",
        has_avatar=True,
        is_product_only=False,
    )
    assert strat_a == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION

    strat_b = resolve_generation_strategy(
        lane_id="PRODUCT_ONLY_HERO",
        product_id="prod1",
        has_avatar=False,
        is_product_only=True,
    )
    assert strat_b == STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE

    strat_c = resolve_generation_strategy(
        lane_id="POSTER_BUILDER",
        product_id="prod1",
        is_poster=True,
    )
    assert strat_c == STRATEGY_FIXED_HERO_POSTER
