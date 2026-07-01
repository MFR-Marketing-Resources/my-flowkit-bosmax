from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
	return (ROOT / relative_path).read_text(encoding="utf-8")


def _section(src: str, start: str, end: str) -> str:
	_, tail = src.split(start, 1)
	head, _ = tail.split(end, 1)
	return head


def test_manifest_points_to_existing_side_panel_entrypoint():
	manifest = _read("extension/manifest.json")
	side_panel_html = ROOT / "extension" / "side_panel.html"

	assert '"default_path": "side_panel.html"' in manifest
	assert side_panel_html.exists()


def test_side_panel_shell_exposes_runtime_markers_and_retry_controls():
	html = _read("extension/side_panel.html")
	js = _read("extension/side_panel.js")
	popup_html = _read("extension/popup.html")
	popup_js = _read("extension/popup.js")

	for token in [
		'data-testid="flowkit-side-panel-root"',
		'data-testid="flowkit-side-panel-ready"',
		'data-testid="flowkit-side-panel-error"',
		'id="btn-retry-runtime"',
		'id="runtime-agent-health"',
		'id="runtime-extension-state"',
		'id="runtime-serving-mode"',
		'id="runtime-owner"',
		'id="runtime-autostart-warning"',
		'id="runtime-offline-reason"',
		'data-dashboard-route="registration"',
		'data-dashboard-route="creative"',
		'data-dashboard-route="bank"',
		"Smart Registration",
		"Creative",
		"Bank",
	]:
		assert token in html

	for token in [
		"/api/local-agent/status",
		"/health",
		"FLOWKIT_DASHBOARD_ROUTE_SYNC",
		"runtime-owner",
		"runtime-autostart-warning",
		"Local agent offline",
		"Extension background disconnected",
		"Dashboard build required",
		"Smart Registration",
		"/product-registration?portal=side",
		"Creative Library",
		"/assets/creative-library?portal=side",
		"Prompt Handoff Bank",
		"/workspace/generation-packages?portal=side",
		"AUTO_RUNTIME_RETRY_MS",
		"silentRetry",
		'window.addEventListener("focus"',
		'document.addEventListener("visibilitychange"',
	]:
		assert token in js

	for token in [
		"currentEmbeddedRoute",
		"window.addEventListener(\"message\", handleEmbeddedRouteSync)",
		"Embedded route sync received:",
	]:
		assert token in js

	for token in [
		'data-dashboard-route="registration"',
		'data-dashboard-route="creative"',
		'data-dashboard-route="bank"',
		"Smart Registration",
		"Creative",
		"Bank",
	]:
		assert token in popup_html

	for token in [
		'registration: "http://127.0.0.1:8100/product-registration?portal=side"',
		'creative: "http://127.0.0.1:8100/assets/creative-library?portal=side"',
		'bank: "http://127.0.0.1:8100/workspace/generation-packages?portal=side"',
	]:
		assert token in popup_js


def test_dashboard_portal_reports_current_embedded_route_to_side_panel_parent():
	app_source = _read("dashboard/src/App.tsx")

	for token in [
		"function EmbeddedRouteReporter() {",
		'new URLSearchParams(location.search).get("portal") === "side"',
		'type: "FLOWKIT_DASHBOARD_ROUTE_SYNC"',
		"window.parent.postMessage(",
		"window.location.origin",
		"document.hidden || inFlight",
		"window.setInterval(loadSummary, 15000)",
		"<EmbeddedRouteReporter />",
	]:
		assert token in app_source

	operator_source = _read("dashboard/src/pages/OperatorPage.tsx")

	for token in [
		"request_type=MANUAL_FLOW_JOB",
		"mode=${encodeURIComponent(mode)}",
		"document.hidden || inFlight",
		"window.setInterval(loadModeRequests, 15000)",
	]:
		assert token in operator_source


