from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_operator_video_lanes_resume_the_active_single_flight_job():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert 'err.detail === "VIDEO_JOB_IN_FLIGHT"' in source
    assert "err.active_job" in source
    assert "void pollJob(String(err.active_job))" in source
    for status in (
        "RENDER_NOT_MATERIALIZED",
        "STALE_OR_FOREIGN_CANDIDATES_ONLY",
        "REJECTED",
    ):
        assert status in source


def test_faceless_lane_resumes_the_active_single_flight_job():
    source = _read("dashboard/src/pages/FacelessVideoPage.tsx")
    assert 'err.detail === "VIDEO_JOB_IN_FLIGHT"' in source
    assert "err.active_job" in source
    assert "void pollJob(String(err.active_job), requestId)" in source
    for status in (
        "RENDER_NOT_MATERIALIZED",
        "STALE_OR_FOREIGN_CANDIDATES_ONLY",
        "REJECTED",
    ):
        assert status in source
