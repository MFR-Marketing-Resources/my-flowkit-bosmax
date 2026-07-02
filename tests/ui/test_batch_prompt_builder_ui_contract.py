"""UI source contracts for the Batch Prompt / Production split dashboard.

Follows the repo's UI-contract idiom (read the built source files and assert
load-bearing tokens) — covers duration authority, HYBRID product anchor,
I2V role law, model standard, and the legacy Batch Manager purge.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


# ── Duration authority (WPS workbook) ─────────────────────────────────────


def test_builder_duration_comes_from_the_authority_endpoint_not_free_input():
    src = _read("dashboard/src/pages/BatchPromptBuilderPage.tsx")
    api = _read("dashboard/src/api/productionQueue.ts")
    assert "duration-authority" in api
    assert "Durations come from the WPS workbook authority" in src
    # No arbitrary numeric duration input: the only number input left is quantity.
    for line in src.splitlines():
        if 'type="number"' in line:
            assert "uration" not in line, f"free duration input still present: {line.strip()}"


# ── HYBRID product anchor visibility ──────────────────────────────────────


def test_hybrid_shows_product_truth_anchor_and_blocks_without_it():
    src = _read("dashboard/src/pages/BatchPromptBuilderPage.tsx")
    assert "PRODUCT TRUTH ANCHOR" in src
    assert "HYBRID blocked" in src


# ── I2V role law labels ───────────────────────────────────────────────────


def test_i2v_uses_role_contract_labels_and_validation_summary():
    src = _read("dashboard/src/pages/BatchPromptBuilderPage.tsx")
    assert "PRODUCT_REFERENCE" in src
    assert "from selected product anchor" in src
    assert "AVATAR_REFERENCE (required)" in src
    assert "STYLE_SCENE_REFERENCE (optional / scene context only)" in src
    assert "Role Map Validation" in src


# ── Model standard (engine registry) ──────────────────────────────────────


def test_send_to_production_requires_explicit_model_selection():
    src = _read("dashboard/src/pages/WorkspaceGenerationPackagesPage.tsx")
    api = _read("dashboard/src/api/productionQueue.ts")
    assert "Select engine model" in src
    assert "/api/flow/video-models" in api


def test_production_queue_page_displays_run_model():
    src = _read("dashboard/src/pages/ProductionQueuePage.tsx")
    assert "Model:" in src


# ── Legacy Batch Manager purge ────────────────────────────────────────────


def test_legacy_batches_page_is_gone_and_unrouted():
    assert not (_ROOT / "dashboard/src/pages/BatchesPage.tsx").exists(), (
        "legacy BatchesPage.tsx must stay deleted (stale engine dropdown, "
        "mixed prompt/production concept)"
    )
    app = _read("dashboard/src/App.tsx")
    assert "BatchesPage" not in app
    assert "BatchPromptBuilderPage" in app
    assert '"/batches"' in app  # route now serves the Batch Prompt Builder
    assert '"/production-queue"' in app
