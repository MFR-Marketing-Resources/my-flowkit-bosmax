"""UI contract: Operator T2V/Hybrid registry authority controls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "dashboard" / "src" / "pages" / "OperatorPage.tsx"


def test_operator_page_has_registry_authority_controls():
    text = OPERATOR.read_text(encoding="utf-8")
    assert 'data-testid="operator-registry-authority"' in text
    assert 'data-testid="operator-avatar-registry"' in text
    assert 'data-testid="operator-scene-registry"' in text
    assert 'mode === "T2V" || mode === "HYBRID"' in text
    assert "/api/workspace/avatar-registry/pool" in text
    assert "/api/workspace/scene-context-registry/pool" in text
    assert "avatar_id: registryAvatarId" in text
    assert "scene_context_override: selectedSceneBackground" in text
    assert "scene_context_code: registrySceneCode" in text
    assert "avatar-persona-composer" not in text
    assert "operator-creator-persona" not in text
    assert "creatorPersona" not in text
