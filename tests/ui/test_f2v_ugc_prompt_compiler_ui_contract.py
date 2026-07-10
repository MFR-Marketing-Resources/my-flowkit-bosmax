from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_f2v_workspace_surfaces_ugc_prompt_compiler_controls():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    api_source = _read("dashboard/src/api/workspacePackages.ts")

    for token in [
        "UGC Prompt Compiler Controls",
        "Generation Mode",
        "Video Duration",
        "Total Video Duration",
        "Duration Authority",
        "Camera Style",
        "Character Presence",
        "Creator Persona",
        "Language Policy",
        "recommended shot(s)",
        "two-step bridge",
        "Regenerate Final Prompt",
    ]:
        assert token in operator_source

    for token in [
        "generation_mode",
        "target_language",
        "camera_style",
        "character_presence",
        "creator_persona",
        "blocks",
        "fetchPromptCompilerRuntimeConfig",
    ]:
        assert token in api_source


def test_f2v_single_mode_exposes_one_authoritative_video_duration():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")

    assert 'const isExtendMode = generationMode === "EXTEND";' in operator_source
    assert 'id="operator-video-duration"' in operator_source
    assert 'name="operator_video_duration"' in operator_source
    assert "One complete video" in operator_source
    assert "Block 1 Duration" not in operator_source
    assert "Block 2 Duration" not in operator_source


def test_operator_extend_multi_block_split_contract():
    """BLOCK-SPLIT fix: Extend surfaces a total-duration control that drives the
    workbook N-block plan (not capped at 2), shows the resolved plan before Load
    Package, and fails closed on unsupported totals. All video modes share this
    OperatorPage path."""
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    api_source = _read("dashboard/src/api/workspacePackages.ts")

    for token in [
        "Total Video Duration",
        'id="operator-extend-total-duration"',
        "extendTotalOptions",
        "OPERATOR_EXTEND_PLAN_BY_TOTAL",
        "OPERATOR_EXTEND_ROUTE",
        "operator-duration-authority-summary",
        "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        "UNSUPPORTED_EXTEND_TOTAL_DURATION_",
        "requested_total_duration_seconds: extendTotalDurationSeconds",
        'engine_duration_target: "GOOGLE_FLOW"',
    ]:
        assert token in operator_source, token

    # One shared builder feeds preview, execution package, and saved handoff.
    assert operator_source.count("...durationAuthority.payload") >= 3
    assert "GOOGLE_FLOW_VEO_EXTEND" not in operator_source
    assert "requested_total_duration_seconds" in api_source


def test_f2v_workspace_form_controls_have_stable_autofill_identifiers():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")

    for token in [
        'id="operator-generation-mode"',
        'name="operator_generation_mode"',
        'id="operator-target-language"',
        'name="operator_target_language"',
        'id="operator-video-duration"',
        'name="operator_video_duration"',
        'id="operator-camera-style"',
        'name="operator_camera_style"',
        'id="operator-character-presence"',
        'name="operator_character_presence"',
        'id="operator-creator-persona"',
        'name="operator_creator_persona"',
    ]:
        assert token in operator_source

    for token in [
        "workspacePackage.prompt_blocks.map((block) =>",
        'id="f2v-manual-prompt"',
        'name="f2v_manual_prompt"',
        'id="f2v-generation-model"',
        'name="f2v_generation_model"',
    ]:
        assert token in f2v_source


def test_handoff_bank_renders_all_prompt_blocks():
    """Prompt Handoff Bank maps EVERY block (not just Block 1) into a separate
    copy box — mode-agnostic over prompt_blocks_json, so F2V/HYBRID/I2V/T2V all
    expose each block separately for the manual Extend workflow.

    Block 1 copies Initial Generation; Block 2+ primary is Extend Prompt with a
    secondary Independent Block Prompt fallback.
    """
    src = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "pkg.prompt_blocks_json" in src
    assert "blocks.map((block, i) =>" in src
    assert "flow_extend_prompt_text" in src
    assert "independent_block_prompt_text" in src or "engine_prompt_text" in src
    assert "Copy Extend Prompt" in src
    assert "Copy Initial Prompt" in src
    assert "Copy Independent Block Prompt" in src
    assert "Block ${block.block_index}" in src
    assert "blocks.length} blocks" in src  # count is dynamic, not a hardcoded 1


def test_storyboard_first_plan_is_visible_in_operator_preview_and_handoff_bank():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    handoff_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")

    for token in [
        "operator-storyboard-plan-summary",
        "Storyboard-first plan",
        "Full dialogue:",
        "storyboard-allocation-summary",
        "Exact dialogue:",
    ]:
        assert token in operator_source, token

    for token in [
        "storyboard-plan-summary",
        "storyboardPlan",
        "Allocated story:",
        "Allocated dialogue:",
        "Seam:",
    ]:
        assert token in handoff_source, token


def test_operator_extend_requires_total_and_hides_manual_duration_controls():
    """Production EXTEND owns one total only; stale or manual block state never
    reaches preview or generation from the normal shared operator surface."""
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "const extendTotalRequired" in src
    assert src.count("extendTotalRequired") >= 5
    assert "if (extendTotalRequired) {" in src
    assert "if (extendTotalRequired) setPreviewPackage(null);" in src
    assert "Production EXTEND requires one Total Video Duration" in src
    assert "WPS Engine Vendor" not in src
    assert "WPS Total Duration" not in src
    assert "operator-block-1-duration" not in src
    assert "operator-block-2-duration" not in src
