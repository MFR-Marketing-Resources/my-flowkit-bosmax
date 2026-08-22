from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_image_library_uses_persistent_manual_delete_contract():
    page = _read("dashboard/src/pages/LibraryPage.tsx")
    app = _read("dashboard/src/App.tsx")
    api = _read("dashboard/src/api/imgFactory.ts")
    flow = _read("agent/api/flow.py")

    assert "Images stay saved until you delete them manually" in page
    assert "Persistent · manual delete" in page
    assert "deleteImageArtifact" in page
    assert 'label: "Image Library"' in app
    assert "export async function deleteImageArtifact" in api
    assert "ONLY_IMAGE_ARTIFACTS_HAVE_MANUAL_DELETE" in flow


def test_video_library_uses_active_surface_as_primary_label():
    page = _read("dashboard/src/pages/LibraryPage.tsx")
    assert 'surface_lane' in page
    assert 'surface_label' in page
    assert 'surfaceDisplayLabel' in page
    assert 'Legacy/Internal' not in page.split('surfaceDisplayLabel', 1)[0]
    assert 'VIDEO_SURFACE_FILTERS' in page
    assert '"HYBRID"' in page
    assert '"FACELESS"' in page
    assert '"MONTAGE"' in page
    assert '"PRODUCTION_STUDIO_P6"' in page