def test_flow_dom_f2v_lane_stays_fail_closed_and_locked_to_lite():
	dom_source = _read("extension/content-flow-dom.js")

	assert "return surfaced || true;" not in dom_source
	assert "return surfaced;" in dom_source
	assert "expectations.modelLabel =" in dom_source
	assert "resolveRequestedModel(job) || FLOW_MODE_CONFIG.F2V.defaultModel;" in dom_source
	assert "Expected model='${expectations.modelLabel}', got '${observed.model}'" in dom_source


def test_flow_dom_f2v_config_launcher_accepts_preselection_counts_before_panel_open():
	dom_source = _read("extension/content-flow-dom.js")
	launcher_section = _section(
		dom_source,
		"function findCollapsedF2VConfigLauncher() {",
		"async function ensureF2VComposerReadyBeforeConfig() {",
	)
	generic_launcher_section = _section(
		dom_source,
		"function findFlowConfigLauncher() {",
		"function findOpenFlowConfigSurface() {",
	)

	assert "function hasFlowCountToken(text)" in dom_source
	assert "function hasFlowAspectToken(text)" in dom_source
	assert "hasFlowCountToken(text)" in launcher_section
	assert "hasFlowAspectToken(text)" in launcher_section
	assert "text.includes('1x')" not in launcher_section
	# Contract note: the strict `count && aspect` rule stays frozen in the
	# F2V-specific findCollapsedF2VConfigLauncher (asserted above via launcher_section).
	# The generic findFlowConfigLauncher was intentionally broadened by the slot-based
	# flow mode inference recovery (commit 1c7bd51 / ae37733) to detect slot pills such
	# as "Video 1x" via looksLikeBottomComposerConfigPillText(), which itself resolves
	# canonical count/aspect tokens through normalizeFlowConfigPillText — so the
	# no-hardcoded-token guarantee is preserved without pinning the old boolean.
	assert "looksLikeBottomComposerConfigPillText(text)" in generic_launcher_section
	assert "collectComposerContextRoots(composer)" in generic_launcher_section


def test_flow_dom_authenticated_editor_prefers_composer_scoped_selectors_before_global_fallbacks():
	dom_source = _read("extension/content-flow-dom.js")
	generate_section = _section(
		dom_source,
		"function findGenerateButtonNearComposer() {",
		"function findComposerElement() {",
	)
	mode_section = _section(
		dom_source,
		"async function ensureModeControlsVisible(mode) {",
		"function resolveRequestedCount(job) {",
	)

	assert "function collectComposerContextRoots(composer = null, maxDepth = 4) {" in dom_source
	assert "function looksLikeGenerateButton(target) {" in dom_source
	assert "function looksLikeExcludedCreateButton(target) {" in dom_source
	assert "function isNearComposerDock(target, composer) {" in dom_source
	assert "collectComposerContextRoots(composer)" in generate_section
	assert "looksLikeExcludedCreateButton(btn)" in generate_section
	assert "isNearComposerDock(btn, composer)" in generate_section
	assert "await openFlowConfigPanel()" in mode_section
	assert "assignVisibleControls(surface, 'config_surface')" in mode_section
	assert "let source = 'global';" in mode_section


def test_gfv2_settings_opener_reuses_composer_pill_and_generic_config_fallbacks():
	dom_source = _read("extension/content-flow-dom.js")
	launcher_section = _section(
		dom_source,
		"function _gfv2FindSettingsLauncher() {",
		"function _gfv2ClickEl(el) {",
	)
	apply_section = _section(
		dom_source,
		"async function gfv2ApplySettings(options) {",
		"if (msg.type === 'GFV2_DISCOVER_SETTINGS') {",
	)

	assert "collectComposerContextRoots(composer)" in launcher_section
	assert "looksLikeBottomComposerConfigPillText(targetText)" in launcher_section
	assert "findFlowConfigLauncher()" in launcher_section
	assert "await openFlowConfigPanel()" in apply_section
	assert "fallback_open_flow_config_panel" in apply_section
	assert "fallback_open_flow_config_panel_after_launcher_scan" in apply_section
	assert "const persistedComposer = _gfv2ReadComposerPersistence()" in apply_section
	assert "save_closed_settings_panel" in apply_section


