from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_manifest_loads_selector_registry_before_flow_dom():
    manifest = _read("extension/manifest.json")

    # Contract migration (commit 1c7bd51, "land API-first runtime unit"): gfv2-readiness.js
    # was intentionally inserted into the content-script load order between
    # selector-registry.js and content-flow-dom.js. The core invariant this test guards —
    # selector-registry.js loads BEFORE content-flow-dom.js — still holds in the new order.
    assert (
        '"js": ["content.js", "selector-registry.js", "gfv2-readiness.js", "content-flow-dom.js"]'
        in manifest
    )
    js_order = manifest.split('"js": [', 1)[1].split("]", 1)[0]
    assert js_order.index("selector-registry.js") < js_order.index("content-flow-dom.js")


def test_selector_registry_declares_required_phase_1c_entries():
    registry_source = _read("extension/selector-registry.js")

    for token in [
        'const FLOWKIT_SELECTOR_REGISTRY_VERSION = "2026-05-24-phase1c-selector-registry";',
        "flow_config_launcher_compact",
        "flow_config_surface_portal",
        "f2v_collapsed_config_launcher",
        "generate_button_composer_scoped",
        "generate_button_icon_path_fallback",
        "upload_slot_label_scan",
        "asset_picker_modal_surface",
        "upload_acceptance_preview_evidence",
        "upload_fixed_overlay_scan",
        "verification_status: \"PROVEN\"",
        "verification_status: \"UNSTABLE\"",
        "verification_status: \"DEPRECATED\"",
        "buildEvidencePointer",
    ]:
        assert token in registry_source


def test_flow_dom_consumes_registry_for_proven_and_unstable_lanes():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "function getSelectorRegistryHelpers() {",
        "flow_config_launcher_compact",
        "flow_config_surface_portal",
        "f2v_collapsed_config_launcher",
        "generate_button_composer_scoped",
        "upload_slot_label_scan",
        "asset_picker_modal_surface",
        "upload_acceptance_preview_evidence",
        "buildSelectorEvidenceMeta('upload_slot_label_scan')",
        "buildSelectorEvidenceMeta('generate_button_composer_scoped')",
        "selector_registry_ids:",
        "fallback_policies:",
    ]:
        assert token in dom_source


def test_package_json_exposes_local_registry_validation_command():
    package_json = _read("package.json")

    assert '"test:selector-registry": "node scripts/test-flow-selector-registry.js"' in package_json
