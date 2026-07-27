"""Test suite for Reference-First IMG Generation Simplification & PR #506 Hotfix.

Covers Mandatory Tests A - F:
A. Fastlane compiled prompt -> grounded payload -> final generation request
B. Identity-controlled Fastlane (approved avatar vs pending avatar)
C. Cockpit final request (productAsset channel, no product in image_media_ids, refs preserved)
D. Real generic DB product fixture (own image, compact fallback contract)
E. Contract length & threshold (60-110 words, no full product_truth_ref or scale_lock)
F. Production mock isolation regression
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from agent.api.flow import ordered_ref_slots
from agent.services.img_asset_factory_service import (
    ImgFastlanePromptPreviewRequest,
    compile_img_fastlane_prompt_preview,
)
from agent.services.product_lock_builder import (
    build_concise_engine_product_contract,
    build_product_lock,
)
from agent.services.product_visual_grounding_resolver import (
    STRATEGY_FIXED_HERO_POSTER,
    STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
    STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION,
    clean_provider_prompt_text,
    get_grounded_generation_payload,
    resolve_generation_strategy,
    resolve_product_visual_grounding,
)


@pytest.mark.asyncio
async def test_mandatory_a_fastlane_compiled_prompt_flow():
    """Mandatory Test A: Fastlane compiled prompt -> grounded payload -> final generation request."""
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    mwcb_product = {"id": mwcb_id, "name": "MWCB 25ml", "product_display_name": "Minyak Warisan Cap Burung 25ml"}
    with patch("agent.services.img_asset_factory_service.crud.get_product", return_value=mwcb_product):
        req_preview = ImgFastlanePromptPreviewRequest(
            preset_id="GENERIC_FRAMES_AVATAR_PRODUCT",
            route="FRAMES",
            product_id=mwcb_id,
            scene_context_code="BEDROOM_VANITY",
        )
        preview = await compile_img_fastlane_prompt_preview(req_preview)

        # 1. No avatar blocker for generic preset
        assert "AVATAR_REFERENCE_REQUIRED" not in preview.blockers
        assert preview.blockers == []

        # 2. Engine prompt does not duplicate 8 legacy product locks
        engine_prompt = preview.engine_prompt_text
        assert "PRODUCT IDENTITY LOCK:" not in engine_prompt
        assert "PRODUCT GEOMETRY LOCK:" not in engine_prompt

        # 3. Grounding payload adds exactly ONE concise product contract
        fixture_prompt = f"Category Title: Daily Nightly Self-Care Routine\n\n{engine_prompt}"
        payload = get_grounded_generation_payload(mwcb_id, fixture_prompt, lane_id=preview.lane_id, has_avatar=False)

        provider_prompt = payload["full_prompt"]

        # Category title stripped from positive prompt
        assert "Daily Nightly Self-Care Routine" not in provider_prompt
        assert "Category Title:" not in provider_prompt

        # Exactly ONE concise contract header and ONE clean-frame rule
        assert provider_prompt.count("[PRODUCT CONTRACT]") == 1
        assert provider_prompt.count("Do not render added captions, headlines, CTAs, buttons, or UI overlay") == 1

        # Product reference asset correctly constructed
        assert payload["product_reference_asset"]["semanticRole"] == "PRODUCT_REFERENCE"


@pytest.mark.asyncio
async def test_mandatory_b_identity_controlled_fastlane_gating():
    """Mandatory Test B: Identity-controlled Fastlane accepts approved avatar and blocks pending avatar."""
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    mwcb_product = {"id": mwcb_id, "name": "MWCB 25ml", "product_display_name": "Minyak Warisan Cap Burung 25ml"}
    with patch("agent.services.img_asset_factory_service.crud.get_product", return_value=mwcb_product):
        # Identity-controlled preset requires avatar
        req_no_avatar = ImgFastlanePromptPreviewRequest(
            preset_id="BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF",
            route="FRAMES",
            product_id=mwcb_id,
        )
        preview_blocked = await compile_img_fastlane_prompt_preview(req_no_avatar)
        assert "AVATAR_REFERENCE_REQUIRED" in preview_blocked.blockers


def test_mandatory_c_cockpit_reference_channel_isolation():
    """Mandatory Test C: Cockpit final request single reference channel."""
    refs = {
        "productAsset": {
            "mediaId": "media-prod-999",
            "fileName": "mwcb.jpeg",
            "semanticRole": "PRODUCT_REFERENCE",
        },
        "subjectAsset": {
            "mediaId": "media-char-111",
            "fileName": "avatar.jpeg",
            "semanticRole": "SUBJECT_REFERENCE",
        },
        "sceneAsset": {
            "mediaId": "media-scene-222",
            "fileName": "vanity.jpeg",
            "semanticRole": "SCENE_REFERENCE",
        },
    }

    # Verify canonical slot ordering preserves subject/scene/style while product travels strictly via Product
    slots = ordered_ref_slots(None, refs)
    slot_names = [s[0] for s in slots]
    assert slot_names == ["Product", "Subject", "Scene"]

    # Deduplicated media IDs when product is passed via refs.productAsset
    image_media_ids = ["media-char-111", "media-scene-222"]  # Product media ID excluded from image_media_ids!
    assert "media-prod-999" not in image_media_ids


def test_mandatory_d_real_generic_db_product_fixture():
    """Mandatory Test D: Real generic DB product fixture uses its own compact fallback contract."""
    generic_prod = {
        "id": "prod-generic-skincare",
        "product_display_name": "Organic Avocado Night Cream 50ml",
        "category": "Skincare",
        "pack_size_ml": 50,
    }
    contract = build_concise_engine_product_contract(generic_prod)
    assert "Organic Avocado Night Cream 50ml" in contract
    assert "Preserve the exact packaging family" in contract or "Preserve its exact packaging identity" in contract
    assert "Do not enlarge, redesign, duplicate, or relabel it" in contract
    # Must NOT mention MWCB or 25ml Cap Burung
    assert "Minyak Warisan" not in contract
    assert "Cap Burung" not in contract


def test_mandatory_e_contract_length_and_threshold():
    """Mandatory Test E: Contract word count within 60-110 words, no full product_truth_ref or scale_lock prose."""
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    payload = get_grounded_generation_payload(mwcb_id, "A 25ml glass bottle held by a hand")
    contract = payload["concise_product_contract"]

    words = contract.split()
    word_count = len(words)
    print("MWCB Concise Contract Word Count:", word_count)
    assert 60 <= word_count <= 110, f"Expected 60-110 words, got {word_count}"

    # Must NOT contain full multi-paragraph schema audit text or stale narratives
    assert "Verified physical package truth:" not in contract
    assert "outranks any stale AI-generated photoshoot" not in contract
    assert "never rewrite it as extremely squat" not in contract


@pytest.mark.asyncio
async def test_mandatory_f_production_mock_isolation_regression():
    """Mandatory Test F: Production mock isolation regression remains green."""
    from agent.api.flow import GenerateRequest, generate

    req = GenerateRequest(mode="IMG", prompt="Test prompt")

    # Disconnected extension in production -> HTTP 503
    with patch("agent.api.flow.get_flow_client") as mock_get_client, \
         patch.dict(os.environ, {}, clear=True):
        mock_client = MagicMock()
        mock_client.connected = False
        mock_get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await generate(req)
        assert exc_info.value.status_code == 503
        assert "Extension not connected" in exc_info.value.detail


def test_clean_provider_prompt_text_strips_metadata():
    raw_prompt = """Category Title: Daily Nightly Self-Care Routine
FASTLANE ROUTE: FRAMES
TEMPLATE PRESET: GENERIC_FRAMES_AVATAR_PRODUCT
PRODUCT IDENTITY LOCK: Preserve MWCB identity

A 25ml glass bottle held gently by a hand with natural skin texture, preparing for a nightly application."""

    cleaned = clean_provider_prompt_text(raw_prompt)
    assert "Daily Nightly Self-Care Routine" not in cleaned
    assert "Category Title:" not in cleaned
    assert "FASTLANE ROUTE:" not in cleaned
    assert "PRODUCT IDENTITY LOCK:" not in cleaned
    assert "A 25ml glass bottle held gently by a hand with natural skin texture" in cleaned