def test_background_flow_blocker_classifier_prefers_mode_mismatch_over_auth_failure():
	background_source = _read("extension/background.js")
	classifier_section = _section(
		background_source,
		"function classifyFlowPrimaryBlocker(result) {",
		"function finalizeFlowReadiness(result) {",
	)

	assert 'rawError.includes("FLOW_MODE_MISMATCH")' in classifier_section
	assert 'rawError.includes("ABORT_FLOW_MODE_MISMATCH")' in classifier_section
	assert classifier_section.index("FLOW_MODE_MISMATCH") < classifier_section.index("FLOW_EDITOR_NOT_AUTHENTICATED")


def test_flow_dom_and_background_publish_runtime_build_handshake_markers():
	dom_source = _read("extension/content-flow-dom.js")
	background_source = _read("extension/background.js")
	diagnostic_section = _section(
		dom_source,
		"function buildDiagnosticPingResponse() {",
		"function normalizeText(value) {",
	)
	telemetry_section = _section(
		background_source,
		"function buildStageTelemetryPayload(message = {}, contentHealth = null) {",
		"function postStageTelemetry(message = {}, contentHealth = null) {",
	)

	assert "const FLOW_KIT_DOM_BUILD_ID =" in dom_source
	assert "runtime_ready: true" in diagnostic_section
	assert "content_build_id: FLOW_KIT_DOM_BUILD_ID" in diagnostic_section
	assert "git_sha: FLOW_KIT_DOM_BUILD_ID" in diagnostic_section
	assert "background_build_id: BUILD_ID" in telemetry_section
	assert "content_build_id:" in telemetry_section
	assert "checkpoint: message.checkpoint || message.stage" in telemetry_section
	assert "build_match:" in telemetry_section
	# Telemetry beacons are STRICTLY one-way (frozen harness gate: "One-way runtime
	# telemetry omits callback lane") — no callback, no response port.
	assert "chrome.runtime.sendMessage(payload, () => {" not in dom_source
	assert "chrome.runtime.sendMessage(payload, () => {" not in background_source
	assert "chrome.runtime.sendMessage(payload);" in dom_source
	assert "chrome.runtime.sendMessage(payload);" in background_source


def test_background_flow_blocker_classifier_fail_closes_on_runtime_or_build_mismatch():
	background_source = _read("extension/background.js")
	classifier_section = _section(
		background_source,
		"function classifyFlowPrimaryBlocker(result) {",
		"function finalizeFlowReadiness(result) {",
	)

	assert "!result?.runtime_ready || !result?.build_match" in classifier_section


def test_background_gfv2_lane_forces_v2_settings_path_and_captures_option_failure_context():
	background_source = _read("extension/background.js")
	gfv2_section = _section(
		background_source,
		"async function handleGfv2Job(job) {",
		"async function handleExecuteFlowJob(job) {",
	)

	assert "gfv2ForceDomSettings: true" in gfv2_section
	assert "gfv2SkipModeSteps: true" in gfv2_section
	assert 'code === "ERR_F2V_OPTION_VIDEO_NOT_FOUND"' in gfv2_section
	assert 'detail.gfv2_readiness = await captureGoogleFlowV2Readiness(flowTab);' in gfv2_section
	assert "runnerApi._submitPromptAndWaitForNegotiationSurface(" in gfv2_section
	assert '"GFV2_PROMPT_SUBMITTED"' in gfv2_section
	assert '"GFV2_QA_SURFACE_READY"' in gfv2_section
	assert '"gfv2_qna_ready_stopped_before_generate"' in gfv2_section


