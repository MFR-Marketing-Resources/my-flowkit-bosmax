"""IMG Fastlane UI contract.

Deterministic text-parse coverage for the database-driven, template-driven IMG
Fastlane operator flow. The primary path must compile prompts automatically from
product truth, preset rules, and existing references without requiring raw
subject / scene / style prompt typing.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_fastlane_route_nav_and_import_registered():
    app = _read("dashboard/src/App.tsx")
    assert 'import ImgFastlanePage from "./pages/ImgFastlanePage"' in app
    assert '/assets/img-fastlane' in app
    assert '<ImgFastlanePage />' in app
    assert "IMG Fastlane" in app


def test_fastlane_uses_database_driven_preset_compiler():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")

    assert "fetchImgFastlanePresets" in page
    assert "compileImgFastlanePromptPreview" in page
    assert "SearchableProductSelect" in page
    assert "Template Preset" in page
    assert "Auto-built Prompt Preview" in page
    assert "Advanced Override Notes optional" in page
    assert "readOnly" in page
    assert "Prompt preview auto-build is active." in page

    assert "compileWorkspacePromptPreview" not in page
    assert "ingSubjectText" not in page
    assert "ingSceneText" not in page
    assert "ingStyleText" not in page
    assert "handleCompileIngredientsPrompt" not in page


def test_fastlane_surfaces_reference_and_product_wiring():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")

    assert "PRODUCT_REFERENCE" in page
    assert "productReferenceAssets" in page
    assert "Select Existing Reference — Avatar" in page
    assert "Select Existing Reference — Scene" in page
    assert "Select Existing Reference — Style" in page
    assert "Select Existing Reference Or Create From Preset" in page
    assert "Create From Preset" in page
    assert "No references found — create one from preset" in page
    assert "Frames Fastlane blocks generation until a database product is selected." in page
    assert "No Product Visual Reference" in page
    assert "/api/flow/artifacts" in page
    assert "Finished artifact candidate" in page


def test_fastlane_presets_and_blockers_are_explicit():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    assert "framePresets" in page
    assert "ingredientPresets" in page
    assert "compiledBlockers" in page
    assert "AVATAR_REFERENCE_REQUIRED" in page
    assert "SCENE_REFERENCE_REQUIRED" in page
    assert "STYLE_REFERENCE_REQUIRED" in page
    assert "SCENE_OR_STYLE_CONTEXT_REQUIRED" in page
    assert "Fastlane Blockers" in page
    assert "resolvedRefsPayload" in page
    assert "buildProductAssetPayload" in page
    assert "saveImgOutputToLibrary" in page


def test_fastlane_generate_and_approval_guards_remain_honest():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")

    assert "NOT_FIRED_IN_SESSION" in page
    assert "EXTERNAL_RUNTIME_NOT_VERIFIED" in page
    assert "setShowGenConfirm(true)" in page
    assert "handleConfirmedGenerate" in page
    assert "Confirm &amp; Generate (live)" in page
    assert "startImgGeneration" in page
    assert "generationBlocked" in page
    assert "approvalBlocked" in page
    assert "scaleGuardFailed" in page
    assert "isChecklistComplete" in page
    assert "PENDING_REVIEW" in page
    assert "APPROVED" in page
    assert "REJECTED" in page


def test_no_live_generation_calls_in_tests():
    api = _read("dashboard/src/api/imgFactory.ts")
    assert "/api/flow/generate" in api
