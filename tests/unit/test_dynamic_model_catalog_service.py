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


def test_openai_compatible_provider_may_now_serve_vision(catalog):
    # Multi-provider vision: openai_compatible_chat is a wired vision transport, so
    # an operator may add a custom Qwen-VL model on the vision lane (no code change).
    summary = cat.upsert_provider_model("qwen", "qwen-vl-x", "Q VL", ["vision"], True)
    custom = next(m for m in summary["providers"]["qwen"]["models"] if m["model_id"] == "qwen-vl-x")
    assert custom["enabled"] is True
    assert custom["lanes"] == ["vision"]
    assert cat.model_supports_lane("qwen", "qwen-vl-x", "vision") is True


def test_seed_multimodal_models_expose_vision(catalog):
    # Real seed multimodal models across all four vision-capable providers.
    assert cat.model_supports_lane("anthropic", "claude-sonnet-5", "vision") is True
    assert cat.model_supports_lane("openai", "gpt-4o", "vision") is True
    assert cat.model_supports_lane("gemini", "gemini-2.0-flash", "vision") is True
    assert cat.model_supports_lane("qwen", "qwen-vl-max", "vision") is True
    for provider in ("anthropic", "openai", "gemini", "qwen"):
        assert "vision" in cat.supported_lanes_for_provider(provider)
    # deepseek ships no vision model -> not vision-capable (no fake support).
    assert "vision" not in cat.supported_lanes_for_provider("deepseek")


def test_text_only_model_still_rejected_for_vision(catalog):
    # A text-only model (qwen-plus) cannot be selected for vision even though its
    # provider transport supports the lane — the MODEL must list it.
    with pytest.raises(ValueError) as exc:
        cat.validate_provider_model_for_lane("qwen", "qwen-plus", "vision")
    assert "MODEL_NOT_SUPPORTED_FOR_LANE" in str(exc.value)


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


# --- forward migration (pre-#210 catalog -> multi-provider vision) -----------

def _write_old_pre_pr210_catalog(catalog_path, *, extra_openai_models=None):
    """A local catalog seeded before PR #210: openai/gemini/qwen are text_assist
    only and qwen-vl-max does not exist yet."""
    openai_models = [
        {"model_id": "gpt-4o-mini", "label": "GPT-4o mini", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
        {"model_id": "gpt-4o", "label": "GPT-4o", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
    ]
    if extra_openai_models:
        openai_models.extend(extra_openai_models)
    payload = {
        "version": 1,
        "providers": {
            "anthropic": {
                "label": "Anthropic",
                "transport": "anthropic_messages",
                "enabled": True,
                "models": [
                    {"model_id": "claude-sonnet-5", "label": "Claude Sonnet 5", "enabled": True, "lanes": ["text_assist", "vision"], "source": "seed"},
                ],
            },
            "openai": {
                "label": "OpenAI",
                "transport": "openai_compatible_chat",
                "enabled": True,
                "models": openai_models,
            },
            "gemini": {
                "label": "Gemini",
                "transport": "openai_compatible_chat",
                "enabled": True,
                "models": [
                    {"model_id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
                ],
            },
            "qwen": {
                "label": "Qwen",
                "transport": "openai_compatible_chat",
                "enabled": True,
                "models": [
                    {"model_id": "qwen-plus", "label": "Qwen Plus", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
                    {"model_id": "qwen-max", "label": "Qwen Max", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
                ],
            },
            "deepseek": {
                "label": "DeepSeek",
                "transport": "openai_compatible_chat",
                "enabled": True,
                "models": [
                    {"model_id": "deepseek-chat", "label": "DeepSeek Chat", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
                ],
            },
        },
    }
    catalog_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _models(summary, provider_id):
    return {m["model_id"]: m for m in summary["providers"][provider_id]["models"]}


def test_existing_pre_pr210_catalog_forward_merges_new_seed_vision_models(catalog):
    _write_old_pre_pr210_catalog(catalog)
    summary = cat.summarize_model_catalog()

    openai = _models(summary, "openai")
    assert "vision" in openai["gpt-4o"]["lanes"]
    assert "text_assist" in openai["gpt-4o"]["lanes"]  # existing lane preserved
    assert "vision" in openai["gpt-4o-mini"]["lanes"]

    gemini = _models(summary, "gemini")
    assert "vision" in gemini["gemini-2.0-flash"]["lanes"]

    qwen = _models(summary, "qwen")
    assert "qwen-vl-max" in qwen  # new seed model added
    assert qwen["qwen-vl-max"]["lanes"] == ["vision"]
    assert qwen["qwen-vl-max"]["enabled"] is True

    for pid in ("anthropic", "openai", "gemini", "qwen"):
        assert "vision" in summary["providers"][pid]["supported_lanes"]
    assert "vision" not in summary["providers"]["deepseek"]["supported_lanes"]


def test_forward_merge_preserves_custom_models(catalog):
    custom = {
        "model_id": "gpt-4o-custom-ft",
        "label": "My Fine-Tune",
        "enabled": True,
        "lanes": ["text_assist"],
        "source": "custom",
    }
    _write_old_pre_pr210_catalog(catalog, extra_openai_models=[custom])
    summary = cat.summarize_model_catalog()

    openai = _models(summary, "openai")
    got = openai["gpt-4o-custom-ft"]
    assert got["source"] == "custom"
    assert got["label"] == "My Fine-Tune"
    assert got["lanes"] == ["text_assist"]  # custom model NOT given vision
    assert got["enabled"] is True
    # Seed models still migrated alongside the untouched custom model.
    assert "vision" in openai["gpt-4o"]["lanes"]


def test_forward_merge_preserves_disabled_seed_model(catalog):
    disabled_gpt4o = [
        {"model_id": "gpt-4o-mini", "label": "GPT-4o mini", "enabled": True, "lanes": ["text_assist"], "source": "seed"},
        {"model_id": "gpt-4o", "label": "GPT-4o", "enabled": False, "lanes": ["text_assist"], "source": "seed"},
    ]
    # Overwrite the default openai block with a disabled gpt-4o.
    _write_old_pre_pr210_catalog(catalog)
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["providers"]["openai"]["models"] = disabled_gpt4o
    catalog.write_text(json.dumps(data, indent=2), encoding="utf-8")

    summary = cat.summarize_model_catalog()
    openai = _models(summary, "openai")
    assert openai["gpt-4o"]["enabled"] is False  # stays disabled
    assert "vision" in openai["gpt-4o"]["lanes"]  # lanes still forward-merged
    # A disabled model is not offered for a lane (no auto-ready selection).
    assert cat.model_supports_lane("openai", "gpt-4o", "vision") is False


def test_forward_merge_is_idempotent(catalog):
    _write_old_pre_pr210_catalog(catalog)
    cat.summarize_model_catalog()  # migrates + writes
    first = catalog.read_text(encoding="utf-8")
    cat.summarize_model_catalog()  # second load must not change the file
    assert catalog.read_text(encoding="utf-8") == first
    # And the migrated content is stable/correct.
    summary = cat.summarize_model_catalog()
    assert "vision" in _models(summary, "openai")["gpt-4o"]["lanes"]