def test_f2v_runner_defers_gfv2_settings_until_after_upload():
	runner_source = _read("extension/f2v-flow-queue-runner.js")
	runner_section = _section(
		runner_source,
		"if (opts?.gfv2ForceDomSettings === true) {",
		"} else if (_shouldTrustWorkspacePackageSettings(job) && opts?.gfv2ForceDomSettings !== true) {",
	)

	assert "authority: 'gfv2_post_upload_verify'" in runner_section
	assert "stageResults.settings_configured = true;" in runner_section
	assert "source=gfv2_post_upload_verify" in runner_section


def test_f2v_runner_exposes_post_submit_negotiation_detector_for_gfv2_boundary_stop():
	runner_source = _read("extension/f2v-flow-queue-runner.js")

	assert "async function MAIN_waitForPromptNegotiationSurface(expectedPromptText, timeoutMs, pollMs) {" in runner_source
	assert "async function _submitPromptAndWaitForNegotiationSurface(scripting, tabId, promptText, opts = {}) {" in runner_source
	assert "ERR_F2V_AGENT_NEGOTIATION_NOT_READY" in runner_source
	assert "ERR_F2V_PROMPT_MISMATCH_BEFORE_SUBMIT" in runner_source
	assert "ERR_F2V_WRONG_QA_ROUTE" in runner_source
	assert "'double check it'" in runner_source
	assert "'edit a video with omni'" in runner_source
	assert "\"i'll upload a video\"" in runner_source
	assert "MAIN_verifyExpectedComposerPrompt," in runner_source
	assert "MAIN_waitForPromptNegotiationSurface," in runner_source
	assert "_submitPromptAndWaitForNegotiationSurface," in runner_source


def test_f2v_runner_start_slot_fallback_prefers_composer_near_interactive_targets():
	runner_source = _read("extension/f2v-flow-queue-runner.js")
	slot_section = _section(
		runner_source,
		"function MAIN_findUploadSlotByLabel(slotLabel, stampAttr) {",
		"/**\n * MAIN-world: find an upload entry-point by aria-label or icon symbol.",
	)

	assert "function findComposer()" in slot_section
	assert "function distanceToComposer(el)" in slot_section
	assert "label_closest_interactive" in slot_section
	assert "container_interactive" in slot_section
	assert "distance_to_composer" in slot_section
	assert "text.indexOf('drop media') >= 0" not in slot_section
	assert "/\\bingredients\\b|\\bimage\\b|\\bscene\\b|\\bsubject\\b|\\bstyle\\b/" in slot_section
	assert "interactiveStartSources" in slot_section
	assert "needle === 'start' && !interactiveStartSources[targets[t].source]" in slot_section


def test_f2v_runner_gfv2_start_launcher_fails_closed_before_generic_composer_fallback():
	runner_source = _read("extension/f2v-flow-queue-runner.js")
	start_section = _section(
		runner_source,
		"async function _clickStartEntryPoint(scripting, tabId, opts) {",
		"async function _clickStart(scripting, tabId, opts) {",
	)

	assert "if (opts?.gfv2ForceDomSettings === true) {" in start_section
	assert "return startSlot;" in start_section
	assert "asset_picker_launcher_fallback" in start_section


