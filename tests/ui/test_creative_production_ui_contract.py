from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_p6_production_studio_is_the_primary_direct_route():
    app = _read("dashboard/src/App.tsx")
    assert 'to: "/production-studio"' in app
    assert 'label: "Production Studio (P6)"' in app
    assert 'path="/production-studio"' in app
    assert "CreativeProductionStudioPage" in app


def test_legacy_studio_route_remains_compatible_but_not_primary():
    app = _read("dashboard/src/App.tsx")
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    assert 'path="/rpa-production-studio"' in app
    assert "compatibility surfaces only" in page
    assert "legacy schema is not deleted" in page


def test_ui_exposes_every_truthful_orchestrator_control_surface():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    for test_id in (
        "p6-cohort-authority",
        "p6-zero-credit-boundary",
        "p6-create-plan",
        "p6-plan-status",
        "p6-action-preflight",
        "p6-action-matrix",
        "p6-action-compile",
        "p6-action-approve",
        "p6-action-waves",
        "p6-action-dry-run",
        "p6-capacity-report",
        "p6-content-matrix",
        "p6-attempt-list",
        "p6-qa-list",
        "p6-live-confirmation",
        "p6-action-live-start",
    ):
        assert test_id in page


def test_live_and_dry_run_are_visibly_separate():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    client = _read("dashboard/src/api/creativeProduction.ts")
    assert "Compile + dry run = 0 media credits" in page
    assert "This action spends media credits" in page
    assert "sends the next queued item now" in page
    assert "authorizes the scheduler to continue" in page
    assert 'P6_LIVE_CONFIRMATION = "AUTHORIZE_P6_LIVE_CREDIT_SPEND"' in client
    assert 'credit_policy: "EXPLICIT_CONFIRMATION_REQUIRED"' in page
    assert "live_media_authorization_granted" not in page


def test_p6_v4_frame_is_opt_in_and_preserves_batch_matrix_ia():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    assert 'searchParams.get("v4") === "1"' in page
    assert 'searchParams.get("classic") !== "1"' in page
    assert '"p6-v4-shell"' in page
    assert '"p6-v4-header"' in page
    assert "WorkflowStep" in page
    assert "OperatorCockpit" in page
    assert "Batch, matrix, waves, QA, and live confirmation remain the P6 IA" in page
    assert "p6-content-matrix" in page
    assert "p6-attempt-list" in page
    assert "p6-qa-list" in page
    assert 'href="/production-studio?classic=1"' in page
    assert 'label: "Start production · gated"' in page


def test_poster_v4_frame_is_opt_in_and_preserves_bespoke_modes():
    page = _read("dashboard/src/pages/PosterBuilderPage.tsx")
    assert 'searchParams.get("v4") === "1"' in page
    assert 'searchParams.get("classic") !== "1"' in page
    assert 'data-testid="poster-builder-v4-shell"' in page
    assert 'data-variant="v4"' in page
    assert "WorkflowStep" in page
    assert "OperatorCockpit" in page
    assert "Auto, Guided, and Controlled modes preserved" in page
    assert "Auto · Guided · Controlled remain available" in page
    assert 'href="/creative/poster-builder?classic=1"' in page
    assert 'label: "Generate poster · gated"' in page


def test_poster_v4_links_to_adjacent_governed_surfaces():
    page = _read("dashboard/src/pages/PosterBuilderPage.tsx")
    assert 'href="/assets/img-cockpit"' in page
    assert 'href="/creative/copy-registry"' in page
    assert 'data-testid="poster-advanced-diagnostics"' in page
    assert "PosterBuilderLegacyPanel" in page


def test_p6_uses_visual_multi_product_allocation_and_governed_video_controls():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    picker = _read(
        "dashboard/src/components/production-studio/"
        "ProductAllocationPicker.tsx"
    )
    assert "ProductAllocationPicker" in page
    assert "product_video_allocations: allocations" in page
    assert 'aria-label="Search governed products"' in picker
    assert 'aria-multiselectable="true"' in picker
    assert "Video quantity for" in picker
    assert 'aria-label="Governed video model"' in page
    assert 'aria-label="Governed video duration"' in page
    assert "fetchVideoModels" in page
    assert "Extend ·" in page
    assert "P5.8 launch cohort products" not in page
    assert "Approved model keys (comma separated)" not in page


def test_p7_and_technical_evidence_are_collapsed_without_being_deleted():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    assert 'data-testid="p7-compact-summary"' in page
    assert "<CreativeSupplyFactoryPanel />" in page
    assert "Technical details" in page
    assert "Technical execution-lane status" in page
    assert "Technical details" in page


def test_plan_state_is_explicit_and_canonical_data_is_not_reconstructed():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    for mode in (
        "NEW_DRAFT",
        "ACTIVE_PLAN",
        "UNSAVED_DRAFT_FROM_ACTIVE_PLAN",
        "LOADING_PLAN",
        "LEGACY_INCOMPLETE_PLAN",
    ):
        assert mode in page
    assert "planRequestSequence" in page
    assert "snapshot.product_allocations" in page
    assert "plans[0]" not in page
    assert "Math.floor" not in page
    assert "product_scope.map" not in page


def test_universal_factory_is_embedded_in_the_existing_production_studio():
    page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    panel = _read(
        "dashboard/src/components/production-studio/"
        "ProductTreatmentFactoryPanel.tsx"
    )
    assert "ProductTreatmentFactoryPanel" in page
    assert "<ProductTreatmentFactoryPanel />" in page
    assert 'id="product-treatment-factory"' in panel
    assert 'href="/production-studio#product-treatment-factory"' in panel
    assert "/product-treatment-factory" not in _read("dashboard/src/App.tsx")


def test_factory_operator_surface_preserves_zero_credit_and_review_authority():
    client = _read("dashboard/src/api/productTreatmentFactory.ts")
    panel = _read(
        "dashboard/src/components/production-studio/"
        "ProductTreatmentFactoryPanel.tsx"
    )
    for endpoint in ("plans", "prepare", "pause", "resume"):
        assert endpoint in client
    assert "provider_calls_enabled: false" in panel
    assert "media_generation_enabled: false" in panel
    assert "Credit spend:" in panel
    assert "never approves authority" in panel
    assert "never dispatches generation" in panel
    assert "AUTHORIZE_P6_LIVE_CREDIT_SPEND" not in panel


def test_factory_operator_surface_exposes_complete_snapshot_truth():
    panel = _read(
        "dashboard/src/components/production-studio/"
        "ProductTreatmentFactoryPanel.tsx"
    )
    for contract in (
        "ptf-loading-state",
        "ptf-empty-state",
        "ptf-error-state",
        "ptf-blocked-state",
        "ptf-success-state",
        "All active canonical products",
        "Explicit product IDs",
        "Filter factory taxonomy",
        "Filter factory readiness",
        "Filter factory next action",
        "Evidence applicability and provenance",
        "Copy and Treatment authority",
        "Action, format and visual authority",
        "Wardrobe",
        "Background / scene",
        "Eligible assets by role",
        "Per-product task isolation",
        "Plan hash",
        "Template → Treatment lineage",
    ):
        assert contract in panel
