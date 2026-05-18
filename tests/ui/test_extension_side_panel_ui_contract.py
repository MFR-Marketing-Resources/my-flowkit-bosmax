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

	for token in [
		'data-testid="flowkit-side-panel-root"',
		'data-testid="flowkit-side-panel-ready"',
		'data-testid="flowkit-side-panel-error"',
		'id="btn-retry-runtime"',
		'id="runtime-agent-health"',
		'id="runtime-extension-state"',
		'id="runtime-serving-mode"',
		'id="runtime-offline-reason"',
	]:
		assert token in html

	for token in [
		"/api/local-agent/status",
		"/health",
		"Local agent offline",
		"Extension background disconnected",
		"Dashboard build required",
	]:
		assert token in js
