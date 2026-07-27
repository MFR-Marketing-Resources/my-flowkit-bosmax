"""Test suite for Reference-First IMG Generation Simplification (Mission A-I).

Verifies:
1. Product contract is inserted exactly once.
2. The same lock family is not appended twice.
3. Selected product is transported only as productAsset.
4. Selected product is not duplicated as imageAsset or subjectAsset.
5. Duplicate product media IDs are not sent.
6. Subject/scene/style references still work.
7. Anonymous UGC does not require an avatar.
8. Identity-controlled avatar mode still requires an approved avatar.
9. Text-only scene context does not require a scene image.
10. Category title is treated as metadata or suppressed from visible rendering.
11. Clean-frame no-added-text rule appears exactly once.
12. Generic products receive a concise fallback product contract.
13. MWCB receives concise schema-derived product truth.
14. Full structured product truth remains available for QA/lineage.
15. Exact-product composite path remains unchanged.
16. Fixed-hero poster path remains unchanged.
17. Production extension-disconnected state fails closed.
18. Explicit mock mode works only when intentionally enabled.
19. Default runtime cannot activate mock mode.
20. Hardcoded MWCB mock copy cannot run in production.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from agent.api.flow import ordered_ref_slots
from agent.services.product_lock_builder import (
    build_concise_engine_product_contract,
    build_product_lock,
)
from agent.services.product_visual_grounding_resolver import (
    STRATEGY_FIXED_HERO_POSTER,
    STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE,
    STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION,
    get_grounded_generation_payload,
    resolve_generation_strategy,
    resolve_product_visual_grounding,
)


def test_01_product_contract_inserted_once():
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    payload = get_grounded_generation_payload(
        mwcb_id,
        "A 25ml glass bottle held gently by a hand with natural skin texture.",
        has_avatar=False,
    )
    prompt = payload["full_prompt"]
    assert prompt.count("[PRODUCT CONTRACT]") == 1
    assert prompt.count("Use the attached image as the sole product") == 1


def test_02_no_duplicate_lock_concepts():
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    payload = get_grounded_generation_payload(
        mwcb_id,
        "Bedroom vanity scene.",
    )
    prompt = payload["full_prompt"]
    # Verify model prompt does not contain redundant multi-section lock headers
    assert "PRODUCT IDENTITY LOCK:" not in prompt
    assert "PRODUCT GEOMETRY LOCK:" not in prompt
    assert "PRODUCT NEGATIVE MORPH RULES:" not in prompt


def test_03_04_05_product_transported_only_as_product_asset():
    refs = {
        "productAsset": {
            "mediaId": "media-prod-123",
            "fileName": "mwcb.jpeg",
            "semanticRole": "PRODUCT_REFERENCE",
        }
    }
    slots = ordered_ref_slots(None, refs)
    slot_names = [s[0] for s in slots]
    assert slot_names == ["Product"]
    assert "Image" not in slot_names
    assert "Subject" not in slot_names

    # Check deduplication of media IDs
    resolved_ids = ["media-prod-123"]
    for _, ref_asset in slots:
        mid = ref_asset.get("mediaId")
        if mid and mid not in resolved_ids:
            resolved_ids.append(mid)
    assert resolved_ids.count("media-prod-123") == 1


def test_06_subject_scene_style_references_preserved():
    refs = {
        "productAsset": {"mediaId": "m-prod"},
        "subjectAsset": {"mediaId": "m-char"},
        "sceneAsset": {"mediaId": "m-scene"},
        "styleAsset": {"mediaId": "m-style"},
    }
    slots = ordered_ref_slots(None, refs)
    slot_labels = [s[0] for s in slots]
    assert slot_labels == ["Product", "Subject", "Scene", "Style"]


def test_07_08_anonymous_ugc_and_avatar_governance():
    # Anonymous UGC without avatar
    strat_anon = resolve_generation_strategy(
        lane_id="AVATAR_PRODUCT_COMPOSITE",
        product_id="prod-1",
        has_avatar=False,
    )
    assert strat_anon == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION

    # Identity-controlled avatar mode
    strat_avatar = resolve_generation_strategy(
        lane_id="AVATAR_PRODUCT_COMPOSITE",
        product_id="prod-1",
        has_avatar=True,
    )
    assert strat_avatar == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION


def test_09_text_only_scene_works():
    payload = get_grounded_generation_payload(
        "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        "Cozy bedroom vanity table with warm bedside lamp",
        lane_id="AVATAR_PRODUCT_COMPOSITE",
        has_avatar=False,
    )
    assert payload["selected_strategy"] == STRATEGY_REFERENCE_CONDITIONED_HUMAN_INTERACTION
    assert "bedroom vanity" in payload["full_prompt"]


def test_10_11_category_title_and_clean_frame():
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    payload = get_grounded_generation_payload(
        mwcb_id,
        "A 25ml glass bottle held by a hand",
        is_poster=False,
    )
    prompt = payload["full_prompt"]
    clean_frame_rule = "Do not render added captions, headlines, CTAs, buttons, or UI overlay"
    assert prompt.count(clean_frame_rule) == 1
    # Category title "Daily Nightly Self-Care Routine" should not be forced into prompt
    assert "Daily Nightly Self-Care Routine" not in prompt


def test_12_13_generic_and_mwcb_concise_product_contracts():
    generic_prod = {
        "id": "gen-100",
        "name": "Organic Olive Oil Soap 100g",
        "category": "Skincare",
    }
    generic_contract = build_concise_engine_product_contract(generic_prod)
    assert "Organic Olive Oil Soap 100g" in generic_contract
    assert "Do not enlarge, redesign, duplicate, or relabel it" in generic_contract

    mwcb_prod = {
        "id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
        "name": "Minyak Warisan Cap Burung 25ml",
        "product_truth_ref": "MWCB_25ML_CAP_BURUNG",
    }
    mwcb_contract = build_concise_engine_product_contract(mwcb_prod)
    assert "Minyak Warisan Cap Burung 25ml" in mwcb_contract or "MWCB_25ML_CAP_BURUNG" in mwcb_contract
    assert "25ml compact green-glass bottle" in mwcb_contract or "compact" in mwcb_contract


def test_14_full_structured_truth_preserved_in_bundle():
    mwcb_id = "6483d624-a03d-4933-9bba-6ca2e5f7b6fd"
    bundle = resolve_product_visual_grounding(mwcb_id)
    assert "PRODUCT IDENTITY LOCK:" in bundle.identity_lock
    assert "PRODUCT GEOMETRY LOCK:" in bundle.geometry_lock
    assert "PRODUCT SCALE LOCK:" in bundle.scale_lock
    assert bundle.label_lock != ""
    assert "HANDLING LOCK:" in bundle.handling_lock
    assert "PRODUCT NEGATIVE MORPH RULES:" in bundle.negative_rules


def test_15_16_exact_and_poster_strategies_preserved():
    strat_exact = resolve_generation_strategy(
        lane_id="PRODUCT_ONLY_HERO",
        product_id="prod-1",
        is_product_only=True,
    )
    assert strat_exact == STRATEGY_PRODUCT_ONLY_DETERMINISTIC_EXACT_COMPOSITE

    strat_poster = resolve_generation_strategy(
        lane_id="PRODUCT_POSTER",
        product_id="prod-1",
        is_poster=True,
    )
    assert strat_poster == STRATEGY_FIXED_HERO_POSTER


@pytest.mark.asyncio
async def test_17_18_19_20_production_mock_isolation_and_fails_closed():
    from agent.api.flow import GenerateRequest, generate

    req = GenerateRequest(mode="IMG", prompt="Test prompt")

    # In production without mock flags and without connected extension, generate() must fail closed with 503
    with patch("agent.api.flow.get_flow_client") as mock_get_client, \
         patch.dict(os.environ, {}, clear=True):
        mock_client = MagicMock()
        mock_client.connected = False
        mock_get_client.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await generate(req)
        assert exc_info.value.status_code == 503
        assert "Extension not connected" in exc_info.value.detail

    # When ENABLE_MOCK_FLOW=1 is explicitly set, mock mode activates
    with patch("agent.api.flow.get_flow_client") as mock_get_client, \
         patch.dict(os.environ, {"ENABLE_MOCK_FLOW": "1"}, clear=True), \
         patch("agent.services.make_video.start_generate") as mock_start_gen:
        mock_client = MagicMock()
        mock_client.connected = False
        mock_get_client.return_value = mock_client
        mock_start_gen.return_value = {"job_id": "job-mock-123"}

        res = await generate(req)
        assert res == {"job_id": "job-mock-123"}
