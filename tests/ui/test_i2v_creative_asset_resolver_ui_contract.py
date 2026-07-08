from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_i2v_module_exposes_semantic_controls_before_engine_slots():
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    api_source = _read("dashboard/src/api/workspacePackages.ts")

    for token in [
        "Semantic Asset Resolver",
        "Product Reference",
        "Character / Creator",
        "Scene Context",
        "Style / Mood",
        "Recipe",
        "Resolved Engine Slots",
        "Resolver Transparency",
        "Resolver Status",
        "Manual slot upload override is active for this run only.",
        "Refresh eligibility",
        "Library has",
        "API fetch failed",
    ]:
        assert token in i2v_source

    for token in [
        "/api/workspace/i2v/resolve-slots",
        "recipe_id",
        "character_reference_asset_id",
        "scene_context_reference_asset_id",
        "style_reference_asset_id",
    ]:
        assert token in api_source


def test_i2v_module_keeps_prompt_and_manual_upload_fallback_surfaces():
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")

    for token in [
        "Prompt Injection",
        "Auto Package Baseline",
        "Manual Override",
        "SEND TO FLOW EDITOR",
        "Upload subject override",
        "Upload scene override",
        "Upload style override",
        "handleAssetUpload",
        "createWorkspaceExecutionPackage",
        "fetchCreativeAssetEligibilityAudit",
        "eligible_assets",
    ]:
        assert token in i2v_source
