from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_operator_authoring_pages_remove_embedded_mode_specific_jobs_panels():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")

    for token in [
        "Text to Video Workspace Jobs",
        "Frames Workspace Jobs",
        "Ingredients Workspace Jobs",
        "Image Workspace Jobs",
    ]:
        assert token not in operator_source

    assert 'title="Workspace Jobs"' in operator_source
    assert "isPortalMode && compactPane === \"jobs\"" in operator_source
    assert "(!isPortalMode || compactPane === \"jobs\")" not in operator_source
    assert "grid flex-1 min-h-0 gap-6 xl:grid-cols" not in operator_source


def test_operator_authoring_pages_keep_workspace_controls_and_modules():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")
    t2v_source = _read("dashboard/src/components/workspace/T2VModule.tsx")
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_source = _read("dashboard/src/components/workspace/IMGModule.tsx")

    for token in [
        "Generation Mode",
        "Language",
        # Unified Duration Authority UX: the legacy per-block "Block 1/2 Duration"
        # controls were removed. SINGLE exposes one "Video Duration"; EXTEND exposes
        # one "Total Video Duration" plus the read-only "Duration Authority" summary.
        "Video Duration",
        "Total Video Duration",
        "Duration Authority",
        "Camera Style",
        "Character Presence",
        "Creator Persona",
        "Language Policy",
        # The load+generate CTA is a per-mode label from packageBridgeFlowLabelByMode
        # ("... + Generate Final Prompt"); assert the stable shared suffix.
        "Generate Final Prompt",
        "Regenerate Final Prompt",
        "Package Eligibility",
    ]:
        assert token in operator_source

    for token in [
        "Start Frame",
        "End Frame (Optional)",
        "Prompt Injection",
        "Flow Mirror Settings",
    ]:
        assert token in f2v_source

    assert "<T2VModule" in operator_source
    assert "<F2VModule" in operator_source
    assert "<I2VModule" in operator_source
    assert "<IMGModule" in operator_source
    assert "Approved product package loaded" in t2v_source
    assert "Semantic Asset Resolver" in i2v_source
    assert "Resolved Engine Slots" in i2v_source
    assert "Resolved product image is the default subject" in img_source


def test_workspace_modules_use_page_scroll_and_clear_auto_vs_manual_sections():
    t2v_source = _read("dashboard/src/components/workspace/T2VModule.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_source = _read("dashboard/src/components/workspace/IMGModule.tsx")

    for source in [t2v_source, f2v_source, i2v_source, img_source]:
        assert "overflow-y-auto" not in source
        assert "Auto Package Baseline" in source or "Manual Prompt Injection" in source
        assert "Manual Override" in source or "Manual Prompt Injection" in source
        assert "xl:sticky xl:top-4" in source

    assert "Auto Asset Baseline" in f2v_source
    assert 'const F2V_DEFAULT_MODEL = "Veo 3.1 - Lite";' in f2v_source
    assert "<option>Veo 3.1 - Pro</option>" not in f2v_source
    assert "<option>Nano Banana 2</option>" not in f2v_source
    assert "Product Reference" in i2v_source
    assert "Auto Asset Baseline" in img_source
    assert "Manual Asset Upload" in f2v_source
    assert "Manual Override" in i2v_source
    assert "Manual Asset Upload" in img_source


def test_workspace_runtime_lane_wires_t2v_i2v_img_through_flow_editor_runtime():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    t2v_source = _read("dashboard/src/components/workspace/T2VModule.tsx")
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_source = _read("dashboard/src/components/workspace/IMGModule.tsx")

    assert 'data.lane === "WORKSPACE_FLOW_EDITOR_RUNTIME"' in operator_source
    for source in [t2v_source, i2v_source, img_source]:
        assert 'lane: "WORKSPACE_FLOW_EDITOR_RUNTIME"' in source
        assert 'stop_after_stage: "PROMPT_EDITABLE_AFTER_INSERT"' in source
