from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_settings_page_exposes_ai_provider_registry_controls():
    src = _read("dashboard/src/pages/SettingsPage.tsx")

    for token in [
        "Runtime Owner",
        "DEGRADED",
        "auto_start_warning",
        "AI Provider Registry",
        "/api/ai-providers",
        "Activate",
        "Save Key",
        "Clear",
        "Deactivate Active Provider",
        "Qwen",
        "Anthropic",
        "OpenAI",
        "Gemini",
        "DeepSeek",
    ]:
        assert token in src


def test_settings_page_exposes_model_and_lane_controls():
    src = _read("dashboard/src/pages/SettingsPage.tsx")

    for token in [
        "Default Model",
        "Lane Settings",
        "Text Assist",
        "Vision",
        "Execution enabled",
        "/api/ai-providers/lanes/",
        "AI Copy Assist",
        "model_catalog",
        "handleSaveLane",
    ]:
        assert token in src


def test_settings_page_exposes_dynamic_catalog_and_explicit_lanes():
    src = _read("dashboard/src/pages/SettingsPage.tsx")

    for token in [
        "Select provider",
        "Select model",
        "NOT CONFIGURED",
        "Add custom model",
        "Built-in models are starter presets",
        "model-catalog",
        "Reset models to seed",
        "handleAddCustomModel",
        "key_present",
        "model_valid",
    ]:
        assert token in src


def test_settings_route_remains_registered_in_dashboard_app():
    src = _read("dashboard/src/App.tsx")

    assert 'path="/settings"' in src
    assert "<SettingsPage />" in src
