import pytest
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt

def test_avatar_registry_selection_takes_precedence_over_composer_persona():
    """Verify that an explicit registry avatar_id overrides any draft creator_persona."""
    product = {
        "id": "prod-test-avatar",
        "raw_product_title": "Test Product",
        "category": "BEAUTY",
    }
    approved_pkg = {"hook_angle": "Empathy", "cta_angle": "Urgency"}

    # Pass explicit avatar_id AND a creator_persona string
    result = compile_ugc_video_prompt(
        mode="T2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        product=product,
        approved_package=approved_pkg,
        creator_persona="DEFAULT_CREATOR",
        avatar_id="BOS_F_ALYA_01",
    )

    # 1. Avatar_id in return dict must be the registry avatar (BOS_F_ALYA_01)
    assert result["avatar_id"] == "BOS_F_ALYA_01"

    # 2. Creator persona metadata must reflect the authoritative registry avatar code
    assert result["creator_persona"] == "BOS_F_ALYA_01"

    # 3. Prompt text in Section 3 must contain the resolved presenter description
    prompt_text = result["prompt_blocks"][0]["engine_prompt_text"]
    assert "presenter is a malaysian young adult woman" in prompt_text.lower()

def test_invalid_avatar_id_fails_closed():
    """Verify that an invalid avatar_id raises AVATAR_NOT_FOUND fail-closed."""
    product = {
        "id": "prod-test-avatar",
        "raw_product_title": "Test Product",
        "category": "BEAUTY",
    }
    approved_pkg = {"hook_angle": "Empathy", "cta_angle": "Urgency"}

    with pytest.raises(ValueError, match="AVATAR_NOT_FOUND"):
        compile_ugc_video_prompt(
            mode="T2V",
            generation_mode="SINGLE",
            duration_seconds=8,
            product=product,
            approved_package=approved_pkg,
            avatar_id="NON_EXISTENT_AVATAR_999",
        )
