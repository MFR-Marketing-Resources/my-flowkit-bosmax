"""Unit tests for the flag-gated DIRECT API-first video lane (ADR-007 recommit).

Pure logic — no network, no credits. Exercises:
  * _direct_lane_plan eligibility (fail-closed: decline reasons, never a silent
    downgrade of model/count/duration/aspect);
  * start_generate routing (reference flag off -> pre-approval rejection;
    eligible -> direct lane; pure T2V -> agent lane with an explicit receipt);
  * flow_client builder contract for the direct submits (videoModelKey override,
    explicit seed, models.json default resolution, fail-closed unknown slots);
  * the DOM-free submit -> poll -> retrieve -> persist pipeline end to end via a
    fake client (DONE + generated_artifact registration + lane release);
  * honest failure classification (render FAILED vs poll timeout ->
    GENERATED_BUT_UNRETRIEVED with re-pollable operations);
  * the flag-gated live-capture entrypoint (raw submit response + background
    retrieval).
"""
import asyncio
import base64

import agent.services.make_video as mv
from agent.services.flow_client import FlowClient, resolve_video_model_key
from agent.services import video_execution_profile_service as profiles

_MID = "11111111-2222-3333-4444-555555555555"
_VBYTES = b"\x00\x00\x00\x18ftypmp42" + b"x" * 64


def _run(coro):
    return asyncio.run(coro)


def _reset_lane():
    mv._JOBS.clear()
    mv._VIDEO_LANE_JOB = None


def _plan(**kw):
    args = {"mode": "F2V", "source_mode": "HYBRID", "model": None,
            "duration_s": None, "aspect": "9:16", "ref_count": 1,
            "num_videos": 1, "require_flag": False}
    args.update(kw)
    return mv._direct_lane_plan(**args)


def _seed_direct_profile_certification(monkeypatch):
    """Fixture the shared 8s direct profile; never mutates repository proof."""
    profile = profiles.resolve_duration_model_profile(
        model="veo_3_1_lite",
        duration_s=8,
        aspect_ratio="9:16",
        provider_transport_key_provenance="direct_video_model_keys[veo_3_1_lite]",
        transport_route="GOOGLE_FLOW_DIRECT:reference_frame_2_video:VIDEO_ASPECT_RATIO_PORTRAIT",
        logical_mode="F2V",
        source_mode="HYBRID",
    )
    monkeypatch.setitem(
        profiles.PROVIDER_CERTIFICATION_PROFILES,
        profile["profile_digest"],
        {"profile_digest": profile["profile_digest"], "status": "CERTIFIED"},
    )


