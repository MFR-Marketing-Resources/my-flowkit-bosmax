"""UI source contract for the Avatar Registry CSV Factory staging panel.

The Avatar Registry page must expose the staged intake flow (import candidate
CSV -> validation report -> per-row approve/reject -> export/sync) and must
route candidate CSVs through the csv-factory endpoints, never straight into
the bridge sync.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_csv_factory_panel_present():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "CSV Factory" in src
    assert "Import Candidate CSV" in src
    # Review controls.
    assert "Approve all valid" in src
    assert "Approve" in src
    assert "Reject" in src
    # Export + sync actions.
    assert "Export approved CSV" in src
    assert "Sync approved" in src


def test_csv_factory_uses_staged_endpoints():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "/api/workspace/avatar-registry/csv-factory/import" in src
    assert "/api/workspace/avatar-registry/csv-factory/batches" in src
    assert "/review" in src
    assert "/export" in src
    assert "/sync`" in src


def test_csv_factory_sync_requires_confirmation():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    handler = src.split("const handleFactorySync", 1)[1]
    handler = handler.split("const handleGenerateImage", 1)[0]
    assert "window.confirm" in handler


def test_csv_factory_surfaces_validation_report():
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    assert "Validation:" in src
    assert "PASS_WITH_WARNINGS" in src
    assert "row.errors.join" in src
    # invalid rows can never be approved from the UI
    assert "disabled={isFactoryBusy || !row.valid}" in src


def test_legacy_direct_sync_is_demoted_and_warned():
    """The legacy /avatar-registry/sync path must be explicitly labelled as
    legacy and warn that it bypasses the CSV Factory, so operators do not
    accidentally skip staging/review."""
    src = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    # Explicit legacy label instead of a plain primary "Sync CSV" action.
    assert "Legacy Direct Sync" in src
    # Bypass warning is surfaced on the legacy handler.
    handler = src.split("const handleSyncUpload", 1)[1]
    handler = handler.split("const handleGenerateImage", 1)[0]
    assert "window.confirm" in handler
    assert "BYPASSES" in handler or "bypass" in handler.lower()
    # Legacy control still targets the legacy endpoint (not removed).
    assert "/api/workspace/avatar-registry/sync" in src
