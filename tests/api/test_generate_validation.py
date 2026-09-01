"""API-level regression tests for /generate model+duration validation (patch I2a).

Calls the route functions directly (no TestClient dependency). The 422 validation runs
BEFORE the extension-connectivity check, so these need no live extension.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from agent.api import flow


def _run(coro):
    return asyncio.run(coro)


_RETIRED = "LEGACY_PAID_VIDEO_ENTRYPOINT_RETIRED_USE_DURABLE_VIDEO_JOB"


@pytest.mark.parametrize(
    "call",
    [
        lambda: flow.make_video(flow.MakeVideoRequest()),
        lambda: flow.agent_negotiate(flow.AgentNegotiateRequest(dry=False)),
        lambda: flow.negotiate_job(flow.NegotiateJobRequest(prompt="x", dry=False)),
        lambda: flow.generate_video(flow.GenerateVideoRequest(
            start_image_media_id="image-1", prompt="x", project_id="project-1",
            scene_id="scene-1")),
        lambda: flow.generate_video_refs(flow.GenerateVideoRefsRequest(
            reference_media_ids=["image-1"], prompt="x", project_id="project-1",
            scene_id="scene-1")),
        lambda: flow.upscale_video(flow.UpscaleVideoRequest(
            media_id="video-1", scene_id="scene-1")),
        lambda: flow.shoot_oneshot(flow.ShootOneshotRequest(prompt="x")),
        lambda: flow.ui_driver_extend_block(flow.UiExtendBlockRequest(
            job_id="job-1", block_index=2, position=2, prompt="continue",
            dry_run=False, confirm_live_credit_burn=True)),
    ],
    ids=[
        "make-video", "agent-negotiate-live", "negotiate-job-live",
        "generate-video", "generate-video-refs", "upscale-video",
        "shoot-oneshot", "ui-extend-live",
    ],
)
def test_legacy_paid_video_routes_retire_before_contact(monkeypatch, call):
    def forbidden_client():
        pytest.fail("retired route contacted the Flow client")

    async def forbidden_product(*_args, **_kwargs):
        pytest.fail("retired route evaluated product authority")

    monkeypatch.setattr(flow, "get_flow_client", forbidden_client)
    monkeypatch.setattr(flow, "_require_flow_product", forbidden_product)

    with pytest.raises(HTTPException) as exc:
        _run(call())
    assert exc.value.status_code == 410
    assert exc.value.detail == _RETIRED


def test_ui_driver_extend_dry_preview_remains_available(monkeypatch):
    calls = {}

    class _C:
        connected = True

    async def fake_extend(_client, **kwargs):
        calls.update(kwargs)
        return {"ok": True, "dry_run": True}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import google_flow_ui_driver as ui_driver
    monkeypatch.setattr(ui_driver, "extend_block_via_ui", fake_extend)

    result = _run(flow.ui_driver_extend_block(flow.UiExtendBlockRequest(
        job_id="job-dry", block_index=2, position=2, prompt="continue",
        dry_run=True,
    )))
    assert result == {"ok": True, "dry_run": True}
    assert calls["dry_run"] is True


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


def _guided_factory_request(**overrides):
    payload = {
        "mode": "T2V",
        "prompt": "Approved final provider prompt",
        "creative_mode": "GUIDED_FACTORY",
        "status": "READY_FOR_BOT4",
        "job_phase": "FINAL_COMPILATION",
        "brief_version": "brief-v1",
        "brief_hash": "brief-sha256",
        "selected_candidate_id": "candidate-03",
        "approval_state": "APPROVED",
        "approved_by": "owner-01",
        "approved_at": "2026-09-02T10:00:00+08:00",
        "final_prompt_hash": "prompt-sha256",
        "generation_run_id": "run-001",
        "compile_gate": "PASS",
        "dispatch_gate": "PASS",
        "may_dispatch": True,
        "maximum_provider_operations": 1,
    }
    payload.update(overrides)
    return flow.GenerateRequest(**payload)


def test_guided_factory_rejects_candidate_planning_before_provider_contact(monkeypatch):
    monkeypatch.setattr(
        flow,
        "get_flow_client",
        lambda: pytest.fail("candidate-planning output contacted provider transport"),
    )

    with pytest.raises(HTTPException) as exc:
        _run(flow.generate(_guided_factory_request(job_phase="CANDIDATE_PLANNING")))

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "GUIDED_FACTORY_DISPATCH_BLOCKED"
    assert exc.value.detail["blockers"] == ["JOB_PHASE_MUST_BE_FINAL_COMPILATION"]
    assert exc.value.detail["pre_provider"] == {
        "provider_calls": 0,
        "credit_spend": False,
    }


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("selected_candidate_id", None, "SELECTED_CANDIDATE_ID_REQUIRED"),
        ("approval_state", "PENDING", "APPROVAL_STATE_MUST_BE_APPROVED"),
        ("final_prompt_hash", None, "FINAL_PROMPT_HASH_REQUIRED"),
        ("dispatch_gate", "FAIL", "BOT2_DISPATCH_GATE_NOT_PASSED"),
        ("maximum_provider_operations", None, "GUIDED_FACTORY_SINGLE_OUTPUT_REQUIRED"),
    ],
)
def test_guided_factory_required_dispatch_fields_fail_closed(field, value, blocker):
    with pytest.raises(HTTPException) as exc:
        _run(flow.generate(_guided_factory_request(**{field: value})))

    assert exc.value.status_code == 409
    assert blocker in exc.value.detail["blockers"]
    assert exc.value.detail["pre_provider"]["provider_calls"] == 0
    assert exc.value.detail["pre_provider"]["credit_spend"] is False


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


def test_make_video_existing_still_uses_canonical_start_generate(monkeypatch):
    calls = {}

    class _C:
        connected = True

    async def fake_start_generate(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"job_id": "g_existing", "status": "SUBMITTED"}

    async def forbidden_start_on_existing(*_args, **_kwargs):
        pytest.fail("/make-video-existing used the retired service")

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)
    monkeypatch.setattr(mv, "start_on_existing", forbidden_start_on_existing)

    result = _run(flow.make_video_existing(flow.MakeVideoExistingRequest(
        project_id="project-1", image_media_id="image-1", prompt="animate",
    )))
    assert result["job_id"] == "g_existing"
    assert calls["args"][:2] == ("I2V", "animate")
    assert calls["kwargs"]["project_id"] == "project-1"
    assert calls["kwargs"]["image_media_ids"] == ["image-1"]


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


def test_negotiate_job_reuses_reference_media_without_start_frame(monkeypatch):
    calls = {}

    class _C:
        connected = True

    async def fake_start_negotiate(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"job_id": "n_reference_dry", "status": "SUBMITTED"}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv
    monkeypatch.setattr(mv, "start_negotiate", fake_start_negotiate)

    result = _run(flow.negotiate_job(flow.NegotiateJobRequest(
        prompt="AQUABLANCE creative prompt",
        project_id="flow-project",
        reference_media_ids=["flow-ref-1"],
        model="omni_flash",
        duration_s=10,
        dry=True,
    )))
    assert result["job_id"] == "n_reference_dry"
    assert calls["args"][2] is True
    assert calls["kwargs"] == {
        "model": "omni_flash",
        "duration_s": 10,
        "project_id": "flow-project",
        "reference_media_ids": ["flow-ref-1"],
    }


def test_negotiate_job_rejects_ambiguous_reference_inputs(monkeypatch):
    class _C:
        connected = True

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    try:
        _run(flow.negotiate_job(flow.NegotiateJobRequest(
            prompt="x", image_prompt="new image", reference_media_ids=["ref-1"]
        )))
        assert False, "expected HTTPException 422"
    except HTTPException as exc:
        assert exc.status_code == 422
        assert "ambiguous" in str(exc.detail).lower()


def test_generate_busy_response_preserves_error_and_exposes_active_job(monkeypatch):
    class _C:
        connected = True

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

    async def fake_start_generate(*args, **kwargs):
        return {
            "status": "REJECTED",
            "error": "VIDEO_JOB_IN_FLIGHT",
            "active_job": "g_existing123",
        }

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    response = _run(flow.generate(flow.GenerateRequest(mode="T2V", prompt="safe prompt")))
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload == {
        "detail": "VIDEO_JOB_IN_FLIGHT",
        "error": "VIDEO_JOB_IN_FLIGHT",
        "active_job": "g_existing123",
    }


def test_generate_reference_rejection_exposes_routing_receipt(monkeypatch):
    class _C:
        connected = True

        async def get_credits(self):
            return {"data": {"userPaygateTier": "PAYGATE_TIER_ONE"}}

    receipt = {
        "logical_mode": "F2V",
        "selected_execution_route": "BLOCKED_REFERENCE_ROUTE",
        "text_only_allowed": False,
        "TEXT_ONLY_TOOL_ALLOWED": False,
        "reference_media_ids": ["ref-1"],
    }

    async def fake_start_generate(*args, **kwargs):
        return {
            "status": "REJECTED",
            "error": "ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL",
            "detail": "blocked before provider approval",
            "routing_receipt": receipt,
        }

    monkeypatch.setattr(flow, "get_flow_client", lambda: _C())
    from agent.services import make_video as mv
    from agent.services import copy_execution_resolver as cer
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    async def fake_resolve(*args, **kwargs):
        return None

    monkeypatch.setattr(cer, "resolve_persisted_copy_execution_binding", fake_resolve)

    response = _run(flow.generate(flow.GenerateRequest(mode="T2V", prompt="safe prompt")))
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"] == "ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL"
    assert payload["detail"] == "blocked before provider approval"
    assert payload["routing_receipt"] == receipt


def test_generate_blocks_stale_creator_byline_package_before_provider(monkeypatch):
    calls = {"start_generate": 0}

    async def fake_get_product(product_id):
        assert product_id == "product-sambal"
        return {
            "id": product_id,
            "product_display_name": "Sambal Nyet Berapi by Khairulaming",
            "shop_name": "khairulamingbrand",
        }

    async def fake_start_generate(*args, **kwargs):
        calls["start_generate"] += 1
        return {"job_id": "must-not-run"}

    monkeypatch.setattr(flow.crud, "get_product", fake_get_product)
    from agent.services import make_video as mv
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)

    try:
        _run(flow.generate(flow.GenerateRequest(
            mode="F2V",
            prompt="Show Sambal Nyet Berapi by Khairulaming in a kitchen.",
            product_id="product-sambal",
        )))
        assert False, "expected stale provider-safety package rejection"
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail == "ERR_PROVIDER_SAFETY_PACKAGE_STALE_RECOMPILE_REQUIRED"
    assert calls["start_generate"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
