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
        "AI Model Routing",
        "/api/ai-model-catalog",
        "/api/ai-routing",
        "Update Route",
        "Reset AI Routing",
        "final_prompt_compiler",
        "bosmax-canonical-compiler",
        "product_image_analysis",
        "copywriting_assist",
        "video_review",
    ]:
        assert token in src


def test_settings_route_remains_registered_in_dashboard_app():
    src = _read("dashboard/src/App.tsx")

    assert 'path="/settings"' in src
    assert "<SettingsPage />" in src
