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
        "Block 1 Duration",
        "Block 2 Duration",
        "Camera Style",
        "Character Presence",
        "Creator Persona",
        "Language Policy",
        "Recommended Shots",
        "Load F2V Package + Generate Final Prompt",
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


def test_f2v_single_mode_hides_block_2_duration_until_extend():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")

    assert 'const isExtendMode = generationMode === "EXTEND";' in operator_source
    assert (
        "Single mode generates one prompt block only and will not split."
        in operator_source
    )
    assert "Switch Generation" in operator_source
    assert "to Extend to produce a multi-block chain." in operator_source
    assert "{isExtendMode ? (" in operator_source


def test_operator_extend_multi_block_split_contract():
    """BLOCK-SPLIT fix: Extend surfaces a total-duration control that drives the
    workbook N-block plan (not capped at 2), shows the resolved plan before Load
    Package, and fails closed on unsupported totals. All video modes share this
    OperatorPage path."""
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    api_source = _read("dashboard/src/api/workspacePackages.ts")

    for token in [
        "Extend Total Duration",
        'id="operator-extend-total-duration"',
        "extendTotalOptions",
        "extendPlanByTotal",
        # rule 8: resolved block plan shown before Load Package
        "Block plan (Google Flow):",
        # rule 5: fail-closed messaging for unsupported totals
        "UNSUPPORTED_EXTEND_TOTAL_DURATION_",
        # rules 1-7: total forwarded so the backend workbook derives N blocks
        "requested_total_duration_seconds: extendTotalValue",
        'engine_duration_target: engineDurationTarget || "GOOGLE_FLOW"',
    ]:
        assert token in operator_source, token

    # rule 9: preview + generate both forward the total (identical payloads)
    assert (
        operator_source.count("requested_total_duration_seconds: extendTotalValue") >= 2  # preview + generate (+ f2v/i2v handoff)
    )
    assert "requested_total_duration_seconds" in api_source


def test_f2v_workspace_form_controls_have_stable_autofill_identifiers():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")

    for token in [
        'id="operator-generation-mode"',
        'name="operator_generation_mode"',
        'id="operator-target-language"',
        'name="operator_target_language"',
        'id="operator-block-1-duration"',
        'name="operator_block_1_duration"',
        'id="operator-block-2-duration"',
        'name="operator_block_2_duration"',
        'id="operator-camera-style"',
        'name="operator_camera_style"',
        'id="operator-character-presence"',
        'name="operator_character_presence"',
        'id="operator-creator-persona"',
        'name="operator_creator_persona"',
    ]:
        assert token in operator_source

    for token in [
        'id={`f2v-prompt-block-${block.block_index}`}',
        'name={`f2v_prompt_block_${block.block_index}`}',
        'id="f2v-manual-prompt"',
        'name="f2v_manual_prompt"',
        'id="f2v-generation-model"',
        'name="f2v_generation_model"',
    ]:
        assert token in f2v_source


def test_handoff_bank_renders_all_prompt_blocks():
    """Prompt Handoff Bank maps EVERY block (not just Block 1) into a separate
    copy box — mode-agnostic over prompt_blocks_json, so F2V/HYBRID/I2V/T2V all
    expose each block separately for the manual Extend workflow."""
    src = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "pkg.prompt_blocks_json" in src
    assert "blocks.map((block, i) =>" in src
    assert "text={block.engine_prompt_text}" in src
    assert "Block ${block.block_index}" in src
    assert "blocks.length} blocks" in src  # count is dynamic, not a hardcoded 1


def test_operator_extend_manual_no_total_blocks_load_and_generate():
    """Counter-audit: EXTEND with no Extend Total is DEV/ADVANCED-only and fails
    closed at the backend. The UI must block BOTH Load and Generate (and the handler
    must guard, and a stale preview must be invalidated) so a normal operator can
    never trigger a rejected API call."""
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    # the blocked condition is defined once, early
    assert 'generationMode === "EXTEND" && extendTotalValue === null' in src
    assert "const extendManualBlocked" in src
    # def + clearing-effect(body+dep) + Load disabled + Load blocker + Generate
    # disabled + handler guard all reference it
    assert src.count("extendManualBlocked") >= 5
    # the Generate handler guards BEFORE any API call
    assert "if (extendManualBlocked) {" in src
    # a stale preview is invalidated on entering the blocked state
    assert "if (extendManualBlocked) setPreviewPackage(null);" in src
    # inline operator blocker on the Load path
    assert "Production EXTEND requires an Extend Total" in src
