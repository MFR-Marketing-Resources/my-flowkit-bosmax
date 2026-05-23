from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_package_json_exposes_phase_2_first_command():
    package_json = _read("package.json")

    assert '"test:phase2:first": "node scripts/test-f2v-cdp-file-chooser-poc.js"' in package_json
    assert '"test:f2v-cdp-file-chooser-poc": "node scripts/test-f2v-cdp-file-chooser-poc.js"' in package_json


def test_manifest_declares_debugger_permission_for_cdp_lane():
    manifest = _read("extension/manifest.json")

    assert '"debugger"' in manifest


def test_background_implements_cdp_file_chooser_interception_flow():
    background_source = _read("extension/background.js")

    for token in [
        'const CDP_DEBUGGER_PROTOCOL_VERSION = "1.3";',
        'const CDP_FILE_CHOOSER_TIMEOUT_MS = 10000;',
        'FLOWKIT_CDP_BEGIN_FILE_CHOOSER_POC',
        'FLOWKIT_CDP_WAIT_FILE_CHOOSER_POC',
        'Page.setInterceptFileChooserDialog',
        'Page.fileChooserOpened',
        'DOM.setFileInputFiles',
        'ERR_CDP_FILE_CHOOSER_TIMEOUT',
    ]:
        assert token in background_source


def test_flow_dom_bridge_exposes_cdp_file_chooser_actions():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        'beginCdpFileChooserProof',
        'waitForCdpFileChooserProofResult',
        "FLOWKIT_CDP_BEGIN_FILE_CHOOSER_POC",
        "FLOWKIT_CDP_WAIT_FILE_CHOOSER_POC",
        "ERR_RUNTIME_MESSAGE_TIMEOUT",
    ]:
        assert token in dom_source


def test_phase_2_harness_uses_playwright_click_and_bridge_wait():
    harness_script = _read("scripts/test-f2v-cdp-file-chooser-poc.js")

    for token in [
        "chromium.launchPersistentContext",
        "RUN_FIRST npm run test:phase2:first",
        'page.click("#start-slot-button")',
        '"Page.fileChooserOpened"',
        "beginCdpFileChooserProof",
        "waitForCdpFileChooserProofResult",
        "PASS CDP file chooser proof of concept",
    ]:
        assert token in harness_script