class _FakeDirectClient:
    """Successful direct-lane provider: submit -> pending op -> successful poll
    with mediaId in the poll's own metadata -> get_media bytes."""

    def __init__(self, fail_render=False, never_finish=False):
        self.calls = []
        self.fail_render = fail_render
        self.never_finish = never_finish

    async def generate_video_from_references(self, reference_media_ids, prompt,
                                             project_id, scene_id, **kw):
        self.calls.append(("r2v", reference_media_ids, kw))
        return {"data": {"operations": [
            {"operation": {"name": "op-r2v-1"},
             "status": "MEDIA_GENERATION_STATUS_PENDING"}]}}

    async def generate_video(self, start_image_media_id, prompt, project_id,
                             scene_id, **kw):
        self.calls.append(("start_frame", start_image_media_id, kw))
        return {"data": {"operations": [
            {"operation": {"name": "op-i2v-1"},
             "status": "MEDIA_GENERATION_STATUS_PENDING"}]}}

    async def check_video_status(self, operations):
        self.calls.append(("poll", [o.get("operation", {}).get("name")
                                    for o in operations]))
        if self.never_finish:
            return {"data": {"operations": [
                {"operation": {"name": "op-r2v-1"},
                 "status": "MEDIA_GENERATION_STATUS_PENDING"}]}}
        if self.fail_render:
            return {"data": {"operations": [
                {"operation": {"name": "op-r2v-1"},
                 "status": "MEDIA_GENERATION_STATUS_FAILED"}]}}
        return {"data": {"operations": [
            {"operation": {"name": "op-r2v-1",
                           "metadata": {"video": {
                               "mediaId": _MID,
                               # untrusted host -> forces the get_media fallback
                               "fifeUrl": "https://example.invalid/v/" + _MID}}},
             "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}]}}

    async def get_media(self, media_id, media_generation_id=None):
        self.calls.append(("get_media", media_id))
        return {"status": 200, "data": {"name": media_id, "video": {
            "encodedVideo": base64.b64encode(_VBYTES).decode()}}}


class _FakeCurrentMediaDirectClient(_FakeDirectClient):
    """Current Flow response: submit exposes media/workflows, then media polling."""

    def __init__(self):
        super().__init__()
        self.media_poll_count = 0

    async def generate_video_from_references(self, reference_media_ids, prompt,
                                             project_id, scene_id, **kw):
        self.calls.append(("r2v", reference_media_ids, kw))
        return {"status": 200, "data": {
            "workflows": [{"name": "workflow-1", "metadata": {
                "primaryMediaId": _MID, "batchId": "batch-1"}}],
            "media": [{"name": _MID, "projectId": project_id,
                        "workflowId": "workflow-1",
                        "mediaMetadata": {"mediaStatus": {
                            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SCHEDULED"}},
                        "video": {"generatedVideo": {
                            "model": "veo_3_1_r2v_fast_portrait"}}}],
            "remainingCredits": 1767,
        }}

    async def check_video_status_by_media(self, targets):
        self.media_poll_count += 1
        self.calls.append(("media_poll", [t["name"] for t in targets]))
        status = ("MEDIA_GENERATION_STATUS_SCHEDULED"
                  if self.media_poll_count == 1
                  else "MEDIA_GENERATION_STATUS_SUCCESSFUL")
        return {"data": {"media": [{"name": _MID,
            "mediaMetadata": {"mediaStatus": {
                "mediaGenerationStatus": status}},
            "video": {"generatedVideo": {
                "fifeUrl": "https://example.invalid/v/" + _MID}}}]}}


def _patch_direct_runtime(monkeypatch, tmp_path, client):
    """Common patches: fake client, tmp output dir, instant polling, recorded
    artifact persistence. Returns the list of insert_generated_artifact kwargs."""
    import agent.db.crud as crud
    import agent.sdk.services.operations as sdk_ops
    recorded = []

    async def fake_insert(**kw):
        recorded.append(kw)

    monkeypatch.setattr(mv, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(sdk_ops, "VIDEO_POLL_INTERVAL", 0)
    monkeypatch.setattr(mv, "_direct_poll_timeout", lambda: 3)
    monkeypatch.setattr(crud, "insert_generated_artifact", fake_insert)
    return recorded


# ── eligibility plan (fail-closed) ──────────────────────────────────────────

def test_plan_flag_off_declines(monkeypatch):
    monkeypatch.delenv("DIRECT_VIDEO_LANE_ENABLED", raising=False)
    p = _plan(require_flag=True)
    assert p == {"eligible": False, "reason": "DIRECT_LANE_DISABLED"}


def test_plan_t2v_has_no_direct_rpc():
    assert _plan(mode="T2V", source_mode=None, ref_count=0)["reason"] == "NO_DIRECT_T2V_RPC"


def test_plan_unknown_aspect_declines():
    assert _plan(aspect="4:3")["reason"].startswith("DIRECT_ASPECT_UNSUPPORTED")


def test_plan_multi_count_declines_never_clamps():
    assert _plan(num_videos=2)["reason"] == "DIRECT_COUNT_UNPROVEN"


def test_plan_needs_a_reference():
    assert _plan(ref_count=0)["reason"] == "DIRECT_NEEDS_REFERENCE"


def test_plan_hybrid_composes_references():
    p = _plan(mode="F2V", source_mode="HYBRID", ref_count=1)
    assert p["eligible"] and p["rpc"] == "r2v"
    assert p["gen_type"] == "reference_frame_2_video"
    assert p["aspect_enum"] == "VIDEO_ASPECT_RATIO_PORTRAIT"


def test_plan_frames_anchor_start_end():
    one = _plan(mode="F2V", source_mode="FRAMES", ref_count=1)
    two = _plan(mode="F2V", source_mode="FRAMES", ref_count=2)
    assert one["eligible"] and one["rpc"] == "start_frame"
    assert one["gen_type"] == "frame_2_video"
    assert two["eligible"] and two["gen_type"] == "start_end_frame_2_video"


def test_plan_f2v_without_source_mode_declines():
    # Bulk/queue lanes do not thread source_mode; a logical-HYBRID job routed to
    # the start-frame RPC would change semantics — fail-safe to the agent lane.
    p = _plan(mode="F2V", source_mode=None, ref_count=1)
    assert p["reason"] == "DIRECT_F2V_SOURCE_MODE_UNKNOWN"


def test_plan_i2v_ingredients_compose_references():
    p = _plan(mode="I2V", source_mode="INGREDIENTS", ref_count=3, aspect="16:9")
    assert p["eligible"] and p["rpc"] == "r2v"
    assert p["aspect_enum"] == "VIDEO_ASPECT_RATIO_LANDSCAPE"


def test_plan_explicit_model_without_captured_key_declines():
    # USER SETTINGS ARE LAW: an explicit model with no captured direct key must
    # decline to the agent lane (which honors it), never fire a different key.
    p = _plan(model="Veo 3.1 - Lite")
    assert p["reason"] == "DIRECT_MODEL_KEY_UNPROVEN:veo_3_1_lite"


def test_plan_explicit_model_with_captured_key_is_eligible(monkeypatch):
    monkeypatch.setitem(
        mv.DIRECT_VIDEO_MODEL_KEYS, "veo_3_1_lite",
            {"reference_frame_2_video": {"VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_r2v_lite"}})
    _seed_direct_profile_certification(monkeypatch)
    p = _plan(model="veo_3_1_lite")
    assert p["eligible"] and p["video_model_key"] == "veo_3_1_r2v_lite"
    assert "direct_video_model_keys" in p["model_key_source"]


def test_plan_captured_key_without_shared_profile_proof_declines(monkeypatch):
    monkeypatch.setitem(
        mv.DIRECT_VIDEO_MODEL_KEYS, "veo_3_1_lite",
        {"reference_frame_2_video": {"VIDEO_ASPECT_RATIO_PORTRAIT": "veo_3_1_r2v_lite"}})
    p = _plan(model="veo_3_1_lite")
    assert p["eligible"] is False
    assert p["reason"] == "DIRECT_PROFILE_UNCERTIFIED:NO_PROVIDER_CERTIFICATION_FOR_PROFILE"


def test_plan_unknown_model_declines_to_canonical_fail_closed():
    assert _plan(model="veo 9000")["reason"] == "DIRECT_MODEL_UNKNOWN:veo 9000"


def test_plan_duration_only_default_8s():
    assert _plan(duration_s=8)["eligible"]
    assert _plan(duration_s=16)["reason"] == "DIRECT_DURATION_UNPROVEN:16"


# ── flow_client direct-submit builder contract ──────────────────────────────

def _capture_client():
    client = FlowClient()
    captured = {}

    async def fake_send(method, params, timeout=60):
        captured["method"] = method
        captured["params"] = params
        return {"ok": True}

    client._send = fake_send
    return client, captured


def test_r2v_builder_honors_override_key_and_seed():
    client, cap = _capture_client()
    _run(client.generate_video_from_references(
        ["m1", "m2"], "the prompt", "pid", "sid",
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        user_paygate_tier="PAYGATE_TIER_TWO",
        video_model_key="captured_key_x", seed=4242))
    assert cap["method"] == "api_request"
    assert "batchAsyncGenerateVideoReferenceImages" in cap["params"]["url"]
    assert cap["params"]["captchaAction"] == "VIDEO_GENERATION"
    req = cap["params"]["body"]["requests"][0]
    assert req["videoModelKey"] == "captured_key_x"
    assert req["seed"] == 4242
    assert [r["mediaId"] for r in req["referenceImages"]] == ["m1", "m2"]


def test_r2v_builder_default_key_comes_from_models_json():
    client, cap = _capture_client()
    _run(client.generate_video_from_references(
        ["m1"], "p", "pid", "sid",
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        user_paygate_tier="PAYGATE_TIER_TWO"))
    req = cap["params"]["body"]["requests"][0]
    assert req["videoModelKey"] == "veo_3_1_r2v_fast_landscape_ultra_relaxed"


def test_start_frame_builder_end_image_switches_endpoint_and_key():
    client, cap = _capture_client()
    _run(client.generate_video(
        "start-m", "p", "pid", "sid",
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        end_image_media_id="end-m", user_paygate_tier="PAYGATE_TIER_ONE",
        seed=7))
    assert "batchAsyncGenerateVideoStartAndEndImage" in cap["params"]["url"]
    req = cap["params"]["body"]["requests"][0]
    assert req["videoModelKey"] == "veo_3_1_i2v_s_fast_portrait_fl"
    assert req["seed"] == 7
    assert req["startImage"] == {"mediaId": "start-m"}
    assert req["endImage"] == {"mediaId": "end-m"}


def test_builder_fails_closed_on_unknown_slot_without_firing():
    client, cap = _capture_client()
    res = _run(client.generate_video_from_references(
        ["m1"], "p", "pid", "sid", aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        user_paygate_tier="PAYGATE_TIER_NINE"))
    assert res.get("error", "").startswith("No model for tier=PAYGATE_TIER_NINE")
    assert "method" not in cap  # nothing was sent


def test_resolve_video_model_key_override_wins_and_uncaptured_is_none():
    assert resolve_video_model_key("PAYGATE_TIER_TWO", "reference_frame_2_video",
                                   "VIDEO_ASPECT_RATIO_PORTRAIT",
                                   override="key_y") == "key_y"
    assert resolve_video_model_key("PAYGATE_TIER_TWO", "reference_frame_2_video",
                                   "VIDEO_ASPECT_RATIO_PORTRAIT") \
        == "veo_3_1_r2v_fast_landscape_ultra_relaxed"
    assert resolve_video_model_key("NOPE", "reference_frame_2_video",
                                   "VIDEO_ASPECT_RATIO_PORTRAIT") is None


# ── start_generate routing ──────────────────────────────────────────────────

def test_reference_routing_flag_off_rejects_before_agent_lane(monkeypatch):
    _reset_lane()
    monkeypatch.delenv("DIRECT_VIDEO_LANE_ENABLED", raising=False)
    ran = {}
    approval_calls = []

    async def fake_agent_run(job_id, *a, **kw):
        ran["agent"] = job_id

    monkeypatch.setattr(mv, "_run_generate", fake_agent_run)

    async def fake_approval(**kwargs):
        approval_calls.append(kwargs)

    from agent.services import execution_approval_service as eas
    monkeypatch.setattr(eas, "verify_and_bind_dispatch", fake_approval)

    async def go():
        return await mv.start_generate(
            "F2V", "p", project_id="pid",
            image_media_ids=["m1"], source_mode="HYBRID",
        )

    res = _run(go())
    assert res["status"] == "REJECTED"
    assert res["error"] == mv.ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL
    receipt = res["routing_receipt"]
    assert receipt["logical_mode"] == "F2V"
    assert receipt["source_mode"] == "HYBRID"
    assert receipt["has_reference"] is True
    assert receipt["reference_requested"] is True
    assert receipt["reference_uploaded"] is True
    assert receipt["reference_count"] == 1
    assert receipt["reference_media_ids"] == ["m1"]
    assert len(receipt["reference_fingerprint"]) == 64
    assert receipt["reference_contract"] == "valid"
    assert receipt["selected_execution_route"] == "BLOCKED_REFERENCE_ROUTE"
    assert receipt["text_only_allowed"] is False
    assert receipt["TEXT_ONLY_TOOL_ALLOWED"] is False
    assert receipt["approval_allowed"] is False
    assert receipt["reference_mode_authorized"] is False
    assert not ran
    assert not approval_calls
    assert not mv._JOBS
    _reset_lane()


def test_captured_faceless_incident_cannot_approve_text_only_fallback(monkeypatch):
    """Exact MWCB shape: reference + HYBRID + Veo Lite 8s is pre-paid blocked."""
    _reset_lane()
    monkeypatch.delenv("DIRECT_VIDEO_LANE_ENABLED", raising=False)
    agent_calls = []

    async def fake_agent_run(*args, **kwargs):
        agent_calls.append(args)

    async def fake_negotiate(*args, **kwargs):
        raise AssertionError("reference incident must not enter agent negotiation")

    monkeypatch.setattr(mv, "_run_generate", fake_agent_run)
    monkeypatch.setattr(mv.agent_video, "negotiate_and_generate", fake_negotiate)

    result = _run(
        mv.start_generate(
            "F2V",
            "MWCB Faceless AUTO AESTHETIC_TABLE product video",
            project_id="mwcb-project",
            image_media_ids=["mwcb-reference-media-id"],
            source_mode="HYBRID",
            model="Veo 3.1 Lite",
            duration_s=8,
            product_id="MWCB",
        )
    )

    assert result["status"] == "REJECTED"
    assert result["error"] == mv.ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL
    assert result["routing_receipt"]["reference_media_ids"] == [
        "mwcb-reference-media-id"
    ]
    assert result["routing_receipt"]["route_reason"] == "DIRECT_LANE_DISABLED"
    assert result["routing_receipt"]["TEXT_ONLY_TOOL_ALLOWED"] is False
    assert not agent_calls
    assert not mv._JOBS
    _reset_lane()


def test_reference_modes_never_fall_back_to_agent(monkeypatch):
    _reset_lane()
    monkeypatch.delenv("DIRECT_VIDEO_LANE_ENABLED", raising=False)
    agent_calls = []

    async def fake_agent_run(*args, **kwargs):
        agent_calls.append(args)

    monkeypatch.setattr(mv, "_run_generate", fake_agent_run)

    async def go():
        return [
            await mv.start_generate(
                mode, "p", image_media_ids=refs, source_mode=source,
            )
            for mode, source, refs in (
                ("F2V", "HYBRID", ["product-ref"]),
                ("F2V", "FRAMES", ["start-ref", "end-ref"]),
                ("I2V", "INGREDIENTS", ["ingredient-a", "ingredient-b"]),
            )
        ]

    results = _run(go())
    assert all(result["status"] == "REJECTED" for result in results)
    assert all(
        result["error"] == mv.ERR_REFERENCE_ROUTE_NOT_PROVEN_PRE_APPROVAL
        for result in results
    )
    assert [result["routing_receipt"]["reference_count"] for result in results] == [1, 2, 2]
    assert all(
        result["routing_receipt"]["TEXT_ONLY_TOOL_ALLOWED"] is False
        for result in results
    )
    assert not agent_calls
    assert not mv._JOBS
    _reset_lane()


def test_routing_flag_on_eligible_takes_direct_lane(monkeypatch):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_LANE_ENABLED", "1")
    ran = {}

    async def fake_direct_run(job_id, *a, **kw):
        ran["direct"] = job_id

    monkeypatch.setattr(mv, "_run_generate_direct", fake_direct_run)

    async def go():
        res = await mv.start_generate("F2V", "p", project_id="pid",
                                      image_media_ids=["m1"], source_mode="HYBRID")
        await mv._JOBS[res["job_id"]]["_task"]
        return res

    res = _run(go())
    assert res["lane"] == "DIRECT_API"
    assert ran["direct"] == res["job_id"]
    assert mv._JOBS[res["job_id"]]["source_mode"] == "HYBRID"
    receipt = res["routing_receipt"]
    assert receipt["selected_execution_route"] == "DIRECT_API"
    assert receipt["reference_media_ids"] == ["m1"]
    assert receipt["reference_mode_authorized"] is True
    assert receipt["text_only_allowed"] is False
    assert receipt["approval_allowed"] is True
    _reset_lane()


def test_routing_flag_on_declined_records_reason(monkeypatch):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_LANE_ENABLED", "1")

    async def fake_agent_run(job_id, *a, **kw):
        pass

    monkeypatch.setattr(mv, "_run_generate", fake_agent_run)

    async def go():
        res = await mv.start_generate("T2V", "p", project_id="pid")
        await mv._JOBS[res["job_id"]]["_task"]
        return res

    res = _run(go())
    assert res["lane"] == "AGENT"
    assert mv._JOBS[res["job_id"]]["direct_decline_reason"] == "NO_DIRECT_T2V_RPC"
    receipt = res["routing_receipt"]
    assert receipt["logical_mode"] == "T2V"
    assert receipt["reference_requested"] is False
    assert receipt["reference_media_ids"] == []
    assert receipt["text_only_allowed"] is True
    assert receipt["TEXT_ONLY_TOOL_ALLOWED"] is True
    assert receipt["approval_allowed"] is True
    _reset_lane()


def test_exact_product_t2v_scaffold_passes_custody_guard_before_provider(monkeypatch):
    """Exact Product T2V uses the server-owned scaffold contract, not R2V."""
    _reset_lane()
    custody = {
        "exact_product_required": True,
        "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
        "generation_type": "scene_video_scaffold_then_deterministic_composite",
    }
    ran = {}

    async def fake_approval(**_kwargs):
        return None

    async def fake_prepare(*_args, **_kwargs):
        return None, True

    async def fake_run(*args, **_kwargs):
        ran["called"] = True

    async def fake_lease(_job_id):
        return None

    monkeypatch.setattr(
        "agent.services.execution_approval_service.verify_and_bind_dispatch",
        fake_approval,
    )
    monkeypatch.setattr(mv, "_prepare_durable_single_job", fake_prepare)
    monkeypatch.setattr(mv, "_run_generate", fake_run)
    monkeypatch.setattr(
        "agent.db.crud.acquire_video_generation_lane_lease",
        fake_lease,
    )

    async def go():
        result = await mv.start_generate(
            "T2V",
            "scene-only scaffold",
            project_id="project-exact",
            image_media_ids=[],
            source_mode="T2V",
            model="Veo 3.1 Lite",
            duration_s=8,
            product_visual_custody=custody,
        )
        await mv._JOBS[result["job_id"]]["_task"]
        return result

    result = _run(go())
    assert result["status"] == "SUBMITTED"
    assert result["lane"] == "AGENT"
    assert result["routing_receipt"]["scene_scaffold_route"] == "AGENT_T2V"
    assert result["routing_receipt"]["provider_product_reference_forbidden"] is True
    assert ran["called"] is True
    _reset_lane()


# ── the DOM-free pipeline end to end ────────────────────────────────────────

def test_direct_lane_end_to_end_done_and_persisted(monkeypatch, tmp_path):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_LANE_ENABLED", "1")
    client = _FakeDirectClient()
    recorded = _patch_direct_runtime(monkeypatch, tmp_path, client)

    async def go():
        res = await mv.start_generate(
            "F2V", "the prompt", project_id="pid-1", image_media_ids=["ref-1"],
            aspect="9:16", tier="PAYGATE_TIER_TWO", source_mode="HYBRID")
        assert res["lane"] == "DIRECT_API"
        await mv._JOBS[res["job_id"]]["_task"]
        return mv.get_job(res["job_id"])

    job = _run(go())
    assert job["status"] == "DONE"
    assert job["artifact"] == "video"
    assert job["media_id"] == _MID
    assert job["approved"] is True
    assert job["lane"] == "DIRECT_API"
    assert job["provider_operation_ids"] == ["op-r2v-1"]
    assert job["credit_state"] == "MAY_HAVE_SPENT"
    assert job["routing_receipt"]["reference_media_ids"] == ["ref-1"]
    assert client.calls[0][1] == ["ref-1"]
    # bytes on disk, from the get_media fallback (untrusted fifeUrl host skipped)
    saved = tmp_path / "retrieved" / f"{_MID}.mp4"
    assert saved.read_bytes() == _VBYTES
    corr = job["artifacts"][0]["correlation"]
    assert corr["matched_on"] == "operation_handle"
    assert corr["operation_name"] == "op-r2v-1"
    assert corr["retrieval_source"] == "get_media"
    # generated_artifact persisted -> Library + Results surfaces
    assert len(recorded) == 1
    assert recorded[0]["media_id"] == _MID
    assert recorded[0]["artifact_kind"] == "video"
    assert recorded[0]["model_used"] == "veo_3_1_r2v_fast_landscape_ultra_relaxed"
    # single-flight lane released
    assert mv._VIDEO_LANE_JOB is None
    # the fired RPC was the HYBRID reference composition
    assert client.calls[0][0] == "r2v"
    _reset_lane()


def test_direct_lane_render_failed_is_honest(monkeypatch, tmp_path):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_LANE_ENABLED", "1")
    client = _FakeDirectClient(fail_render=True)
    recorded = _patch_direct_runtime(monkeypatch, tmp_path, client)

    async def go():
        res = await mv.start_generate(
            "F2V", "p", project_id="pid-1", image_media_ids=["ref-1"],
            source_mode="HYBRID", tier="PAYGATE_TIER_TWO")
        await mv._JOBS[res["job_id"]]["_task"]
        return mv.get_job(res["job_id"])

    job = _run(go())
    assert job["status"] == "FAILED"
    assert "DIRECT_RENDER_FAILED" in job["error"]
    assert job["credit_state"] == "MAY_HAVE_SPENT"  # submit was accepted
    assert not recorded
    assert mv._VIDEO_LANE_JOB is None
    _reset_lane()


def test_direct_lane_poll_timeout_is_generated_but_unretrieved(monkeypatch, tmp_path):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_LANE_ENABLED", "1")
    client = _FakeDirectClient(never_finish=True)
    _patch_direct_runtime(monkeypatch, tmp_path, client)
    import agent.sdk.services.operations as sdk_ops
    monkeypatch.setattr(sdk_ops, "VIDEO_POLL_INTERVAL", 1)
    monkeypatch.setattr(mv, "_direct_poll_timeout", lambda: 1)

    async def go():
        res = await mv.start_generate(
            "F2V", "p", project_id="pid-1", image_media_ids=["ref-1"],
            source_mode="HYBRID", tier="PAYGATE_TIER_TWO")
        await mv._JOBS[res["job_id"]]["_task"]
        return mv.get_job(res["job_id"])

    job = _run(go())
    # A paid, possibly-finished render must NEVER be reported as plain FAILED.
    assert job["status"] == "GENERATED_BUT_UNRETRIEVED"
    assert job["provider_operation_ids"] == ["op-r2v-1"]  # re-pollable recovery
    assert job["credit_state"] == "MAY_HAVE_SPENT"
    assert mv._VIDEO_LANE_JOB is None
    _reset_lane()


# ── live-capture entrypoint ─────────────────────────────────────────────────

def test_capture_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DIRECT_VIDEO_CAPTURE_ENABLED", raising=False)
    res = _run(mv.start_direct_capture("F2V", "p", "pid", ["m1"]))
    assert res["ok"] is False and "DIRECT_CAPTURE_DISABLED" in res["error"]


def test_capture_requires_explicit_credit_confirmation(monkeypatch):
    monkeypatch.setenv("DIRECT_VIDEO_CAPTURE_ENABLED", "1")
    res = _run(mv.start_direct_capture("F2V", "p", "pid", ["m1"]))
    assert res["ok"] is False
    assert "DIRECT_CAPTURE_CONFIRMATION_REQUIRED" in res["error"]


def test_capture_returns_raw_submit_and_retrieves_in_background(monkeypatch, tmp_path):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_CAPTURE_ENABLED", "1")
    client = _FakeDirectClient()
    recorded = _patch_direct_runtime(monkeypatch, tmp_path, client)

    async def go():
        res = await mv.start_direct_capture(
            "F2V", "p", "pid-1", ["ref-1"], aspect="9:16",
            tier="PAYGATE_TIER_TWO", source_mode="HYBRID",
            confirm_live_credit_burn=True)
        assert res["ok"] is True
        assert res["operations"] == ["op-r2v-1"]
        assert res["submit_response"]["data"]["operations"]  # RAW contract capture
        assert res["fired"]["video_model_key"] == "veo_3_1_r2v_fast_landscape_ultra_relaxed"
        await mv._JOBS[res["job_id"]]["_task"]
        return mv.get_job(res["job_id"])

    job = _run(go())
    assert job["status"] == "DONE"
    assert job["lane"] == "DIRECT_CAPTURE"
    assert len(recorded) == 1 and recorded[0]["media_id"] == _MID
    assert mv._VIDEO_LANE_JOB is None
    _reset_lane()


def test_capture_current_media_submit_contract_polls_without_second_submit(
        monkeypatch, tmp_path):
    """The current media/workflow response is accepted and retrieved once."""
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_CAPTURE_ENABLED", "1")
    client = _FakeCurrentMediaDirectClient()
    recorded = _patch_direct_runtime(monkeypatch, tmp_path, client)

    async def go():
        res = await mv.start_direct_capture(
            "F2V", "p", "pid-1", ["ref-1"], aspect="9:16",
            tier="PAYGATE_TIER_TWO", source_mode="HYBRID",
            confirm_live_credit_burn=True)
        assert res["ok"] is True
        assert res["operations"] == [_MID]
        assert res["submit_response"]["data"]["media"]
        await mv._JOBS[res["job_id"]]["_task"]
        return mv.get_job(res["job_id"])

    job = _run(go())
    assert job["status"] == "DONE"
    assert job["approved"] is True
    assert job["credit_state"] == "MAY_HAVE_SPENT"
    assert job["provider_operation_ids"] == [_MID]
    assert job["output_correlation"]["matched_on"] == "media_status"
    assert client.media_poll_count == 2
    assert [c[0] for c in client.calls].count("r2v") == 1
    assert [c[0] for c in client.calls].count("media_poll") == 2
    assert not any(c[0] == "poll" for c in client.calls)
    assert (tmp_path / "retrieved" / f"{_MID}.mp4").read_bytes() == _VBYTES
    assert len(recorded) == 1 and recorded[0]["media_id"] == _MID
    _reset_lane()


def test_current_media_parser_handles_nested_relay_envelope():
    response = {"id": "relay-1", "status": 200, "data": {"status": 200,
        "data": {"workflows": [{"metadata": {
            "primaryMediaId": _MID}}], "media": [{"name": _MID}]}}}
    assert mv._extract_direct_media_targets(response, "pid-1") == [
        {"name": _MID, "projectId": "pid-1"}
    ]


def test_direct_media_recovery_never_calls_provider_submit(monkeypatch, tmp_path):
    _reset_lane()
    client = _FakeCurrentMediaDirectClient()
    _patch_direct_runtime(monkeypatch, tmp_path, client)

    async def go():
        res = await mv.start_direct_media_recovery(
            media_id=_MID, project_id="pid-1", recovery_of="direct_capture_736_live",
            model_key="veo_3_1_r2v_fast_portrait", seed=81989,
            confirm_recovery=True)
        assert res["ok"] is True
        assert res["provider_submit"] is False
        assert res["credit_action"] == "NO_PROVIDER_SUBMIT"
        await mv._JOBS[res["job_id"]]["_task"]
        return mv.get_job(res["job_id"])

    job = _run(go())
    assert job["status"] == "DONE"
    assert job["lane"] == "DIRECT_CAPTURE_RECOVERY"
    assert not any(call[0] == "r2v" for call in client.calls)
    assert client.media_poll_count == 2
    _reset_lane()


def test_capture_forwards_explicit_model_and_duration_after_key_capture(
        monkeypatch, tmp_path):
    _reset_lane()
    monkeypatch.setenv("DIRECT_VIDEO_CAPTURE_ENABLED", "1")
    monkeypatch.setitem(
        mv.DIRECT_VIDEO_MODEL_KEYS, "veo_3_1_lite",
        {"reference_frame_2_video": {
            "VIDEO_ASPECT_RATIO_PORTRAIT": "captured_r2v_portrait"}})
    _seed_direct_profile_certification(monkeypatch)
    client = _FakeDirectClient()
    _patch_direct_runtime(monkeypatch, tmp_path, client)

    async def go():
        res = await mv.start_direct_capture(
            "F2V", "p", "pid-1", ["ref-1"], aspect="9:16",
            tier="PAYGATE_TIER_TWO", source_mode="HYBRID",
            model="veo_3_1_lite", duration_s=8,
            confirm_live_credit_burn=True)
        assert res["ok"] is True
        assert client.calls[0][2]["video_model_key"] == "captured_r2v_portrait"
        assert res["fired"]["model"] == "veo_3_1_lite"
        assert res["fired"]["duration_s"] == 8
        await mv._JOBS[res["job_id"]]["_task"]

    _run(go())
    _reset_lane()
