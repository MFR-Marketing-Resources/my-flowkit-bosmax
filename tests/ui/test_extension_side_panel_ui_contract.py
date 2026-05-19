from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
	return (ROOT / relative_path).read_text(encoding="utf-8")


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
		'id="runtime-offline-reason"',
		'data-dashboard-route="creative"',
		'data-dashboard-route="bank"',
		"Creative",
		"Bank",
	]:
		assert token in html

	for token in [
		"/api/local-agent/status",
		"/health",
		"Local agent offline",
		"Extension background disconnected",
		"Dashboard build required",
		"Creative Library",
		"/assets/creative-library?portal=side",
		"Prompt Handoff Bank",
		"/workspace/generation-packages?portal=side",
	]:
		assert token in js

	for token in [
		'data-dashboard-route="creative"',
		'data-dashboard-route="bank"',
		"Creative",
		"Bank",
	]:
		assert token in popup_html

	for token in [
		'creative: "http://127.0.0.1:8100/assets/creative-library?portal=side"',
		'bank: "http://127.0.0.1:8100/workspace/generation-packages?portal=side"',
	]:
		assert token in popup_js
