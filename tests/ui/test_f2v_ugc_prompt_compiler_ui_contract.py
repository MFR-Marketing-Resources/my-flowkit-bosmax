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
    assert "Single mode compiles one anchor block." in operator_source
    assert "Switch Generation" in operator_source
    assert "to Extend to unlock Block 2 duration." in operator_source
    assert "{isExtendMode ? (" in operator_source


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
