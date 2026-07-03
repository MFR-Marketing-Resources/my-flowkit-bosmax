"""Dashboard source contract for the Copy Strategy Studio (Phase 2 UI).

Grep-based contract (same pattern as the other tests/ui/*_ui_contract.py): it
locks the API client → page → route wiring so a future edit cannot silently drop
the copy-set approval loop, and asserts the engine-safety boundary (diagnostics
never labeled as prompt output).
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_copy_sets_api_client_wires_all_endpoints():
    api_source = _read("dashboard/src/api/copySets.ts")
    for token in [
        "/api/copy-sets/generate",
        "/api/copy-sets/product/",
        "/approve",
        "/reject",
        "/regenerate",
        'COPY_SET_APPROVAL_PHRASE = "APPROVE_COPY_SET"',
        "export async function generateCopySet",
        "export async function listCopySetsForProduct",
        "export async function getCopySet",
        "export async function patchCopySet",
        "export async function approveCopySet",
        "export async function rejectCopySet",
        "export async function regenerateCopySet",
    ]:
        assert token in api_source


def test_copy_strategy_studio_page_surfaces_approval_loop():
    page_source = _read("dashboard/src/pages/CopyStrategyStudioPage.tsx")
    for token in [
        "Copy Strategy Studio",
        "Generate Copy Set",
        "Save / Edit",
        "Regenerate",
        "Approve Copy Set",
        "Reject",
        "Completeness",
        "Claim / Risk Safety",
        "COPY_SET_APPROVAL_PHRASE",
        "COPY_APPROVED",
        "COPY_REJECTED",
        "COPY_REVIEW_REQUIRED",
        "Dedupe match",
    ]:
        assert token in page_source


def test_copy_strategy_studio_keeps_engine_prompt_boundary():
    page_source = _read("dashboard/src/pages/CopyStrategyStudioPage.tsx")
    # Diagnostics (source/provenance) must be explicitly flagged as NOT prompt output,
    # and the page must not send anything to Google Flow in this phase.
    assert "NOT part of any engine-facing prompt" in page_source
    assert "No Google Flow execution happens here" in page_source


def test_copy_strategy_studio_is_routed_and_navigable():
    app_source = _read("dashboard/src/App.tsx")
    assert 'import CopyStrategyStudioPage from "./pages/CopyStrategyStudioPage"' in app_source
    assert 'path="/copy-strategy"' in app_source
    assert "<CopyStrategyStudioPage />" in app_source
    assert '"/copy-strategy"' in app_source  # nav item
    assert "Copy Strategy Studio" in app_source  # nav label
