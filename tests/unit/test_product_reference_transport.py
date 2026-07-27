"""Unit tests for Product Reference Provider Transport (PR #500)."""
from __future__ import annotations

import pytest
from agent.api.flow import (
    REF_SLOT_ORDER,
    _asset_payload_has_local_file,
    _asset_payload_remote_url,
    _extract_flow_media_id,
    ordered_ref_slots,
)
from agent.services.product_visual_grounding_resolver import (
    get_grounded_generation_payload,
)


def test_ref_slot_order_includes_product_asset():
    slot_keys = [slot[0] for slot in REF_SLOT_ORDER]
    assert "productAsset" in slot_keys
    assert slot_keys[0] == "productAsset"


def test_ordered_ref_slots_extracts_product_asset():
    refs = {
        "productAsset": {"localFilePath": "C:/tmp/product.jpg"},
        "subjectAsset": {"mediaId": "11111111-2222-3333-4444-555555555555"},
    }
    slots = ordered_ref_slots(None, refs)
    slot_labels = [s[0] for s in slots]
    assert "Product" in slot_labels
    assert "Subject" in slot_labels
    assert slots[0] == ("Product", {"localFilePath": "C:/tmp/product.jpg"})


def test_asset_payload_has_local_file_aliases():
    assert _asset_payload_has_local_file({"localFilePath": "/tmp/a.jpg"})
    assert _asset_payload_has_local_file({"local_file_path": "/tmp/b.jpg"})
    assert _asset_payload_has_local_file({"localPath": "/tmp/c.jpg"})
    assert _asset_payload_has_local_file({"local_path": "/tmp/d.jpg"})
    assert not _asset_payload_has_local_file({"url": "http://example.com/a.jpg"})


def test_asset_payload_remote_url_aliases():
    assert _asset_payload_remote_url({"downloadUrl": "http://a.com"}) == "http://a.com"
    assert _asset_payload_remote_url({"download_url": "http://b.com"}) == "http://b.com"
    assert _asset_payload_remote_url({"previewUrl": "http://c.com"}) == "http://c.com"
    assert _asset_payload_remote_url({"url": "http://d.com"}) == "http://d.com"
    assert _asset_payload_remote_url({"image_url": "http://e.com"}) == "http://e.com"


def test_extract_flow_media_id():
    valid_uuid = "12345678-1234-1234-1234-123456789abc"
    assert _extract_flow_media_id({"mediaId": valid_uuid}) == valid_uuid
    assert _extract_flow_media_id({"media_id": valid_uuid}) == valid_uuid
    assert _extract_flow_media_id({"assetId": valid_uuid}) == valid_uuid
    assert _extract_flow_media_id({"assetId": "product-image:123:start_frame"}) is None


def test_grounded_payload_returns_normalized_product_reference_asset():
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    payload = get_grounded_generation_payload(mwcb_id, "Presenter prompt")
    assert "product_reference_asset" in payload
    ref_asset = payload["product_reference_asset"]
    assert ref_asset["semanticRole"] == "PRODUCT_REFERENCE"
    assert ref_asset["localFilePath"] is not None
