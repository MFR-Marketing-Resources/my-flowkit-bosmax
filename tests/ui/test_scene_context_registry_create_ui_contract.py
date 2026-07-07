"""UI source contract for the Scene Context Registry "Create Scene" section.

The Scene Context Registry page must expose manual add + AI auto-generate,
mirroring the avatar registry, wired to the add-manual / auto-generate
endpoints with fail-closed messaging (409 redundant, 503 unconfigured lane,
502 invalid AI response).
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_create_scene_manual_add_wired():
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    assert "Create Scene" in src
    assert "/api/workspace/scene-context-registry/add-manual" in src
    assert "handleAddManualScene" in src
    # Fail-closed redundancy surface (409 SCENE_REDUNDANT).
    assert "SCENE_REDUNDANT" in src
    assert "Scene serupa sudah wujud" in src
    # Manual fields for the add-manual body.
    assert "scene_name" in src
    assert "background_prompt" in src


def test_create_scene_auto_generate_wired():
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    assert "/api/workspace/scene-context-registry/auto-generate" in src
    assert "handleAutoGenerateScene" in src
    assert "Auto-generate Scene" in src
    # 503 must point operators to the AI Provider Settings text_assist lane.
    assert "AI Provider Settings" in src
    assert "text_assist" in src
    # Loading state while the LLM call is in flight.
    assert "isAutoGenerating" in src


def test_create_scene_reuses_page_error_success_state():
    """The new section must reuse the existing refresh()/error/successMsg
    state rather than introducing parallel handlers."""
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    # Handlers drive the shared success/error surfaces and refresh the pool.
    handler = src.split("const handleAddManualScene", 1)[1]
    handler = handler.split("const handleGenerateImage", 1)[0]
    assert "setSuccessMsg" in handler
    assert "setError" in handler
    assert "await refresh()" in handler
