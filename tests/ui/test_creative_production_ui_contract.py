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
    assert "separately authorized boundary" in page
    assert 'P6_LIVE_CONFIRMATION = "AUTHORIZE_P6_LIVE_CREDIT_SPEND"' in client
    assert 'credit_policy: "EXPLICIT_CONFIRMATION_REQUIRED"' in page
    assert "live_media_authorization_granted" not in page
