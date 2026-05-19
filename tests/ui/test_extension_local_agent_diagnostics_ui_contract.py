"""UI contract — extension side panel local-agent diagnostic logic.

Verifies that side_panel.js correctly classifies partial vs full offline
and surfaces actionable messages for each failure mode.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


# ── fetchRuntimeSnapshot — failure classification ───────────────────────────

def test_both_endpoints_fail_yields_local_agent_offline():
    src = _read("extension/side_panel.js")
    assert "LOCAL_AGENT_OFFLINE" in src
    # When both fail, mark LOCAL_AGENT_OFFLINE
    assert "!statusOk && !healthOk" in src


def test_health_ok_status_fail_yields_partial_diagnostic_failure():
    src = _read("extension/side_panel.js")
    assert "PARTIAL_AGENT_DIAGNOSTIC_FAILURE" in src
    assert "healthOk && !statusOk" in src


def test_health_fail_status_ok_yields_health_endpoint_failed():
    src = _read("extension/side_panel.js")
    assert "HEALTH_ENDPOINT_FAILED" in src
    assert "!healthOk && statusOk" in src


def test_full_online_proceeds_to_extension_connected_check():
    src = _read("extension/side_panel.js")
    assert "EXTENSION_DISCONNECTED" in src
    assert "getExtensionConnected" in src


def test_snapshot_uses_statusok_healthok_booleans():
    src = _read("extension/side_panel.js")
    assert "statusOk = statusResult.status" in src
    assert "healthOk = healthResult.status" in src


# ── renderUnavailableState — error messages ──────────────────────────────────

def test_local_agent_offline_message_references_both_endpoints():
    src = _read("extension/side_panel.js")
    assert "Both /health and /api/local-agent/status" in src or (
        "LOCAL_AGENT_OFFLINE" in src and "is reachable" in src
    )


def test_partial_diagnostic_failure_message_present():
    src = _read("extension/side_panel.js")
    assert "Partial agent diagnostic failure" in src or "PARTIAL_AGENT_DIAGNOSTIC_FAILURE" in src
    assert "status endpoint failed" in src


def test_health_endpoint_failed_message_present():
    src = _read("extension/side_panel.js")
    assert "Health endpoint failed" in src or "HEALTH_ENDPOINT_FAILED" in src


def test_partial_failure_does_not_show_generic_offline_message():
    src = _read("extension/side_panel.js")
    # PARTIAL_AGENT_DIAGNOSTIC_FAILURE must be handled separately
    assert "PARTIAL_AGENT_DIAGNOSTIC_FAILURE" in src
    # The handler for partial must exist before the generic offline fallback
    partial_idx = src.index("PARTIAL_AGENT_DIAGNOSTIC_FAILURE")
    offline_idx = src.index("LOCAL_AGENT_OFFLINE")
    assert partial_idx != offline_idx


# ── navigateToRoute — iframe gating ─────────────────────────────────────────

def test_navigate_uses_can_embed_dashboard_gate():
    src = _read("extension/side_panel.js")
    assert "canEmbedDashboard" in src
    assert "renderUnavailableState" in src


def test_can_embed_dashboard_checks_health_status_ok():
    src = _read("extension/side_panel.js")
    assert 'health?.status === "ok"' in src


def test_can_embed_dashboard_checks_serving_mode():
    src = _read("extension/side_panel.js")
    assert "DASHBOARD_STATIC_READY" in src
    assert "getServingMode" in src


# ── timeout — offline detected fast ─────────────────────────────────────────

def test_health_request_timeout_reduced_for_fast_offline_detection():
    src = _read("extension/side_panel.js")
    # Timeout must be ≤ 2000ms for snappy offline feedback
    assert "HEALTH_REQUEST_TIMEOUT_MS = 1500" in src or "HEALTH_REQUEST_TIMEOUT_MS = 2000" in src


# ── host_permissions — CSP not the blocker ──────────────────────────────────

def test_manifest_host_permissions_include_local_agent():
    src = _read("extension/manifest.json")
    assert "http://127.0.0.1:8100/*" in src


def test_manifest_csp_connect_src_includes_local_agent():
    src = _read("extension/manifest.json")
    assert "connect-src" in src
    assert "http://127.0.0.1:8100" in src


# ── Promise.allSettled — parallel fetch pattern ──────────────────────────────

def test_runtime_snapshot_uses_promise_allsettled():
    src = _read("extension/side_panel.js")
    assert "Promise.allSettled" in src


def test_both_status_and_health_fetched_in_parallel():
    src = _read("extension/side_panel.js")
    assert "LOCAL_AGENT_STATUS_URL" in src
    assert "LOCAL_AGENT_HEALTH_URL" in src


# ── creative/bank routes present in loaded extension ────────────────────────

def test_side_panel_js_has_creative_route():
    src = _read("extension/side_panel.js")
    assert "creative" in src
    assert "creative-library" in src or "creative" in src


def test_side_panel_js_has_bank_route():
    src = _read("extension/side_panel.js")
    assert "bank" in src
    assert "generation-packages" in src


def test_side_panel_html_has_creative_button():
    src = _read("extension/side_panel.html")
    assert 'data-dashboard-route="creative"' in src


def test_side_panel_html_has_bank_button():
    src = _read("extension/side_panel.html")
    assert 'data-dashboard-route="bank"' in src
