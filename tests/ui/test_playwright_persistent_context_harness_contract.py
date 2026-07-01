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
        '"exclude_matches": [',
        '"http://127.0.0.1:8100/*"',
        '"http://localhost:8100/*"',
    ]:
        assert token in manifest


def test_flow_dom_exposes_playwright_test_bridge_only_for_harness_marker():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "const FLOW_KIT_PLAYWRIGHT_HARNESS = hasPlaywrightHarnessMarker();",
        "const FLOW_KIT_IS_GOOGLE_FLOW = window.location.href.startsWith('https://labs.google/');",
        "const FLOW_KIT_TEST_BRIDGE_SOURCE = 'FLOWKIT_PLAYWRIGHT_TEST_BRIDGE';",
        "document.documentElement?.getAttribute('data-flowkit-harness') === 'playwright'",
        "!FLOW_KIT_TEST_MODE && !FLOW_KIT_PLAYWRIGHT_HARNESS && !FLOW_KIT_IS_GOOGLE_FLOW",
        "window.postMessage({",
        "direction: 'response'",
        "ERR_UNKNOWN_TEST_ACTION:",
    ]:
        assert token in dom_source


def test_open_flow_new_project_waits_for_root_landing_before_selector_fail():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "if (initialState.isRoot && !initialState.landingDetected) {",
        "await waitForCondition(() => {",
        "const state = collectProjectCreationState();",
        "if (state.landingDetected || state.newProjectControlFound) return true;",
        "return observed.visibleUploadSlots.includes('Start') || observed.composerPresent;",
    ]:
        assert token in dom_source


def test_frames_project_creation_hands_navigation_waitoff_to_background():
    dom_source = _read("extension/content-flow-dom.js")
    background_source = _read("extension/background.js")

    for token in [
        "awaiting_navigation: true,",
        "setTimeout(() => {",
        "background must wait for editor navigation",
        "if (msg.type === 'ENSURE_VIDEO_FRAMES_EDITOR_READY') {",
        "project_list_or_landing_detected: projectCreationState.landingDetected,",
        "new_project_control_found: projectCreationState.newProjectControlFound,",
    ]:
        assert token in dom_source

    for token in [
        "async function waitForFramesProjectEditorReady(",
        "{ type: \"ENSURE_VIDEO_FRAMES_EDITOR_READY\" }",
        "Timed out waiting for Frames editor after New project click",
        "async function waitForFlowProjectCreationSurface(",
        "await waitForFlowProjectCreationSurface(targetTab.id, mode, 20000);",
    ]:
        assert token in background_source


def test_f2v_model_gate_allows_unknown_visible_model_but_rejects_nano_banana():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "if (/nano.?banana/i.test(modelText)) {",
        "modelText: 'UNKNOWN_VISIBLE_MODEL',",
        "modelVerification: 'SOFT_UNKNOWN_PASS',",
        "if (observedModel.includes('nano banana')) {",
        "Expected F2V video model, got image model",
    ]:
        assert token in dom_source


def test_f2v_frames_contract_keeps_start_required_end_optional_and_explicit_abort_codes():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "function resolveInteractiveControlTarget(el, text = '') {",
        "const descendant = findVisibleInteractiveDescendant(el, text);",
        "const target = resolveInteractiveControlTarget(el, label);",
        "const target = resolveInteractiveControlTarget(el, text);",
        "function resolveExplicitEndFrameAssetSource(job) {",
        "if (resolveExplicitEndFrameAssetSource(job)) slots.push('End');",
        "return 'ERR_START_FRAME_REQUIRED_MISSING';",
        "return 'ERR_END_FRAME_REQUIRED_MISSING';",
        "job.mode === 'F2V' ? 'ERR_ASPECT_9_16_NOT_SELECTED' : 'FLOW_MODE_MISMATCH';",
        "job.mode === 'F2V' ? 'ERR_COUNT_1X_NOT_SELECTED' : 'FLOW_MODE_MISMATCH';",
        "throw new Error(assetVerification.error || assetVerification.reason || 'ASSET_PREVIEW_NOT_VISIBLE');",
    ]:
        assert token in dom_source


