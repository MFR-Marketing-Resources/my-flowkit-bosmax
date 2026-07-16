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


def test_scene_registry_coverage_lens_present():
    """Phase A modernization: the page is framed as a live authority pool and
    shows the read-only coverage/usage lens with dependency notes."""
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    assert "Live Scene / Context Authority Pool" in src
    assert "getRegistryCoverage" in src
    assert "Scene-Prompt Coverage" in src
    assert "Coverage Gaps" in src
    # Dependency note: scene reference lanes + Creative Intelligence context.
    assert "scene reference lanes" in src
    assert "Creative Intelligence context" in src


def test_scene_registry_reconciliation_panel_present():
    """Phase C: read-only reconciliation panel with non-destructive labels."""
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    assert "getRegistryReconciliation" in src
    assert "Registry Reconciliation" in src
    assert "Scene Prompts" in src
    assert "Referenced" in src
    assert "Review candidates" in src
    assert "not directly mapped" in src
    assert "safe to delete" not in src.lower()
    assert "delete now" not in src.lower()


def test_scene_registry_archive_delete_planning_present():
    """Phase D: read-only archive/delete planning panel with dry-run framing."""
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    assert "getRegistryCleanupPlan" in src
    assert "Archive / Delete Planning" in src
    assert "Read-only dry-run" in src
    assert "No records are changed" in src
    assert "Owner approval required" in src
    assert "BLOCKED_UNKNOWN_MAPPING" in src
    assert "FUTURE_ARCHIVE_ELIGIBLE" in src
    assert "safe to delete" not in src.lower()
    assert "delete now" not in src.lower()


def test_scene_registry_phase_e_closeout_note():
    """Phase E closeout: the cleanup panel shows a read-only finalization note —
    Registry Modernization complete, no current archive/delete eligibility (when
    future_archive_eligible_total is 0), and owner approval + zero-reference
    dry-run proof required for any future cleanup. No delete/archive action added."""
    src = _read("dashboard/src/pages/SceneContextRegistryPage.tsx")
    assert "Registry Modernization (Phases A" in src
    assert "No records are currently eligible for archive or delete" in src
    assert "zero-reference dry-run proof" in src
    assert "cleanup.future_archive_eligible_total === 0" in src
    assert "safe to delete" not in src.lower()
    assert "delete now" not in src.lower()