def test_f2v_runner_start_surface_guard_aborts_when_f2v_drifted_to_ingredients():
	runner_source = _read("extension/f2v-flow-queue-runner.js")
	start_guard_section = _section(
		runner_source,
		"function MAIN_assertF2VStartSurface() {",
		"/**\n * MAIN-world: find an upload entry-point by aria-label or icon symbol.",
	)
	execute_section = _section(
		runner_source,
		"const startResult = _useCdpUpload",
		"    stageResults.start_clicked = true;",
	)

	# Hardened: the guard must fail closed on ANY non-Frames sub-surface (the old
	# "subMode !== 'Ingredients'" let the UNKNOWN/None drift into the ghost
	# negotiation Q&A surface pass through to upload -> prompt injection).
	assert "!== 'Frames'" in start_guard_section
	assert "!subModeDrift" in start_guard_section
	assert "sub_mode_drift" in start_guard_section
	assert "state.subMode !== 'Ingredients'" not in start_guard_section
	assert "foreign_slot_drift" in start_guard_section
	assert "ERR.SURFACE_DRIFT_AFTER_START" in execute_section
	assert "MAIN_assertF2VStartSurface" in runner_source
	# The guard is re-sampled across a settle window, not a single snapshot, so a
	# delayed post-Start SPA re-render that drifts the surface is still caught.
	assert "startSurfaceSamples" in execute_section
	assert "startSurfaceSampleGapMs" in execute_section


def test_f2v_runner_submit_guard_requires_expected_bosmax_prompt_in_visible_composer():
	runner_source = _read("extension/f2v-flow-queue-runner.js")
	submit_section = _section(
		runner_source,
		"async function _submitPromptAndWaitForNegotiationSurface(scripting, tabId, promptText, opts = {}) {",
		"// ───────────────────────────────────────────────────────────────────────",
	)
	generate_button_section = _section(
		runner_source,
		"function MAIN_stampGenerateButton(stampAttr) {",
		"/**\n * MAIN-world: locate the visible composer-side asset-picker launcher.",
	)

	assert "MAIN_verifyExpectedComposerPrompt" in runner_source
	assert "error: ERR.PROMPT_MISMATCH_BEFORE_SUBMIT" in submit_section
	assert "distanceToComposer" in generate_button_section
	assert "isNearComposerDock" in generate_button_section
	assert "distanceToComposer(best.btn, composer) > 520" in generate_button_section


def test_flow_dom_f2v_readiness_prefers_slot_surface_and_bottom_composer_state_over_legacy_mode_text():
	dom_source = _read("extension/content-flow-dom.js")
	readiness_section = _section(
		dom_source,
		"    const readiness = checkFlowComposerReady();",
		"  async function waitForNewProjectEditor(mode = 'F2V', timeoutMs = 45000) {",
	)
	open_project_section = _section(
		dom_source,
		"    if (msg.type === 'OPEN_FLOW_NEW_PROJECT') {",
		"    if (msg.type === 'EXECUTE_FLOW_JOB') {",
	)

	assert "function hasF2VEditorSurfaceSignals(readinessObserved = null) {" in dom_source
	assert "const f2vSurface = hasF2VEditorSurfaceSignals(readinessObserved);" in readiness_section
	assert "configPill.bottom_composer_config_pill_visible" in dom_source
	assert "hasF2VEditorSurfaceSignals(ready.observed).ready" in open_project_section


def test_flow_dom_new_project_root_lane_uses_pointer_sequence_clicks():
	dom_source = _read("extension/content-flow-dom.js")
	root_open_section = _section(
		dom_source,
		"  async function openFlowNewProjectFlow(mode = 'F2V') {",
		"  function runExecuteFlowJobSmoke(job) {",
	)
	message_handler_section = _section(
		dom_source,
		"    if (msg.type === 'OPEN_FLOW_NEW_PROJECT') {",
		"    if (msg.type === 'EXECUTE_FLOW_JOB') {",
	)
	workspace_recovery_section = _section(
		dom_source,
		"      const newProjectBtn = findNewProjectControl();",
		"      if (!appeared) {",
	)

	assert "_gfv2ClickEl(createControl);" in root_open_section
	assert "_gfv2ClickEl(createControl);" in message_handler_section
	assert "_gfv2ClickEl(newProjectBtn);" in workspace_recovery_section
	assert "_gfv2ClickEl(goBackBtn);" in workspace_recovery_section


