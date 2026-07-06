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
    # The Frames "Style" reference field was a dead/fake picker (no STYLE records,
    # no way to create one) — it must stay removed.
    assert "Select Existing Reference — Style" not in page
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
    assert "Confirm &amp; Generate" in page
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


# ── Forensic counter-audit V2 regression guards ──────────────────────────────
# These lock in the findings of the IMG_FASTLANE_FORENSIC_COUNTER_AUDIT_V2 so a
# future regression to the retired free-text composer, a dead/duplicate route,
# or a missing role button fails CI instead of shipping as a "stale UI" mystery.

# The retired pre-template composer UI. If any of these strings reappear in the
# page source, a stale/duplicate component has been reintroduced.
_RETIRED_COMPOSER_MARKERS = (
    "Auto compile product prompt",
    "COMPOSE SUBJECT / AVATAR",
    "COMPOSE SCENE / ENVIRONMENT",
    "COMPOSE STYLE / MOOD",
    "Describe the image prompt here",
    "SELECT EXISTING AVATAR FOR LINEAGE",
)

# The current template-driven UI markers that MUST be present.
_CURRENT_UI_MARKERS = (
    "Auto-built Prompt Preview",
    "Template Preset",
    "Select Target Ingredient Role",
    "Product Scale Truth Guard",
    "Register Output (Credit-free)",
)


def test_fastlane_has_no_retired_composer_markers():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    for marker in _RETIRED_COMPOSER_MARKERS:
        assert marker not in page, f"retired composer marker leaked back: {marker!r}"
    for marker in _CURRENT_UI_MARKERS:
        assert marker in page, f"current UI marker missing: {marker!r}"


def test_fastlane_all_four_ingredient_roles_wired():
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Canonical role enum options.
    for role in (
        "AVATAR_REFERENCE",
        "SCENE_REFERENCE",
        "STYLE_REFERENCE",
        "PRODUCT_REFERENCE",
    ):
        assert role in page
    # Each role's visible button label.
    for label in ("Subject / Avatar", "Scene", "Style", "Product / Product Lock"):
        assert label in page
    # Each role's output-role help text (independent copy per role).
    assert "Output role: CHARACTER_REFERENCE." in page
    assert "Output role: SCENE_CONTEXT_REFERENCE." in page
    assert "Output role: STYLE_REFERENCE." in page
    assert "product lock or poster-safe product reference" in page
    # Role state drives lane/preset/reference selection.
    assert "ingSaveLaneId" in page
    assert 'ingSaveLaneId === "PRODUCT_REFERENCE"' in page


def test_fastlane_product_role_resolves_lane_via_compiled_preview_not_direct_lookup():
    """PRODUCT_REFERENCE has no lane_id of its own (lanes are PRODUCT_ONLY_HERO /
    PRODUCT_POSTER), so the page MUST resolve the active lane from the compiled
    preview's lane_id, not only from a direct lanes.find(ingSaveLaneId)."""
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    assert "compiledPreview?.lane_id" in page
    assert "lanes.find((item) => item.lane_id === compiledPreview.lane_id)" in page


def test_portal_side_route_uses_same_img_fastlane_component():
    """`/assets/img-fastlane?portal=side` must render the SAME component. React
    Router matches on path only, so there must be exactly one img-fastlane route
    and no separate/duplicate portal-specific element."""
    app = _read("dashboard/src/App.tsx")
    assert app.count('path="/assets/img-fastlane"') == 1
    assert app.count("<ImgFastlanePage />") == 1
    # No alternate img-fastlane route element that could diverge under a query.
    assert "img-fastlane-side" not in app
    assert "ImgFastlaneSidePage" not in app


def test_build_identity_marker_is_wired():
    """The stale-bundle observability marker must stay wired: build-time define
    in vite config + a boot marker in main.tsx exposing window.__FLOWKIT_BUILD__."""
    vite = _read("dashboard/vite.config.ts")
    assert "__BUILD_SHA__" in vite
    assert "__BUILT_AT__" in vite
    assert "git rev-parse --short HEAD" in vite

    main = _read("dashboard/src/main.tsx")
    assert "__FLOWKIT_BUILD__" in main
    assert "__BUILD_SHA__" in main
    assert "__BUILT_AT__" in main
    assert "[flowkit] build" in main

    decl = _read("dashboard/src/build-info.d.ts")
    assert "declare const __BUILD_SHA__: string;" in decl
    assert "declare const __BUILT_AT__: string;" in decl


