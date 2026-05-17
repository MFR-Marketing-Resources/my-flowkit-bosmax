from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workspace_package_bridge_surfaces_approved_package_history_and_manual_fallback():
    app_source = _read("dashboard/src/App.tsx")
    page_source = _read("dashboard/src/pages/ApprovedPackagesPage.tsx")
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")

    assert "/approved-packages" in app_source
    for token in [
        "Approved Product Packages",
        "Copy Approved Prompt",
        "Open in Workspace",
        "Manual Fallback Checklist",
        "Download",
    ]:
        assert token in page_source

    for token in [
        "Approved Package Bridge",
        "prompt_package_snapshot_id",
        "workspace_execution_package_id",
    ]:
        assert token in operator_source


def test_workspace_modules_prefill_from_approved_package_payload():
    t2v_source = _read("dashboard/src/components/workspace/T2VModule.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_source = _read("dashboard/src/components/workspace/IMGModule.tsx")

    assert "Approved product package loaded" in t2v_source
    assert "Start Frame defaults to the cached product image" in f2v_source
    assert "Subject uses the cached product image" in i2v_source
    assert "Subject/reference defaults to the cached product image" in img_source
