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
	assert "hasFlowCountToken(text) && hasFlowAspectToken(text)" in generic_launcher_section
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


def test_background_flow_blocker_classifier_fail_closes_on_runtime_or_build_mismatch():
	background_source = _read("extension/background.js")
	classifier_section = _section(
		background_source,
		"function classifyFlowPrimaryBlocker(result) {",
		"function finalizeFlowReadiness(result) {",
	)

	assert "!result?.runtime_ready || !result?.build_match" in classifier_section
