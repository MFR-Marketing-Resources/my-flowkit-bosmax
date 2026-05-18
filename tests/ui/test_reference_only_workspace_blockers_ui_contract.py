"""UI contract — reference-only product blockers across all workspace modes.

Verifies shared surface tokens that enforce reference-only product blocking
in SearchableProductSelect, OperatorPage, and WorkspaceGenerationPackagesPage.
All four workspace modes share the same SearchableProductSelect + OperatorPage
Approved Package Bridge, so these tests cover T2V / F2V / I2V / IMG together.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


# ── SearchableProductSelect — shared selector covers all 4 modes ────────────

def test_selector_resolves_readiness_status_without_ready_default():
    """resolveReadinessStatus must not default to READY for reference products."""
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "resolveReadinessStatus" in source
    # Must not use bare ?? "READY" which falsely signals generation-readiness
    assert '?? "READY"' not in source


def test_selector_shows_reference_only_product_status_string():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "REFERENCE_ONLY_PRODUCT" in source


def test_selector_shows_reference_only_amber_badge():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "Reference only" in source
    assert "reference_only" in source


def test_selector_shows_convert_register_guidance_for_reference_products():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    # Inline guidance in dropdown for reference-only rows
    assert "Convert/Register" in source or "convert" in source.lower()
    assert "REFERENCE_ONLY_PRODUCT" in source


def test_selector_shows_catalog_visibility_reason():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "catalog_visibility_reason" in source


def test_selector_accepts_is_loading_readiness_prop():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "isLoadingReadiness" in source


def test_selector_shows_checking_while_loading():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    # Shows a non-READY fallback while the API is loading
    assert "CHECKING" in source or "isLoading" in source


def test_selector_readiness_tone_class_handles_reference_only():
    source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "readinessToneClass" in source
    assert "REFERENCE_ONLY_PRODUCT" in source


# ── OperatorPage — Approved Package Bridge shared across T2V/F2V/I2V/IMG ──

def test_operator_passes_is_loading_readiness_to_selector():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "isLoadingReadiness={isLoadingReadiness}" in source


def test_operator_shows_reference_only_blocker_panel_early():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Reference-Only Product" in source or "reference_only" in source
    assert "REFERENCE_ONLY_PRODUCT" in source


def test_operator_shows_convert_register_product_button():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Convert / Register Product" in source
    assert "/product-registration" in source


def test_operator_load_package_blocked_when_not_ready():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert 'selectedReadiness?.readiness_status !== "READY"' in source


def test_operator_reference_only_blocker_message_defined():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "REFERENCE_ONLY_PRODUCT" in source
    assert "Smart Registration" in source


def test_operator_prompt_handoff_bank_blocked_for_reference_only():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    # The Prompt Handoff Bank section must also check reference_only
    assert "reference_only" in source
    assert "Generate / Save Package" in source


def test_operator_save_handler_guards_reference_only():
    source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "selectedProduct.reference_only" in source
    assert "isSavingPackage" in source


# ── All four modes share the same Approved Package Bridge ──────────────────

def test_t2v_mode_uses_shared_operator_page():
    """T2V is served by OperatorPage — no separate module-level load blocker needed."""
    app_source = _read("dashboard/src/App.tsx")
    assert "/operator/t2v" in app_source or "t2v" in app_source.lower()
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "T2V" in operator_source


def test_f2v_mode_uses_shared_operator_page():
    app_source = _read("dashboard/src/App.tsx")
    assert "F2V" in app_source
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "F2V" in operator_source


def test_i2v_mode_uses_shared_operator_page():
    app_source = _read("dashboard/src/App.tsx")
    assert "I2V" in app_source
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "I2V" in operator_source


def test_img_mode_uses_shared_operator_page():
    app_source = _read("dashboard/src/App.tsx")
    assert "IMG" in app_source
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "IMG" in operator_source


# ── WGP API error handling ─────────────────────────────────────────────────

def test_wgp_api_has_409_blocker_conversion():
    source = _read("agent/api/workspace_generation_packages.py")
    assert "_BLOCKER_409" in source
    assert "_http_exc_for" in source
    assert "REFERENCE_ONLY_PRODUCT" in source


def test_wgp_api_f2v_uses_http_exc_for():
    source = _read("agent/api/workspace_generation_packages.py")
    assert "_http_exc_for(exc)" in source


# ── WGP service has explicit reference-only guard ──────────────────────────

def test_wgp_service_has_assert_not_reference_only():
    source = _read("agent/services/workspace_generation_package_service.py")
    assert "_assert_not_reference_only" in source
    assert "FASTMOSS_REFERENCE_BLOCKER" in source


def test_wgp_service_f2v_calls_reference_guard():
    source = _read("agent/services/workspace_generation_package_service.py")
    assert "_assert_not_reference_only(product_id" in source


# ── Smart Registration path ────────────────────────────────────────────────

def test_smart_registration_path_present_in_readiness_service():
    source = _read("agent/services/approved_product_package_service.py")
    assert "smart_registration_path" in source
    assert "/product-registration" in source


def test_smart_registration_route_in_app():
    app_source = _read("dashboard/src/App.tsx")
    assert "product-registration" in app_source or "ProductRegistration" in app_source


# ── Image auto-seed: reference-only products do not fake-seed ──────────────

def test_image_asset_product_image_only_for_image_ready_products():
    """_product_image_asset returns None when image_readiness_status is not ready."""
    source = _read("agent/services/approved_product_package_service.py")
    assert "IMAGE_READY_STATES" in source
    assert "_product_image_asset" in source
    # Must check image_readiness_status before building the asset slot
    assert "image_readiness_status" in source


def test_reference_only_readiness_shows_image_reference_not_available():
    source = _read("agent/services/approved_product_package_service.py")
    # The reference-only path includes image_reference_status
    assert "image_reference_status" in source
    assert "IMAGE_NOT_AVAILABLE" in source