def test_background_f2v_editor_detection_uses_surface_signals_not_only_legacy_mode_string():
	background_source = _read("extension/background.js")
	probe_section = _section(
		background_source,
		"function isActualFlowEditorProbe(result, mode = null) {",
		"async function resolveExistingProjectEditorAuthority(tab, mode) {",
	)
	preselection_section = _section(
		background_source,
		"function isPreselectionEditorReadyDiagnostic(diagnostic) {",
		"// Read-only Google Flow V2 readiness capture.",
	)

	assert "function looksLikeF2VEditorSurfaceFromDiagnostic(diagnostic) {" in background_source
	assert 'visibleUploadSlots.includes("Start")' in probe_section
	assert "hasBottomComposerState" in probe_section
	assert "looksLikeF2VEditorSurfaceFromDiagnostic(diagnostic)" in background_source
	assert "diagnostic.bottom_composer_config_pill_visible" in preselection_section
	assert "diagnostic.project_list_or_landing_detected === true" in preselection_section
	assert "diagnostic.new_project_control_found === true" in preselection_section
	assert "diagnostic.editor_capability_ready === true" in preselection_section
	assert "diagnostic.prompt_field_found && diagnostic.generate_button_found" in preselection_section


def test_background_existing_editor_authority_revalidates_f2v_surface_before_reuse():
	background_source = _read("extension/background.js")
	authority_section = _section(
		background_source,
		"async function resolveExistingProjectEditorAuthority(tab, mode) {",
		"function classifyFlowTabKind(tab) {",
	)

	assert 'type: "CHECK_FLOW_COMPOSER_READY"' in authority_section
	assert "if (!isActualFlowEditorProbe(readiness, mode)) {" in authority_section
	assert 'error: "FLOW_EDITOR_AUTHORITY_SURFACE_UNHEALTHY"' in authority_section
	assert "readiness," in authority_section


def test_background_open_new_project_fail_closes_when_flow_stays_on_root_shell():
	background_source = _read("extension/background.js")
	open_section = _section(
		background_source,
		"async function handleOpenFlowNewProject(mode) {",
		"async function waitForFlowProjectCreationSurface(",
	)

	assert "const settledOnEditor = isProjectEditorUrl(effectiveFlowUrl);" in open_section
	assert "const editorReady = Boolean(result?.editor_ready) && settledOnEditor;" in open_section
	assert 'result?.ok && !editorReady ? "FLOW_PROJECT_EDITOR_NOT_OPEN" : null' in open_section
	assert "ok: Boolean(result?.ok && editorReady)," in open_section


def test_background_gfv2_surface_classifier_rejects_root_shell_without_project_url():
	# manual_5353152e: gfv2EnsureSurface granted existing_healthy authority to the
	# Flow root/home tab (url=https://labs.google/fx/tools/flow) because the root
	# composer passes the editor proof; the F2V runner then failed the Start click
	# with ERR_F2V_START_BUTTON_NOT_FOUND. The classifier must reject any surface
	# whose URL is not a /project/ editor so root tabs route through New/Create.
	background_source = _read("extension/background.js")
	classify_section = _section(
		background_source,
		"function gfv2ClassifySurface(tab, capture) {",
		"async function gfv2EnsureSurface(mode, emit) {",
	)

	assert 'if (!url.includes("/project/")) {' in classify_section
	assert 'reason: "root_shell_no_project"' in classify_section
	# The root-shell rejection must gate the healthy verdict, i.e. run before the
	# final editorOk return, so a passing editor proof cannot override it.
	assert classify_section.index('reason: "root_shell_no_project"') < classify_section.index(
		'reason: editorOk ? "ok" : "no_editor_surface"'
	)


