from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_package_json_exposes_phase_1b_first_command():
    package_json = _read("package.json")

    assert '"test:phase1b:first": "node scripts/test-f2v-playwright-persistent-context.js"' in package_json
    assert '"test:f2v-playwright-persistent-context": "node scripts/test-f2v-playwright-persistent-context.js"' in package_json


def test_manifest_authorizes_local_playwright_harness_page():
    manifest = _read("extension/manifest.json")

    for token in [
        '"http://127.0.0.1/*"',
        '"http://localhost/*"',
    ]:
        assert token in manifest


def test_flow_dom_exposes_playwright_test_bridge_only_for_harness_marker():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "const FLOW_KIT_PLAYWRIGHT_HARNESS = hasPlaywrightHarnessMarker();",
        "const FLOW_KIT_TEST_BRIDGE_SOURCE = 'FLOWKIT_PLAYWRIGHT_TEST_BRIDGE';",
        "document.documentElement?.getAttribute('data-flowkit-harness') === 'playwright'",
        "window.postMessage({",
        "direction: 'response'",
        "ERR_UNKNOWN_TEST_ACTION:",
    ]:
        assert token in dom_source


def test_playwright_harness_script_loads_unpacked_extension_and_runs_start_slot_upload():
    harness_script = _read("scripts/test-f2v-playwright-persistent-context.js")

    for token in [
        "chromium.launchPersistentContext",
        "channel: \"chromium\"",
        "--disable-extensions-except=",
        "--load-extension=",
        "RUN_FIRST npm run test:phase1b:first",
        "FLOWKIT_PLAYWRIGHT_TEST_BRIDGE",
        "simulateFileUpload",
        "PASS Playwright persistent-context harness",
    ]:
        assert token in harness_script
