"""Regression tests for fail-closed build-identity proof.

These lock in the fix for the defect where a stale persisted request-telemetry row
(carrying an old build id) was read as current build proof. The evaluator must look
ONLY at a live self-test snapshot and fail closed unless the active Flow tab proves
the loaded build.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.services import build_proof as bp

_BASE = Path(__file__).resolve().parents[2]
EXPECTED = bp.read_canonical_build_id(_BASE)
NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)


def _ts(delta_seconds: int = 0) -> str:
    return (NOW + timedelta(seconds=delta_seconds)).isoformat()


def _good_snapshot() -> dict:
    return {
        "connected": True,
        "agentConnected": True,
        "background_build_id": EXPECTED,
        "runner_build_id": EXPECTED,
        "content_build_id": EXPECTED,
        "build_match": True,
        "flow_tab_found": True,
        "flow_tab_id": 1234,
        "flow_tab_url": "https://labs.google/fx/tools/flow/project/abc",
        "content_script_alive_on_active_tab": True,
        "extension_id": "abcdefghijklmnopabcdefghijklmnop",
        "timestamp": _ts(-5),
    }


def test_canonical_build_id_present_and_well_formed():
    assert EXPECTED
    assert bp.BUILD_ID_LITERAL_RE.fullmatch(EXPECTED)


def test_happy_path_passes():
    v = bp.evaluate_build_proof(_good_snapshot(), EXPECTED, now=NOW)
    assert v.ok and v.verdict == bp.PASS
    assert v.build_match is True
    assert v.background_build_id == EXPECTED
    assert v.content_build_id == EXPECTED
    assert v.page_url.endswith("/project/abc")
    assert v.tab_id == 1234


def test_no_self_test_blocks():
    v = bp.evaluate_build_proof(None, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_NO_SELF_TEST


def test_stale_telemetry_background_only_does_not_pass():
    # Mirrors the real defect: background id looks correct (as a stale telemetry row
    # would suggest) but there is no live tab. Must NOT pass on background alone.
    snap = _good_snapshot()
    snap["flow_tab_found"] = False
    snap["target_tab"] = None
    snap["flow_tabs"] = []
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_NO_FLOW_TAB


def test_missing_content_script_blocks():
    snap = _good_snapshot()
    snap["content_script_alive_on_active_tab"] = False
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_MISSING_CONTENT_SCRIPT


def test_content_build_missing_blocks():
    snap = _good_snapshot()
    snap.pop("content_build_id")
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_CONTENT_BUILD_MISSING


def test_background_build_mismatch_blocks():
    snap = _good_snapshot()
    snap["background_build_id"] = "flowkit-f2v-runner-audit-2026-06-15a"
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_BACKGROUND_BUILD_MISMATCH


def test_content_background_mismatch_blocks():
    # Reloaded background paired with a stale injected content script.
    snap = _good_snapshot()
    snap["content_build_id"] = "flowkit-f2v-runner-audit-2026-06-15a"
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_BUILD_MISMATCH


def test_build_match_flag_false_blocks():
    snap = _good_snapshot()
    snap["build_match"] = False
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_BUILD_MATCH_NOT_PROVEN


def test_stale_handshake_blocks():
    snap = _good_snapshot()
    snap["timestamp"] = _ts(-3600)  # one hour old
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW, freshness_seconds=120)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_STALE_HANDSHAKE


def test_future_skew_handshake_blocks():
    snap = _good_snapshot()
    snap["timestamp"] = _ts(3600)  # one hour in the future
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW, freshness_seconds=120)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_STALE_HANDSHAKE


def test_offline_extension_blocks():
    snap = _good_snapshot()
    snap["connected"] = False
    snap["agentConnected"] = False
    v = bp.evaluate_build_proof(snap, EXPECTED, now=NOW)
    assert v.verdict == bp.BLOCK and v.reason == bp.REASON_EXTENSION_OFFLINE
