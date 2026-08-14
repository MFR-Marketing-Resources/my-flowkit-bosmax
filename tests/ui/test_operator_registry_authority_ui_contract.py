"""UI contract: product-mapped avatar + scene strategy authority."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "dashboard" / "src" / "pages" / "OperatorPage.tsx"


def test_operator_page_uses_product_mapping_without_manual_scene_registry():
    text = OPERATOR.read_text(encoding="utf-8")
    assert 'data-testid="operator-product-mapped-avatar"' in text
    assert 'data-testid="operator-registry-authority"' not in text
    assert 'data-testid="operator-avatar-registry"' not in text
    assert 'data-testid="operator-scene-registry"' not in text
    assert "fetchAvatarRegistryPool" in text
    assert "/api/workspace/scene-context-registry/pool" not in text
    assert "getProductRecipes" in text
    assert "avatar_id: registryAvatarId" in text
    assert "scene_template_id: creativeDirection.recipes[0]?.scene_template_id" in text
    assert "scene_context_override: null" in text
    assert "scene_context_code: null" in text
    assert "avatar-persona-composer" not in text
    assert "operator-creator-persona" not in text
    assert "creatorPersona" not in text


def test_scene_registry_is_owned_only_by_i2v_reference_controls():
    controls = (
        ROOT
        / "dashboard"
        / "src"
        / "components"
        / "workspace"
        / "CanonicalReferenceBindingControls.tsx"
    ).read_text(encoding="utf-8")
    assert 'if (mode != "I2V")' not in controls  # TypeScript strict comparison below
    assert 'if (mode !== "I2V")' in controls
    assert "/api/workspace/scene-context-registry/pool" in controls
    assert "I2V uses three required engine images" in controls
