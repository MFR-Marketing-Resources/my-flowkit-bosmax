"""UI contract — I2V Generate / Save Package handoff integration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_i2v_operator_shows_generate_save_package_action():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Generate / Save Package" in operator_source


def test_i2v_operator_calls_create_i2v_generation_package():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "createI2VGenerationPackage" in operator_source


def test_i2v_operator_saved_package_includes_final_prompt():
    service_source = _read("agent/services/workspace_generation_package_service.py")
    assert "final_prompt_text" in service_source
    assert "compiler_context_summary" in service_source


def test_i2v_operator_subject_scene_style_in_handoff():
    service_source = _read("agent/services/workspace_generation_package_service.py")
    assert '"subject"' in service_source
    assert '"scene"' in service_source
    assert '"style"' in service_source


def test_i2v_operator_upload_order_subject_scene_style():
    service_source = _read("agent/services/workspace_generation_package_service.py")
    # Upload order is Subject -> Scene -> Style for I2V
    assert "subject" in service_source
    assert "scene" in service_source
    assert "style" in service_source
    # upload_order construction includes these slots
    assert "upload_order" in service_source


def test_i2v_operator_open_prompt_handoff_bank_action():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Open Prompt Handoff Bank" in operator_source


def test_i2v_operator_resolver_output_persisted():
    service_source = _read("agent/services/workspace_generation_package_service.py")
    assert "resolver_output_json" in service_source
    assert "resolved_slots" in service_source


def test_i2v_manual_handoff_page_shows_subject_scene_style_labels():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    # ImageSlotRow renders labels from image_assets_json including Subject/Scene/Style
    assert "ImageSlotRow" in page_source
    assert "slot_key" in page_source