def test_flow_dom_new_project_control_scan_is_deadline_bounded_and_single_pass():
	# manual_efad2bb1 / manual_stkdiag1: findNewProjectControl ran up to 21
	# forced-reflow full-document scans per OPEN_FLOW_NEW_PROJECT message and
	# blocked the tab main thread past the 70s message timeout (and once threw
	# "Maximum call stack size exceeded"). The scan must match text BEFORE any
	# visibility/reflow work and must stop at a hard deadline so a pathological
	# DOM fails closed instead of hanging the tab.
	dom_source = _read("extension/content-flow-dom.js")
	control_section = _section(
		dom_source,
		"function findNewProjectControl() {",
		"function collectProjectCreationState() {",
	)

	assert "const deadline = Date.now() + " in control_section
	assert "if (Date.now() > deadline) break;" in control_section
	# Cheap text matching must run before the reflow-forcing visibility check.
	assert control_section.index("const label = normalizeText(") < control_section.index(
		"if (!isVisible(item.el)) continue;"
	)
	# No per-candidate findElementByText full-document rescans.
	assert "findElementByText(" not in control_section

	state_section = _section(
		dom_source,
		"function collectProjectCreationState() {",
		"async function ensureVideoFramesEditorReady() {",
	)
	# The control is resolved once and reused for both landing flags.
	assert state_section.count("findNewProjectControl()") == 1

	# Stack evidence must survive the message boundary so the next overflow (if
	# any) lands in telemetry instead of vanishing into a bare error string.
	assert "error_stack: String(err?.stack || '').slice(0, 1500)," in dom_source
	background_source = _read("extension/background.js")
	assert "createResult?.error_stack" in background_source


def test_flow_dom_message_listener_reinjection_guard_keeps_single_listener():
	# ensureFlowDomScript() re-injects content-flow-dom.js on stale-script
	# retries within the same extension instance. Without deregistering the
	# previous copy's listener, every OPEN_FLOW_NEW_PROJECT message runs N scan
	# storms serially on the tab main thread (manual_efad2bb1 hang/overflow
	# amplification). The last injection must win: remove the prior listener
	# before registering the new one.
	dom_source = _read("extension/content-flow-dom.js")

	assert "if (window._flowKitDomListener) {" in dom_source
	assert (
		"chrome.runtime.onMessage.removeListener(window._flowKitDomListener);"
		in dom_source
	)
	assert "window._flowKitDomListener = flowDomMessageListener;" in dom_source
	# Deregistration must happen BEFORE the new listener is registered.
	assert dom_source.index(
		"chrome.runtime.onMessage.removeListener(window._flowKitDomListener);"
	) < dom_source.index("chrome.runtime.onMessage.addListener(flowDomMessageListener);")


def test_flow_dom_page_state_diagnostic_never_calls_project_creation_state():
	# True root cause of "Maximum call stack size exceeded" (manual_efad2bb1
	# create error; manual_8fa93d98 renderer frozen after GFV2_FLOW_ROOT_OPENED):
	# collectFlowPageStateDiagnostic() called collectProjectCreationState(),
	# which itself calls collectFlowPageStateDiagnostic() — unconditional mutual
	# recursion, each cycle running full-DOM scans until the stack blew. The
	# diagnostic must compute landing/root detection inline and must NEVER call
	# collectProjectCreationState().
	dom_source = _read("extension/content-flow-dom.js")
	diagnostic_section = _section(
		dom_source,
		"function collectFlowPageStateDiagnostic(mode) {",
		"// Google Flow UI Contract V2",
	)

	assert "collectProjectCreationState(" not in diagnostic_section
	# The inline replacements must still feed the three landing/root fields.
	assert "is_root_flow_url: isRootFlowUrl(window.location.href)," in diagnostic_section
	assert "new_project_control_found: !!newProjectControlInline," in diagnostic_section
	# The reverse direction (creation state -> diagnostic) stays, so the pair
	# must remain acyclic: exactly one direction may exist.
	creation_section = _section(
		dom_source,
		"function collectProjectCreationState() {",
		"async function ensureVideoFramesEditorReady() {",
	)
	assert "collectFlowPageStateDiagnostic(" in creation_section
