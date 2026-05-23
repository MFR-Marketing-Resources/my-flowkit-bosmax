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
        'simulateCdpFileUpload',
        'simulateLegacyDomFileUpload',
        'CDP_LOCAL_FILE_PATH_REQUIRED',
        "uploadStrategy: 'cdp_file_chooser'",
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


def test_dashboard_upload_lane_preserves_local_file_path_for_cdp_runtime():
    assets_api = _read("dashboard/src/api/assets.ts")
    client_api = _read("dashboard/src/api/client.ts")
    f2v_module = _read("dashboard/src/components/workspace/F2VModule.tsx")
    i2v_module = _read("dashboard/src/components/workspace/I2VModule.tsx")
    img_module = _read("dashboard/src/components/workspace/IMGModule.tsx")
    shared_types = _read("dashboard/src/types/index.ts")

    for token in [
        "local_file_path",
        "localFilePath",
    ]:
        assert token in "\n".join(
            [assets_api, client_api, f2v_module, i2v_module, img_module, shared_types]
        )


def test_flow_upload_endpoint_persists_local_staging_path_for_phase_3():
    flow_api = _read("agent/api/flow.py")

    for token in [
        'tempfile.gettempdir()',
        '"flowkit-upload-staging"',
        '"local_file_path": str(temp_file_path)',
    ]:
        assert token in flow_api
