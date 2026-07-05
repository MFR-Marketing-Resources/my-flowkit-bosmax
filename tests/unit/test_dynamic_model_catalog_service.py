"""Unit tests for the mutable AI model catalog (ai_provider_model_catalog).

Covers: seed initialization, add/edit/disable custom models, reset-seed,
transport gating (a lane a provider's transport cannot serve is rejected), and
custom model IDs added WITHOUT any source-code change.
"""
import json

import pytest

from agent.services import ai_provider_model_catalog as cat


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_DIR", tmp_path)
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_FILE", tmp_path / "ai-model-catalog.json")
    return tmp_path / "ai-model-catalog.json"


def test_catalog_initializes_from_seed(catalog):
    summary = cat.summarize_model_catalog()
    assert set(summary["providers"].keys()) == {"qwen", "anthropic", "openai", "gemini", "deepseek"}
    qwen_models = {m["model_id"] for m in summary["providers"]["qwen"]["models"]}
    assert {"qwen-plus", "qwen-max"} <= qwen_models
    assert catalog.exists()  # seed written on first load
    for m in summary["providers"]["qwen"]["models"]:
        assert m["source"] == "seed"


def test_add_custom_model_persists_and_is_source_custom(catalog):
    cat.upsert_provider_model("deepseek", "deepseek-reasoner", "DeepSeek Reasoner", ["text_assist"], True)
    on_disk = json.loads(catalog.read_text(encoding="utf-8"))
    models = on_disk["providers"]["deepseek"]["models"]
    custom = next(m for m in models if m["model_id"] == "deepseek-reasoner")
    assert custom["source"] == "custom"
    assert custom["lanes"] == ["text_assist"]
    assert cat.model_supports_lane("deepseek", "deepseek-reasoner", "text_assist") is True


def test_edit_existing_model_label_and_lanes(catalog):
    cat.upsert_provider_model("deepseek", "deepseek-chat", "DeepSeek Chat v2", ["text_assist"], True)
    entry = cat.get_model_entry("deepseek", "deepseek-chat")
    assert entry["label"] == "DeepSeek Chat v2"


def test_disable_model_removes_it_from_lane_options(catalog):
    cat.disable_provider_model("qwen", "qwen-max")
    assert cat.model_supports_lane("qwen", "qwen-max", "text_assist") is False
    lane_models = {m["model_id"] for m in cat.models_for_lane("qwen", "text_assist")}
    assert "qwen-max" not in lane_models
    assert "qwen-plus" in lane_models


def test_add_vision_lane_to_openai_compatible_provider_rejected(catalog):
    # qwen transport is openai_compatible_chat which cannot serve the vision lane.
    with pytest.raises(ValueError) as exc:
        cat.upsert_provider_model("qwen", "qwen-vl-x", "Q VL", ["vision"], True)
    assert "TRANSPORT_NOT_SUPPORTED_FOR_LANE" in str(exc.value)


def test_anthropic_may_serve_vision(catalog):
    assert cat.model_supports_lane("anthropic", "claude-sonnet-5", "vision") is True
    assert "vision" in cat.supported_lanes_for_provider("anthropic")
    assert "vision" not in cat.supported_lanes_for_provider("qwen")


def test_unknown_provider_upsert_rejected(catalog):
    with pytest.raises(ValueError) as exc:
        cat.upsert_provider_model("mystery", "x", "X", ["text_assist"], True)
    assert "UNKNOWN_PROVIDER" in str(exc.value)


def test_empty_model_id_rejected(catalog):
    with pytest.raises(ValueError) as exc:
        cat.upsert_provider_model("qwen", "   ", "X", ["text_assist"], True)
    assert "MODEL_ID_REQUIRED" in str(exc.value)


def test_reset_seed_discards_edits(catalog):
    cat.upsert_provider_model("deepseek", "deepseek-reasoner", "R", ["text_assist"], True)
    cat.disable_provider_model("qwen", "qwen-max")
    cat.reset_seed_catalog()
    summary = cat.summarize_model_catalog()
    deepseek_ids = {m["model_id"] for m in summary["providers"]["deepseek"]["models"]}
    assert "deepseek-reasoner" not in deepseek_ids
    qwen_max = next(m for m in summary["providers"]["qwen"]["models"] if m["model_id"] == "qwen-max")
    assert qwen_max["enabled"] is True


def test_custom_edit_survives_reload_non_destructive_merge(catalog):
    cat.upsert_provider_model("deepseek", "deepseek-reasoner", "R", ["text_assist"], True)
    # A fresh load must preserve the operator's custom model (seed only fills gaps).
    reloaded = cat.get_model_catalog()
    ids = {m["model_id"] for m in reloaded["providers"]["deepseek"]["models"]}
    assert "deepseek-reasoner" in ids
    assert "deepseek-chat" in ids


def test_transport_declared_per_provider(catalog):
    assert cat.get_provider_transport("anthropic") == "anthropic_messages"
    assert cat.get_provider_transport("qwen") == "openai_compatible_chat"
    assert cat.get_provider_transport("mystery") is None
