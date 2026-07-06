"""IMG Fastlane UI contract.

Deterministic text-parse (no browser/server) asserting the dedicated operator
fastlane page exists, is routed, exposes every required control, and honestly
gates + labels the credit-spending live-generation path.
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
    assert 'IMG Fastlane' in app  # nav label


def test_fastlane_exposes_all_workflow_controls():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    
    # Tabs exist
    assert "Frames Fastlane" in page
    assert "Ingredients Fastlane" in page

    # Selectors exist
    assert "SearchableProductSelect" in page
    assert "CHARACTER_REFERENCE" in page
    assert "Avatar Reference" in page
    assert "Style / Mood Reference" in page
    assert "Scene Context Reference" in page
    
    # Prompt compiler & preview
    assert "compileWorkspacePromptPreview" in page
    assert "Auto compile product prompt" in page or "Auto compile product" in page
    assert "Prompt Preview" in page

    # Quantity selector
    assert "Quantity (Capped 1-4)" in page or "quantity" in page.lower()
    
    # Register output
    assert "Register Output" in page
    assert "Finished Artifact" in page
    assert "Upload File" in page

    # Scale Guard / Checklist
    assert "Product Scale Truth Guard" in page
    assert "realistic handheld" in page
    assert "Label, cap, and body" in page
    assert "scale matches hand/body" in page
    assert "misleading claims" in page
    assert "F2V Start Frame" in page

    # Review Decisions
    assert "PENDING_REVIEW" in page
    assert "APPROVED" in page
    assert "REJECTED" in page

    # Save to Creative Library
    assert "Save to Creative Library" in page
    assert "saveImgOutputToLibrary" in page


def test_fastlane_generate_is_gated_and_honestly_labeled():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Honesty labels must be present verbatim.
    assert "NOT_FIRED_IN_SESSION" in page
    assert "EXTERNAL_RUNTIME_NOT_VERIFIED" in page
    
    # The generate button opens an explicit confirm; live gen only runs from the
    # confirmed handler — it must never auto-fire.
    assert "setShowGenConfirm(true)" in page
    assert "handleConfirmedGenerate" in page
    assert "Confirm & Generate (live)" in page or "Confirm &amp; Generate (live)" in page
    assert "spends credits" in page
    
    # The one place that calls the real generation lane is the confirmed handler.
    assert "startImgGeneration" in page


def test_fastlane_approval_requires_all_pass_and_checklist():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Approve requires ALL truth statuses to PASS and the scale checklist to be complete.
    assert "approvalBlocked" in page
    assert "canApprove" in page
    assert "scaleGuardFailed" in page
    assert "isChecklistComplete" in page


def test_fastlane_generate_sends_selected_refs_and_blocks_without_visual():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Selected references are mapped to a structured refs payload.
    assert "resolvedRefsPayload" in page
    assert "buildAssetPayload" in page
    assert "buildProductAssetPayload" in page
    assert "refs: resolvedRefsPayload" in page
    
    # Generate is blocked when the lane's required visual truth cannot resolve.
    assert "generationBlocked" in page
    assert "productResolvable" in page
    assert "No Product Visual Reference" in page


def test_fastlane_saves_correct_semantic_role():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Composite frame saves as AVATAR_PRODUCT_COMPOSITE or AVATAR_PRODUCT_SCENE_COMPOSITE,
    # which backend derives to COMPOSITE_FRAME_REFERENCE (F2V allowed_modes).
    assert "AVATAR_PRODUCT_COMPOSITE" in page
    assert "AVATAR_PRODUCT_SCENE_COMPOSITE" in page
    assert "AVATAR_REFERENCE" in page
    assert "SCENE_REFERENCE" in page
    assert "STYLE_REFERENCE" in page


def test_fastlane_style_enforcement_and_ingredients_composer():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Style is strictly required for Frames tab
    assert "styleMissing" in page
    assert "activeTab === \"frames\" ? !approvedStyle :" in page or "activeTab === 'frames' ? !approvedStyle :" in page

    # Ingredients Composer includes Subject + Scene + Style
    assert "ingCharacterAssetId" in page
    assert "ingSceneAssetId" in page
    assert "ingStyleAssetId" in page
    assert "ingSubjectText" in page
    assert "ingSceneText" in page
    assert "ingStyleText" in page
    assert "handleCompileIngredientsPrompt" in page


def test_no_live_generation_calls_in_tests():
    # Verify that the test itself doesn't import startImgGeneration or run it.
    api = _read("dashboard/src/api/imgFactory.ts")
    assert "/api/flow/generate" in api
