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


def _expect_422_mve(body, needle=None):
    try:
        _run(flow.make_video_existing(body))
        assert False, "expected HTTPException 422"
    except HTTPException as e:
        assert e.status_code == 422, f"got {e.status_code}: {e.detail}"
        if needle:
            assert needle.lower() in str(e.detail).lower(), e.detail


def test_make_video_existing_duration_without_model_422():
    # Legacy lane must fail-closed the same way /generate does (patch I5).
    _expect_422_mve(flow.MakeVideoExistingRequest(
        project_id="p", image_media_id="m", prompt="x", duration_s=10), "10s")


def test_make_video_existing_unknown_model_422():
    _expect_422_mve(flow.MakeVideoExistingRequest(
        project_id="p", image_media_id="m", prompt="x", model="Nano Banana 2"),
        "unknown video model")


def _expect_422_nego(body, needle=None):
    try:
        _run(flow.negotiate_job(body))
        assert False, "expected HTTPException 422"
    except HTTPException as e:
        assert e.status_code == 422, f"got {e.status_code}: {e.detail}"
        if needle:
            assert needle.lower() in str(e.detail).lower(), e.detail


def test_negotiate_job_quality_4s_returns_422():
    # /negotiate-job must fail-closed before spawning a job + junk project (patch I4a).
    _expect_422_nego(flow.NegotiateJobRequest(
        prompt="x", model="Veo 3.1 - Quality", duration_s=4))


def test_generate_resolves_refs_payload_contract(monkeypatch):
    calls = {"start_generate": None, "uploaded": [], "materialized": []}

    class _C:
        connected = True
        async def get_media(self, media_id):
            return {"status": 200, "data": {"name": media_id}}
        async def upload_image(self, b64, mime_type="image/png", project_id="", file_name=""):
            calls["uploaded"].append(file_name)
            return {"_mediaId": "fresh-upload-1", "data": {}}

    async def fake_materialize(url, file_name):
        calls["materialized"].append(url)
        import pathlib, tempfile
        p = pathlib.Path(tempfile.gettempdir()) / "bosmax_test_api_ref.png"
        p.write_bytes(b"\x89PNG_fake")
        return {"local_file_path": str(p), "file_name": file_name, "mime_type": "image/png"}

    async def fake_start_generate(mode, prompt, project_id=None, image_media_ids=None, **kw):
        calls["start_generate"] = {"mode": mode, "image_media_ids": image_media_ids}
        return {"job_id": "g_api_test", "status": "SUBMITTED", "mode": mode}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    monkeypatch.setattr(flow, "_materialize_remote_url_to_staging", fake_materialize)
    from agent.services import make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    # Let's test calling generate directly.
    body = flow.GenerateRequest(
        mode="IMG",
        prompt="A photo of robot",
        refs={
            "subjectAsset": {
                "mediaId": "00000000-0000-0000-0000-000000000123"
            },
            "imageAsset": {
                "mediaId": None,
                "localFilePath": None,
                "downloadUrl": "https://s.500fd.com/tt_product/prod1.webp"
            }
        }
    )
    result = _run(flow.generate(body))
    assert result["status"] == "SUBMITTED"
    assert calls["materialized"] == ["https://s.500fd.com/tt_product/prod1.webp"]
    assert "00000000-0000-0000-0000-000000000123" in calls["start_generate"]["image_media_ids"]
    assert "fresh-upload-1" in calls["start_generate"]["image_media_ids"]


def test_negotiate_job_unknown_model_returns_422():
    _expect_422_nego(flow.NegotiateJobRequest(prompt="x", model="Nano Banana 2"),
                     "unknown video model")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
