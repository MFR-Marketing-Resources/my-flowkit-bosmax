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


def test_settings_page_defensively_normalizes_registry_payload():
    """HOTFIX: a stale/legacy/corrupt /api/ai-providers payload must never blank
    the page. The page normalizes every payload into the V3 shape before render
    and guards the direct field derefs the incident crashed on."""
    src = _read("dashboard/src/pages/SettingsPage.tsx")

    # A single normalization entry point coerces the raw payload.
    for token in [
        "function normalizeRegistry",
        "normalizeProvider",
        "normalizeLane",
        "normalizeCatalogEntry",
        "catalogMalformed",
    ]:
        assert token in src, token

    # The raw payload is normalized on both the poll and mutation paths (the
    # fetch is typed as unknown, not a trusted AIProviderRegistry).
    assert 'fetchAPI<unknown>("/api/ai-providers")' in src
    assert "normalizeRegistry(providers)" in src

    # Malformed catalog surfaces a visible warning, not a crash.
    assert "Model catalog unavailable or malformed. Reset catalog or refresh." in src


def test_settings_page_guards_v3_field_derefs():
    """The exact derefs the blank-screen incident crashed on are guarded so a
    missing field degrades gracefully instead of throwing."""
    src = _read("dashboard/src/pages/SettingsPage.tsx")

    # lane.status.replaceAll(...) was the live crash (old shape had no status).
    assert "(setting.status ?? \"NOT_CONFIGURED\").replaceAll" in src
    # Array derefs are guarded with ?? [].
    for token in [
        "(provider.current_capabilities ?? [])",
        "(provider.supported_lanes ?? [])",
        "(model.lanes ?? [])",
        "(providerRegistry.providers ?? [])",
    ]:
        assert token in src, token


def test_settings_page_vision_lane_allows_openai_compatible_providers():
    """Multi-provider Vision Lane: the custom-model vision checkbox is offered for
    BOTH wired vision transports (Anthropic messages + OpenAI-compatible), not
    Anthropic-only."""
    src = _read("dashboard/src/pages/SettingsPage.tsx")
    assert 'transport === "anthropic_messages"' in src
    assert 'transport === "openai_compatible_chat"' in src


def test_settings_page_vision_providers_are_registry_driven():
    """The Vision Lane provider dropdown is derived from the registry's transport-
    gated supported_lanes — NOT a hardcoded Anthropic-only list. After forward
    migration surfaces vision for openai/gemini/qwen, they appear automatically."""
    src = _read("dashboard/src/pages/SettingsPage.tsx")
    # Lane provider options come from providersForLane(...) which filters by
    # supported_lanes.includes(lane).
    assert "providersForLane" in src
    assert "supported_lanes ?? []).includes(lane)" in src
    assert "laneProviders.map" in src


def test_settings_route_remains_registered_in_dashboard_app():
    src = _read("dashboard/src/App.tsx")

    assert 'path="/settings"' in src
    assert "<SettingsPage />" in src
