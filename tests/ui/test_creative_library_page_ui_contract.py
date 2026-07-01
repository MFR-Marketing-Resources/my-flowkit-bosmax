from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_creative_library_route_nav_and_page_contract_exist():
    # Contract migration (commit d3add97, PR #120 "Creative Library split"):
    # the upload/metadata FORM moved out of CreativeLibraryPage.tsx (which is now a
    # read-only gallery/table surface) into CreativeLibraryWorkspacePage.tsx (the
    # detail/edit surface at /assets/creative-library/workspace). This test now asserts
    # the split contract: gallery tokens on the gallery page, form tokens on the
    # workspace page, and the nav/route/link invariants that tie them together.
    app_source = _read("dashboard/src/App.tsx")
    registry_source = _read("dashboard/src/pages/AssetRegistryPage.tsx")
    generator_source = _read("dashboard/src/pages/ProductAssetGeneratorPage.tsx")
    gallery_source = _read("dashboard/src/pages/CreativeLibraryPage.tsx")
    workspace_source = _read("dashboard/src/pages/CreativeLibraryWorkspacePage.tsx")
    api_source = _read("dashboard/src/api/creativeAssets.ts")

    for token in [
        "/assets/creative-library",
        "Creative Library",
        "Asset Registry",
        '/assets/creative-library", label: "Creative"',
        '/workspace/generation-packages", label: "Bank"',
    ]:
        assert token in app_source

    # Gallery page: list/table surface that filters assets and links to the editor.
    for token in [
        "Semantic Role",
        "All Roles",
        "All Modes",
        "Search assets",
        "/assets/creative-library/workspace",
    ]:
        assert token in gallery_source

    # Workspace editor page: the upload + semantic-metadata form (moved here in the split).
    for token in [
        "Upload Image",
        "Asset Details",
        "Allowed Modes",
        "Engine Slot Eligibility",
        "Archive Asset",
        "Unarchive Asset",
        "Mode A Metadata Handoff",
        "Character DNA",
        "Scene Context DNA",
        "Style / Mood DNA",
    ]:
        assert token in workspace_source

    # Preset card launchers must NOT appear on either Creative Library surface
    # (input-first UX refactor).
    for token in [
        "Preset Library",
        "Launch Preset",
        "DATABASE PRODUCT REQUIRED",
        "Product-holding presets force database product truth",
    ]:
        assert token not in gallery_source
        assert token not in workspace_source

    for token in [
        "/api/creative-assets?",
        "/api/creative-assets",
        "/archive",
        "/unarchive",
    ]:
        assert token in api_source

    for token in [
        "Asset Registry is read-only.",
        "open Creative",
        "/assets/creative-library",
        "Open Creative Library",
    ]:
        assert token in registry_source

    presets_source = _read(
        "dashboard/src/components/product-asset-generator/presets.ts"
    )
    for token in [
        "ecommerce_hero_clean_studio",
        "avatar_holding_product_halfbody",
        "product_scene_style_blend",
    ]:
        assert token in presets_source

    # Product Asset Generator stays preview-only and points users to Creative Library.
    for token in [
        "Preview-only",
        "No Flow execution",
        "/assets/creative-library",
        "Creative Library",
    ]:
        assert token in generator_source


def test_creative_library_form_covers_required_semantic_categories():
    # Contract migration (commit d3add97, PR #120 "Creative Library split"): the
    # semantic-category form + DNA metadata fields now live on the workspace editor
    # page (CreativeLibraryWorkspacePage.tsx), not the read-only gallery page.
    page_source = _read("dashboard/src/pages/CreativeLibraryWorkspacePage.tsx")

    for token in [
        "PRODUCT_REFERENCE",
        "CHARACTER_REFERENCE",
        "SCENE_CONTEXT_REFERENCE",
        "STYLE_REFERENCE",
        "COMPOSITE_FRAME_REFERENCE",
        "display_name",
        "visual_dna_summary",
        "character_dna",
        "scene_context_dna",
        "style_mood_dna",
    ]:
        assert token in page_source
