from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_image_library_uses_persistent_manual_delete_contract():
    page = _read("dashboard/src/pages/LibraryPage.tsx")
    app = _read("dashboard/src/App.tsx")
    api = _read("dashboard/src/api/imgFactory.ts")
    flow = _read("agent/api/flow.py")

    assert "Image kekal disimpan sehingga anda padam secara manual" in page
    assert "Persistent · manual delete" in page
    assert "deleteImageArtifact" in page
    assert 'label: "Image Library (Manual Delete)"' in app
    assert "export async function deleteImageArtifact" in api
    assert "ONLY_IMAGE_ARTIFACTS_HAVE_MANUAL_DELETE" in flow
