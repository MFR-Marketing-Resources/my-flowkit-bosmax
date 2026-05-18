"""UI contract tests — Workspace Generation Package (Prompt Handoff Bank) page."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


# ─── Route ───────────────────────────────────────────────────

def test_generation_packages_route_registered_in_app():
    app_source = _read("dashboard/src/App.tsx")
    assert "/workspace/generation-packages" in app_source


def test_generation_packages_nav_entry_in_workspace_group():
    app_source = _read("dashboard/src/App.tsx")
    assert "Prompt Handoff Bank" in app_source


def test_generation_packages_page_imported_in_app():
    app_source = _read("dashboard/src/App.tsx")
    assert "WorkspaceGenerationPackagesPage" in app_source


# ─── Page structure ───────────────────────────────────────────

def test_page_has_prompt_handoff_bank_heading():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "Prompt Handoff Bank" in page_source


def test_page_has_table_list_rendering():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "PackageRow" in page_source
    assert "workspace_generation_package_id" in page_source


def test_page_has_detail_panel():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "PackageDetailPanel" in page_source


def test_page_has_copy_final_prompt_affordance():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "Copy Final Prompt" in page_source
    assert "copy_prompt" in page_source or "ClipboardCopy" in page_source


def test_page_has_image_open_affordance():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "Open" in page_source
    assert "preview_url" in page_source


def test_page_has_image_download_affordance():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "Download" in page_source
    assert "download_url" in page_source


def test_page_has_upload_order_panel():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "upload_order" in page_source
    assert "Upload order" in page_source


def test_page_has_filters():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "modeFilter" in page_source
    assert "statusFilter" in page_source
    assert "search" in page_source


def test_page_send_to_google_flow_is_disabled():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "Send to Google Flow" in page_source
    assert "disabled" in page_source
    assert "DOM handoff not enabled in this wave" in page_source


def test_page_dom_handoff_ready_false_assertion():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "dom_handoff_ready" in page_source


def test_page_shows_blockers_and_warnings():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "Blockers" in page_source
    assert "Warnings" in page_source


def test_page_shows_lineage_ids():
    page_source = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    assert "prompt_package_snapshot_id" in page_source
    assert "workspace_execution_package_id" in page_source


# ─── API client ───────────────────────────────────────────────

def test_api_client_exists():
    api_source = _read("dashboard/src/api/workspaceGenerationPackages.ts")
    assert "listWorkspaceGenerationPackages" in api_source
    assert "getWorkspaceGenerationPackage" in api_source
    assert "createF2VGenerationPackage" in api_source
    assert "createI2VGenerationPackage" in api_source


def test_api_client_supports_filters():
    api_source = _read("dashboard/src/api/workspaceGenerationPackages.ts")
    assert "mode" in api_source
    assert "status" in api_source
    assert "product_id" in api_source


# ─── Types ───────────────────────────────────────────────────

def test_types_exported_for_generation_package():
    types_source = _read("dashboard/src/types/index.ts")
    assert "WorkspaceGenerationPackage" in types_source
    assert "WorkspaceGenerationPackageStatus" in types_source
    assert "F2VGenerationPackageRequest" in types_source
    assert "I2VGenerationPackageRequest" in types_source
    assert "dom_handoff_ready" in types_source
