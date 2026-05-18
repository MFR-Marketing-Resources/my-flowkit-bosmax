from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workspace_jobs_route_and_sidebar_navigation_exist():
    app_source = _read("dashboard/src/App.tsx")

    assert "/workspace/jobs" in app_source
    assert "Workspace Jobs" in app_source
    assert '{ to: "/workspace/jobs", icon: Activity, label: "Workspace Jobs" }' in app_source
    assert '{ to: "/workspace/jobs", label: "Jobs" }' in app_source


def test_workspace_jobs_page_renders_unified_table_filters_and_detail_contract():
    page_source = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")

    for token in [
        "Workspace Jobs",
        "Unified read-only workspace reporting",
        "Request ID",
        "Job Type / Mode",
        "Product / Package",
        "Status",
        "Latest Stage",
        "Created / Updated",
        "Error / Remark",
        "Actions / View Details",
        "View Details",
        "Recorded Stage History",
        "Operator Remark",
    ]:
        assert token in page_source

    for token in [
        '{ id: "ALL", label: "All" }',
        '{ id: "T2V", label: "T2V" }',
        '{ id: "F2V", label: "F2V" }',
        '{ id: "I2V", label: "I2V" }',
        '{ id: "IMG", label: "IMG" }',
        '{ id: "WAITING", label: "Waiting" }',
        '{ id: "RUNNING", label: "Running" }',
        '{ id: "COMPLETED", label: "Completed" }',
        '{ id: "FAILED", label: "Failed" }',
        "Search request ID, mode, stage, error, product...",
        "buildTelemetryHandoffTimeline",
        "classifyTelemetryExecution",
        "fetchAPI<TelemetryRequest[]>(\"/api/telemetry/requests?limit=200\")",
        "fetchAPI<TelemetryRequestDetail>(",
    ]:
        assert token in page_source
