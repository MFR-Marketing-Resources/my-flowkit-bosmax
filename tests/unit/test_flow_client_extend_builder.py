"""flow_client.generate_video_extend emits the EXACT captured native-Extend
contract (byte-shape parity vs the sanitized fixture), and fails closed."""
import json
import os

from agent.services.flow_client import FlowClient
from agent.services import google_flow_native_extend_runtime as nx

_FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "google_flow_native_extend")


def _load(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return json.load(f)


async def test_extend_builder_matches_captured_contract():
    client = FlowClient()
    captured = {}

    async def fake_send(method, params, timeout=60):
        captured["method"] = method
        captured["params"] = params
        return {"ok": True}

    client._send = fake_send
    await client.generate_video_extend(
        source_operation_id="b6371e69-23d4-4d6e-a874-50dc03fc850a",
        project_id="c6c87bdd-7af2-415b-9826-315d53fc8d9b",
        scene_id="cce593f7-8450-4461-9f82-6b207cfc5857",
        position=1, prompt="FULL STRUCTURED BLOCK PROMPT (block 2 of 2)",
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        start_frame_index=1, end_frame_index=24, seed=11019,
        batch_id="36bf48e5-0ba1-4726-9670-2e4539fd4cdd",
    )
    assert captured["method"] == "api_request"
    p = captured["params"]
    assert "batchAsyncGenerateVideoExtendVideo" in p["url"]
    assert p["captchaAction"] == "VIDEO_GENERATION"
    body = p["body"]
    # the built body must satisfy the captured-contract drift guard
    nx.assert_request_matches_contract(body)

    fixture = _load("extend_request.sanitized.json")
    # structural parity — clientContext is runtime-generated (excluded); prompt +
    # batchId are inputs, compared for shape not literal value.
    assert body["useV2ModelConfig"] is True is fixture["useV2ModelConfig"]
    assert (body["mediaGenerationContext"]["audioFailurePreference"]
            == fixture["mediaGenerationContext"]["audioFailurePreference"]
            == "BLOCK_SILENCED_VIDEOS")
    assert (body["mediaGenerationContext"]["sceneContext"]
            == fixture["mediaGenerationContext"]["sceneContext"])
    br = body["requests"][0]
    fr = fixture["requests"][0]
    assert br["videoModelKey"] == fr["videoModelKey"] == "veo_3_1_extension_lite"
    assert br["videoInput"] == fr["videoInput"]
    assert br["aspectRatio"] == fr["aspectRatio"]
    assert set(br["textInput"]["structuredPrompt"]["parts"][0]) == {"text"}


async def test_extend_builder_fails_closed_on_unknown_aspect():
    client = FlowClient()

    async def fake_send(*a, **k):  # should NOT be reached
        raise AssertionError("must not fire on unknown model")

    client._send = fake_send
    res = await client.generate_video_extend(
        source_operation_id="m", project_id="p", scene_id="s", position=1,
        prompt="x", aspect_ratio="VIDEO_ASPECT_RATIO_SQUARE")
    assert res["error"].startswith("UNKNOWN_EXTEND_MODEL")


async def test_extend_builder_missing_parent():
    client = FlowClient()

    async def fake_send(*a, **k):
        raise AssertionError("must not fire without parent")

    client._send = fake_send
    res = await client.generate_video_extend(
        source_operation_id="", project_id="p", scene_id="s", position=1, prompt="x")
    assert res["error"] == "EXTEND_PARENT_MEDIA_ID_MISSING"


async def test_poll_by_media_uses_media_body_shape():
    client = FlowClient()
    captured = {}

    async def fake_send(method, params, timeout=30):
        captured["params"] = params
        return {"media": []}

    client._send = fake_send
    await client.check_video_status_by_media([{"name": "c", "projectId": "p"}])
    assert captured["params"]["body"] == {"media": [{"name": "c", "projectId": "p"}]}
    assert "batchCheckAsyncVideoGenerationStatus" in captured["params"]["url"]