def test_fastlane_section_has_no_backdrop_blur_stacking_trap():
    """The Section wrapper must not use backdrop-blur. backdrop-filter creates a
    stacking context that trapped the open SearchableProductSelect dropdown (z-50)
    inside the section, so it painted BEHIND the next section and was unusable.
    Regression guard for the product-selector overlay fix."""
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    assert "shadow-black/10 backdrop-blur-md" not in page


def test_avatar_registry_back_link_is_context_aware():
    """Avatar Registry "Back" must return to the referrer (?from=...) rather than
    a hardcoded page. Regression guard: opening the registry from IMG Fastlane and
    pressing Back used to dump the user on IMG Cockpit."""
    reg = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "useSearchParams" in reg
    assert 'searchParams.get("from")' in reg
    assert "href={backTo}" in reg
    assert "{backLabel}" in reg
    # Fastlane tells the registry where Back should return to.
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    assert "/assets/avatar-registry?from=/assets/img-fastlane" in page


def test_image_gen_settings_are_a_shared_ssot():
    """Aspect / count / image-model options must come from ONE shared config
    (image-gen settings SSOT), not per-page hardcoded copies, so every image-gen
    page holds identical settings."""
    # Backend SSOT endpoint, derived from models.json.
    api = _read("agent/api/img_factory.py")
    assert '"/image-gen-settings"' in api
    assert "aspect_options" in api and "count_options" in api
    assert "IMAGE_MODELS" in api
    # Shared frontend module + hook.
    shared = _read("dashboard/src/api/imageGenSettings.ts")
    assert "useImageGenSettings" in shared
    assert "/api/img-factory/image-gen-settings" in shared
    # IMG Fastlane consumes the shared settings (no private option copies).
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    assert "useImageGenSettings" in page
    assert "imgGen.models" in page
    assert "imgGen.aspect_options" in page
    assert "IMG_MODEL_OPTIONS" not in page  # local copy removed


def test_all_image_gen_pages_share_settings_and_route_the_model():
    """Every image-gen surface consumes the shared useImageGenSettings hook and
    sends image_model end-to-end, so aspect/count/model are standardized (not
    per-page) AND the picked model actually routes (no display-only pickers)."""
    # Image Gen (IMGModule) → OperatorPage one-door.
    imgmod = _read("dashboard/src/components/workspace/IMGModule.tsx")
    assert "useImageGenSettings" in imgmod and "imgGen.models" in imgmod
    assert "image_model: model" in imgmod
    operator = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "image_model: data.image_model" in operator
    # IMG Cockpit → startImgGeneration.
    cockpit = _read("dashboard/src/pages/ImgCockpitPage.tsx")
    assert "useImageGenSettings" in cockpit and "image_model: imageModel" in cockpit
    # Avatar Registry → /generate-image backend (additive image_model/count).
    avatar = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "useImageGenSettings" in avatar and "image_model: imageModel" in avatar
    wp = _read("agent/api/workspace_packages.py")
    assert "image_model: str | None = None" in wp
    assert "image_model=request.image_model" in wp


def test_frames_flow_is_universal_and_credit_free():
    """Frames Fastlane must be a universal avatar+product Generate — no Template
    Preset dropdown, style/scene optional, and image generation labelled
    credit-free (only video burns credits). Regression guard for the rework."""
    page = _read("dashboard/src/pages/ImgFastlanePage.tsx")
    # Template Preset picker is gone; the universal generic preset is forced.
    assert 'title="Template Preset"' not in page
    assert '"GENERIC_FRAMES_AVATAR_PRODUCT"' in page
    # Style/scene never hard-block generation.
    assert "OPTIONAL_BLOCKERS" in page
    assert "hardBlockers" in page
    # The false "spends credits" claim is gone; image gen is credit-free.
    assert "Spends Credits" not in page
    assert "Credit-spending Generation" not in page
    assert "credit-free" in page
