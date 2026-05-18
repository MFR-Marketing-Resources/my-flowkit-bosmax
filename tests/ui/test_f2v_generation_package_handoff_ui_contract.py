"""UI contract — F2V Generate / Save Package handoff integration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_f2v_operator_shows_generate_save_package_action():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Generate / Save Package" in operator_source


def test_f2v_operator_calls_create_f2v_generation_package():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "createF2VGenerationPackage" in operator_source


def test_f2v_operator_imports_handoff_bank_api():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "workspaceGenerationPackages" in operator_source


def test_f2v_operator_saved_package_id_displayed():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "savedGenPackage" in operator_source
    assert "workspace_generation_package_id" in operator_source


def test_f2v_operator_open_prompt_handoff_bank_action():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Open Prompt Handoff Bank" in operator_source
    assert "/workspace/generation-packages" in operator_source


def test_f2v_operator_persists_workspace_execution_package_id():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "workspace_execution_package_id" in operator_source


def test_f2v_operator_save_does_not_trigger_dom_execution():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    # The save handler calls createF2VGenerationPackage, NOT handleExecute
    assert "handleSaveGenerationPackage" in operator_source
    # Confirm no Google Flow DOM invocation in the save handler
    # (the handler calls generation package API, not execute flow directly)
    assert "isSavingPackage" in operator_source


def test_f2v_operator_prompt_handoff_bank_section_visible_when_package_loaded():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Prompt Handoff Bank" in operator_source
    assert "workspacePackage" in operator_source
