import asyncio

import pytest
from fastapi import HTTPException

from agent.api.flow import GenerateRequest, generate
from agent.api.img_factory import (
    get_creative_campaign_status,
    get_image_capability_audit,
)


def test_phase_1a_capability_audit_is_explicitly_no_spend():
    audit = asyncio.run(get_image_capability_audit())

    assert audit.phase == "1A_STATIC_NO_SPEND"
    assert audit.no_spend is True
    assert audit.capability_status["multi_reference_roles"] == "UNPROVEN"
    assert audit.transport_contract["role_semantics"] == "UNPROVEN_GENERIC_MEDIA_IDS"
    assert any("BOUNDED_CREDIT_AUTHORIZATION" in item for item in audit.blockers)


def test_creative_campaign_status_keeps_exact_production_default():
    status = asyncio.run(get_creative_campaign_status())

    assert status["production_default"] is False
    assert status["legacy_scene_asset_required"] is False
    assert status["optional_scene_reference_supported"] is True
    assert status["bounded_live_confirmation_required"] is True


def test_creative_campaign_live_route_fails_closed_before_provider_work(monkeypatch):
    monkeypatch.setattr(
        "agent.config.CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZED", False
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            generate(
                GenerateRequest(
                    mode="IMG",
                    prompt="nine-section prompt",
                    product_id="product-test-1",
                    visual_lane_id="POSTER_BUILDER_CREATIVE_CAMPAIGN",
                    image_contract_version="image_prompt_compiler_v1",
                    confirm_live_credit_burn=True,
                    maximum_provider_operations=1,
                    max_retry_operations=0,
                )
            )
        )

    assert raised.value.status_code == 403
    assert raised.value.detail == "CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZATION_REQUIRED"


def test_creative_campaign_rejects_unbounded_variant_request(monkeypatch):
    monkeypatch.setattr(
        "agent.config.CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZED", True
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            generate(
                GenerateRequest(
                    mode="IMG",
                    prompt="nine-section prompt",
                    product_id="product-test-1",
                    visual_lane_id="POSTER_BUILDER_CREATIVE_CAMPAIGN",
                    image_contract_version="image_prompt_compiler_v1",
                    confirm_live_credit_burn=True,
                    count=4,
                    maximum_provider_operations=4,
                    max_retry_operations=0,
                )
            )
        )

    assert raised.value.status_code == 422
    assert raised.value.detail == "CREATIVE_CAMPAIGN_MAX_THREE_VARIANTS"


def test_creative_campaign_requires_clean_key_visual_and_final_model(monkeypatch):
    monkeypatch.setattr(
        "agent.config.CREATIVE_CAMPAIGN_LIVE_BENCHMARK_AUTHORIZED", True
    )

    with pytest.raises(HTTPException) as intent_error:
        asyncio.run(
            generate(
                GenerateRequest(
                    mode="IMG",
                    prompt="nine-section prompt",
                    product_id="product-test-1",
                    visual_lane_id="POSTER_BUILDER_CREATIVE_CAMPAIGN",
                    image_contract_version="image_prompt_compiler_v1",
                    output_intent="COMPLETE_POSTER",
                    image_model="NANO_BANANA_PRO",
                    confirm_live_credit_burn=True,
                    maximum_provider_operations=1,
                    max_retry_operations=0,
                )
            )
        )
    assert intent_error.value.detail == "CREATIVE_CAMPAIGN_CLEAN_KEY_VISUAL_REQUIRED"

    with pytest.raises(HTTPException) as model_error:
        asyncio.run(
            generate(
                GenerateRequest(
                    mode="IMG",
                    prompt="nine-section prompt",
                    product_id="product-test-1",
                    visual_lane_id="POSTER_BUILDER_CREATIVE_CAMPAIGN",
                    image_contract_version="image_prompt_compiler_v1",
                    output_intent="CLEAN_KEY_VISUAL",
                    image_model="NANO_BANANA_2",
                    confirm_live_credit_burn=True,
                    maximum_provider_operations=1,
                    max_retry_operations=0,
                )
            )
        )
    assert model_error.value.detail == "CREATIVE_CAMPAIGN_FINAL_MODEL_REQUIRED:NANO_BANANA_PRO"
