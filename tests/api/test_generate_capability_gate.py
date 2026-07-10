"""API gate: /generate operator-surface capability validation (SINGLE).

The capability gate is engine-gated — it only runs when the caller declares an
`engine` with SINGLE `generation_mode` (the Step-1 operator surface always does).
Bare programmatic callers (no engine) keep the registry-only lane, so existing
behavior is preserved. Validation runs BEFORE the extension-connectivity check,
so no live extension is needed.
"""
import asyncio

from fastapi import HTTPException

from agent.api import flow
from agent.services import video_capability_matrix as cm


def _run(coro):
    return asyncio.run(coro)


def _expect_422(body, needle=None):
    try:
        _run(flow.generate(body))
        assert False, "expected HTTPException 422"
    except HTTPException as e:
        assert e.status_code == 422, f"got {e.status_code}: {e.detail}"
        if needle:
            assert needle.lower() in str(e.detail).lower(), e.detail


def _gen(**kw):
    base = dict(mode="T2V", prompt="x", engine="GOOGLE_FLOW", generation_mode="SINGLE")
    base.update(kw)
    return flow.GenerateRequest(**base)


def test_google_flow_single_6s_rejected():
    _expect_422(_gen(model="Omni Flash", duration_s=6), cm.ERR_UNSUPPORTED_ENGINE_DURATION)


def test_google_flow_single_12s_rejected():
    _expect_422(_gen(model="Omni Flash", duration_s=12), cm.ERR_UNSUPPORTED_ENGINE_DURATION)


def test_google_flow_10s_on_veo_rejected():
    # 10s is in policy but Veo Lite has no 10s → model/duration mismatch.
    _expect_422(_gen(model="Veo 3.1 - Lite", duration_s=10), cm.ERR_UNSUPPORTED_MODEL_DURATION)


def test_grok_engine_rejected_runtime_not_integrated():
    _expect_422(_gen(engine="GROK", model="Omni Flash", duration_s=6),
                cm.ERR_ENGINE_RUNTIME_NOT_INTEGRATED)


def test_capability_version_mismatch_rejected():
    _expect_422(_gen(model="Veo 3.1 - Lite", duration_s=8,
                     capability_matrix_version="video-capability-vOLD"),
                cm.ERR_CAPABILITY_MATRIX_VERSION_MISMATCH)


def test_bare_programmatic_caller_keeps_registry_lane():
    # No engine declared → capability gate is skipped; the registry lane still
    # allows 6s on Omni (a real captured capability) up to the connectivity check.
    body = flow.GenerateRequest(mode="T2V", prompt="x", model="Omni Flash", duration_s=6)
    try:
        _run(flow.generate(body))
        assert False, "expected to reach connectivity check"
    except HTTPException as e:
        # 503 (extension not connected) proves it passed validation, not 422.
        assert e.status_code == 503, f"got {e.status_code}: {e.detail}"


def test_valid_single_tuple_passes_gate_to_connectivity():
    # GOOGLE_FLOW + Omni + 10s is valid → passes the gate, then 503 at connectivity.
    try:
        _run(flow.generate(_gen(model="Omni Flash", duration_s=10)))
        assert False, "expected connectivity 503"
    except HTTPException as e:
        assert e.status_code == 503, f"got {e.status_code}: {e.detail}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
