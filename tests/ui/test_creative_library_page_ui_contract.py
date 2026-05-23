from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_creative_library_route_nav_and_page_contract_exist():
    app_source = _read("dashboard/src/App.tsx")
    registry_source = _read("dashboard/src/pages/AssetRegistryPage.tsx")
    generator_source = _read("dashboard/src/pages/ProductAssetGeneratorPage.tsx")
    page_source = _read("dashboard/src/pages/CreativeLibraryPage.tsx")
    api_source = _read("dashboard/src/api/creativeAssets.ts")

    for token in [
        "/assets/creative-library",
        "Creative Library",
        "Asset Registry",
        '/assets/creative-library", label: "Creative"',
        '/workspace/generation-packages", label: "Bank"',
    ]:
        assert token in app_source

    for token in [
        "Upload and store reusable creative images for workspace use:",
        "Preset Library",
        "Launch Preset",
        "DATABASE PRODUCT REQUIRED",
        "Product-holding presets force database product truth",
        "Character",
        "/ Creator",
        "Scene Context / Environment",
        "Style / Mood",
        "Composite",
        "Frame references",
        "Upload New Asset",
        "Detail Panel",
        "Archive Asset",
        "Unarchive Asset",
        "Allowed Modes",
        "Engine Slot Eligibility",
        "Mode A metadata handoff",
    ]:
        assert token in page_source

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

    for token in [
        "ecommerce_hero_clean_studio",
        "avatar_holding_product_halfbody",
        "product_scene_style_blend",
    ]:
        assert token in generator_source

    for token in [
        "This page is preview-only.",
        "reusable generated/external",
        "/assets/creative-library",
        "Open Creative Library",
    ]:
        assert token in generator_source


def test_creative_library_form_covers_required_semantic_categories():
    page_source = _read("dashboard/src/pages/CreativeLibraryPage.tsx")

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
