"""Active video surfaces recover session results by durable identity only."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_all_video_surfaces_pass_staff_surface_and_durable_request_identity():
    expected = {
        "dashboard/src/pages/OperatorPage.tsx": (
            'surfaceLane={isImageMode ? null : "HYBRID"}',
            "requestId={notice.requestId}",
        ),
        "dashboard/src/pages/FacelessVideoPage.tsx": (
            'surfaceLane="FACELESS"',
            "requestId={notice.requestId}",
        ),
        "dashboard/src/pages/MontagePage.tsx": (
            'surfaceLane="MONTAGE"',
            "requestId={run?.montage_run_id",
        ),
        "dashboard/src/pages/CreativeProductionStudioPage.tsx": (
            'surfaceLane="PRODUCTION_STUDIO_P6"',
            "requestId={detail?.plan.request_id",
        ),
    }
    for path, markers in expected.items():
        source = _read(path)
        assert "staffId={staffIdentity.staffId}" in source
        assert all(marker in source for marker in markers)


def test_results_sidebar_never_globally_discovers_recent_video_artifacts():
    source = _read("dashboard/src/components/workspace/ResultsSidebar.tsx")
    assert "/api/results/recover?" in source
    assert "/api/flow/artifacts?" not in source
    for correlation in ("staff_id", "surface_lane", "job_id", "request_id"):
        assert correlation in source


def test_montage_and_p6_collectors_expose_final_bindings_only():
    source = _read("dashboard/src/utils/videoSessionResults.ts")
    montage = source[source.index("export function collectMontageSessionResults"):]
    production = source[source.index("export function collectCreativeProductionSessionResults"):]
    assert "final_media_id" in montage
    assert "video_media_id" not in montage.split(
        "export function collectCreativeProductionSessionResults", 1
    )[0]
    assert "output_media_id" in production
    assert "artifact_media_id" not in production
