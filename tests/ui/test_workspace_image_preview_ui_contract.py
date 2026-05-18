from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workspace_image_preview_slots_fail_closed():
    slot_source = _read("dashboard/src/components/workspace/WorkspaceImageAssetSlot.tsx")
    f2v_source = _read("dashboard/src/components/workspace/F2VModule.tsx")
    i2v_source = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_source = _read("dashboard/src/components/workspace/IMGModule.tsx")

    for token in [
        "Image preview failed",
        "Open Preview",
        "Download",
        "Replace image",
        "onError",
    ]:
        assert token in slot_source

    assert "Image preview failed. Upload a manual Start Frame replacement" in f2v_source
    assert "WorkspaceImageAssetSlot" in f2v_source
    assert "WorkspaceImageAssetSlot" in i2v_source
    assert "WorkspaceImageAssetSlot" in img_source
