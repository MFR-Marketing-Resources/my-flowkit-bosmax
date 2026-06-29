"""API-level regression tests for /generate model+duration validation (patch I2a).

Calls the route functions directly (no TestClient dependency). The 422 validation runs
BEFORE the extension-connectivity check, so these need no live extension.
"""
import asyncio

from fastapi import HTTPException

from agent.api import flow


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


def test_duration_without_model_returns_422():
    # 10s on the default Lite (no model) must 422 here, not blow up late in the job.
    _expect_422(flow.GenerateRequest(mode="I2V", prompt="x", duration_s=10), "10s")


def test_unknown_model_returns_422():
    _expect_422(flow.GenerateRequest(mode="T2V", prompt="x", model="Nano Banana 2"),
                "unknown video model")


def test_quality_4s_returns_422():
    _expect_422(flow.GenerateRequest(mode="T2V", prompt="x",
                                     model="Veo 3.1 - Quality", duration_s=4))


def test_empty_prompt_returns_422():
    _expect_422(flow.GenerateRequest(mode="T2V", prompt="   "))


def test_video_models_shape():
    res = _run(flow.video_models_list())
    assert res["default"] == "veo_3_1_lite"
    assert len(res["models"]) == 4
    omni = [m for m in res["models"] if m["key"] == "omni_flash"][0]
    assert omni["default_cost"] == 30 and omni["default_duration_s"] == 10


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