def test_f2v_editor_readiness_accepts_hidden_config_chips_without_forcing_panel_open():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "const contradictoryAspectVisible = observed.aspectRatio !== 'UNKNOWN' && observed.aspectRatio !== '9:16';",
        "const contradictoryCountVisible = observed.count !== 'UNKNOWN' && observed.count !== '1x';",
        "const contradictoryModelVisible = Boolean(",
        "const softUnknownModelPass = !readinessModel || readinessModel === 'unknown';",
        "detail: workspaceReady",
        "'F2V editor ready with hidden config chips'",
    ]:
        assert token in dom_source


def test_one_way_runtime_telemetry_avoids_callback_response_lane():
    dom_source = _read("extension/content-flow-dom.js")
    background_source = _read("extension/background.js")

    for token in [
        "function sendRuntimeMessageNoThrow(payload) {",
        "chrome.runtime.sendMessage(payload);",
    ]:
        assert token in dom_source
        assert token in background_source


def test_background_status_contract_exposes_compatibility_build_fields():
    background_source = _read("extension/background.js")
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "function buildBackgroundStatusResponse() {",
        'if (message.type === "STATUS") {',
        "sendResponse(buildBackgroundStatusResponse());",
        "return false;",
        "buildId,",
        "build_id: buildId,",
        "background_build_id: buildId,",
        "gitSha: buildId,",
        "git_sha: buildId,",
        "runtimeReady,",
        "runtime_ready: runtimeReady,",
        "build_match: true,",
    ]:
        assert token in background_source

    for token in [
        "const statusPayload = resp?.data && typeof resp.data === 'object' ? resp.data : resp;",
        "resolve(statusPayload || { ok: false, error: 'ERR_EMPTY_BACKGROUND_STATUS' });",
        "const backgroundBuildId = String(",
        "testConn?.build_id",
        "testConn?.background_build_id",
        "testConn?.gitSha",
        "testConn?.git_sha",
        "const backgroundRuntimeReady = typeof testConn?.runtimeReady === 'boolean'",
        "background_build_id=${backgroundBuildId || 'legacy-compatible'}",
    ]:
        assert token in dom_source


def test_background_reloads_stale_flow_context_before_execute_and_readiness():
    background_source = _read("extension/background.js")

    for token in [
        "function isRecoverableFlowDomBridgeError(error) {",
        "/Extension context invalidated/i.test(message)",
        "async function reloadAndReinjectFlowDomContext(flowTab, reason = \"UNKNOWN\") {",
        "recovery_action: \"RELOAD_AND_REINJECT_STALE_CONTEXT\"",
        "async function ensureFreshFlowDomContext(flowTab, reason = \"UNKNOWN\") {",
        "\"HANDLE_EXECUTE_FLOW_JOB\"",
        "\"HANDLE_CHECK_FLOW_COMPOSER_READY\"",
        "\"HANDLE_DEBUG_FLOW_DOM_EXECUTION\"",
        "error: \"ERR_CONTENT_SCRIPT_STALE_OR_INVALIDATED\"",
    ]:
        assert token in background_source


def test_ensure_f2v_workspace_waits_for_root_landing_before_new_project_scan():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "// On root / landing URL — must create or open a project first.",
        "await waitForCondition(() => {",
        "const state = collectProjectCreationState();",
        "if (state.landingDetected || state.newProjectControlFound) return true;",
        "const snapObs = observeFlowState();",
    ]:
        assert token in dom_source


def test_observe_flow_state_recovers_mode_from_visible_upload_slots():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "if (observed.topMode === 'UNKNOWN') {",
        "observed.visibleUploadSlots.includes('Start') || observed.visibleUploadSlots.includes('End')",
        "observed.topMode = 'Video';",
        "observed.subMode = 'Frames';",
        "observed.visibleUploadSlots.includes('Subject')",
        "observed.visibleUploadSlots.includes('Scene')",
        "observed.visibleUploadSlots.includes('Style')",
        "observed.subMode = 'Ingredients';",
        "observed.topMode = 'Image';",
    ]:
        assert token in dom_source


def test_open_flow_config_panel_has_view_settings_and_f2v_menu_fallback():
    dom_source = _read("extension/content-flow-dom.js")

    for token in [
        "const looksLikeSettingsLauncher = lower.includes('view settings') || lower.includes('settings_2');",
        "if (looksLikeModelChip || looksLikeConfigChip || looksLikeSettingsLauncher) {",
        "const fallback = await ensureOpenF2VConfigMenu();",
        "surfaced = fallback.ok || Boolean(findOpenFlowConfigSurface());",
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
