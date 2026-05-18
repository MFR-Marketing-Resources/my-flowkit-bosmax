import pytest

from agent.services.prompt_compiler_runtime_config_service import (
    dialogue_word_budget,
    get_runtime_config,
    get_shot_policy,
    normalize_generation_mode,
    validate_duration_seconds,
)


def test_runtime_config_exposes_central_policy_contract():
    config = get_runtime_config()

    assert config["generation_modes"] == ["SINGLE", "EXTEND"]
    assert config["allowed_block_durations_seconds"] == [6, 8, 10, 12, 15, 20, 25]
    assert config["defaults"]["block_duration_seconds"] == 8
    assert "BM_MS" in config["language_wps_policy"]
    assert "EN_US" in config["language_wps_policy"]
    assert config["shot_count_policy"][10]["recommended"] == 3


def test_runtime_config_rejects_invalid_duration_and_generation_mode():
    with pytest.raises(ValueError, match="INVALID_BLOCK_DURATION_SECONDS:9"):
        validate_duration_seconds(9)

    with pytest.raises(ValueError, match="INVALID_GENERATION_MODE:LOOP"):
        normalize_generation_mode("loop")


def test_dialogue_word_budget_uses_language_policy():
    assert dialogue_word_budget(8, "BM_MS", dialogue_enabled=True) == 13
    assert dialogue_word_budget(10, "EN_US", dialogue_enabled=True) == 20
    assert dialogue_word_budget(10, "EN_US", dialogue_enabled=False) == 0
    assert get_shot_policy(25)["recommended"] == 6
