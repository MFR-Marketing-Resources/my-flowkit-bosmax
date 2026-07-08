from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_avatar_registry_bulk_ui_contract_tokens():
    page = _read("dashboard/src/pages/AvatarRegistryPage.tsx")
    for token in [
        "data-testid=\"bulk-generate-selected\"",
        "data-testid=\"bulk-select-all\"",
        "data-testid=\"bulk-cancel-run\"",
        "data-testid=\"bulk-retry-failed\"",
        "data-testid=\"bulk-register-assets\"",
        "data-testid=\"bulk-resume-run-select\"",
        "data-testid=\"bulk-recovery-note\"",
        "handleBulkCreateAndStart",
        "BULK_CANCEL_CONFIRM",
        "Submitted or running Flow jobs may not be cancellable remotely",
        "Confirm to spend Flow credits",
        "listBulkRuns",
        "resumeBulkRun",
        "selectedCodes",
        "bulkRunDetail.items",
    ]:
        assert token in page, f"missing UI contract token: {token}"


def test_bulk_generation_client_list_runs_contract():
    client = _read("dashboard/src/api/bulkGeneration.ts")
    assert "export async function listBulkRuns" in client
    assert "`${BASE}/runs?limit=${limit}`" in client or "/runs?limit=" in client