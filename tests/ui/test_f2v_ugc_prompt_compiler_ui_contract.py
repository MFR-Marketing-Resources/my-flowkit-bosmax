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
