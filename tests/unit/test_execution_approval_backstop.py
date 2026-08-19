"""Exhaustive provider-boundary backstop — the FlowClient net that closes every
credit-bearing video-dispatch bypass (Native Extend, Direct Capture, the ungated
primitive routes). Provider-free: no real HTTP, no credit.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.services import execution_approval_service as eas
from agent.services.flow_client import FlowClient


_ASSET = "550e8400-e29b-41d4-a716-446655440000"


def _spec(prompt: str, **ov):
    d = dict(surface="hybrid", logical_mode="F2V", final_prompt_text=prompt,
             product_id="prod_bs_1", source_mode="HYBRID", model="Veo 3.1 Lite",
             aspect="9:16", duration_s=8, count=1, asset_media_ids=[_ASSET])
    d.update(ov)
    return d


def _dispatch(prompt: str, **ov):
    d = dict(mode="F2V", final_prompt_text=prompt, source_mode="HYBRID",
             model="Veo 3.1 Lite", aspect="9:16", duration_s=8, count=1,
             asset_media_ids=[_ASSET])
    d.update(ov)
    return d


def _video_send_params():
    return {"url": "https://labs.google/fx/api/video:batchAsyncGenerateVideo",
            "method": "POST", "headers": {}, "body": {},
            "captchaAction": "VIDEO_GENERATION"}


# --------------------------------------------------------------------------- #
# Service-level backstop verdict
# --------------------------------------------------------------------------- #

def test_reason_none_when_not_enforced(monkeypatch):
    monkeypatch.delenv("EXECUTION_APPROVAL_GATE_ENFORCED", raising=False)
    assert eas.video_dispatch_unauthorized_reason(method="generate_video") is None


def test_reason_blocks_when_enforced_and_unauthorized(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas._DISPATCH_AUTH.set(None)  # a fresh dispatch context is unauthorised
    assert (
        eas.video_dispatch_unauthorized_reason(method="generate_video")
        == "PROVIDER_DISPATCH_UNAUTHORIZED"
    )


def test_reason_allows_when_exempt(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas.mark_dispatch_exempt("final-timeline concatenation (assembly, no new gen)")
    assert eas.video_dispatch_unauthorized_reason(method="run_video_concatenation") is None


async def test_reason_allows_after_gate_pass(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "BS_gatepass"
    snap = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    verdict = await eas.verify_and_bind_dispatch(**_dispatch(prompt))
    assert verdict["pass"] is True
    # The passed gate authorised THIS context.
    assert eas.current_dispatch_authorization()["kind"] == "APPROVED"
    assert eas.video_dispatch_unauthorized_reason(method="generate_video") is None


async def test_authorization_propagates_into_created_task(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    prompt = "BS_propagate"
    snap = await eas.create_review_snapshot(**_spec(prompt))
    await eas.approve_snapshot(snap["snapshot_id"], approved_by="faris")
    await eas.verify_and_bind_dispatch(**_dispatch(prompt))

    captured: dict = {}

    async def _child():
        captured["reason"] = eas.video_dispatch_unauthorized_reason(method="generate_video")

    # asyncio.create_task copies the current (authorised) context, exactly as
    # start_generate does before spawning the generation task.
    await asyncio.create_task(_child())
    assert captured["reason"] is None


# --------------------------------------------------------------------------- #
# FlowClient._send integration — the exhaustive boundary
# --------------------------------------------------------------------------- #

async def test_send_blocks_unauthorized_video(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    eas._DISPATCH_AUTH.set(None)  # a fresh dispatch context is unauthorised
    client = FlowClient()
    client._extension_ws = None
    client._mock_connected = True

    result = await client._send("api_request", _video_send_params())
    assert result.get("error") == "PROVIDER_DISPATCH_UNAUTHORIZED"


async def test_send_allows_exempt_video(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    client = FlowClient()
    client._extension_ws = None
    client._mock_connected = True

    eas.mark_dispatch_exempt("test-exempt")
    result = await client._send("api_request", _video_send_params())
    # Falls through the backstop to the mock transport; not the gate block.
    assert result.get("error") != "PROVIDER_DISPATCH_UNAUTHORIZED"


async def test_send_never_blocks_image(monkeypatch):
    monkeypatch.setenv("EXECUTION_APPROVAL_GATE_ENFORCED", "1")
    client = FlowClient()
    client._extension_ws = None
    client._mock_connected = True

    # Image generation is credit-free and uses IMAGE_GENERATION — never gated.
    params = {"url": "https://labs.google/fx/api/image:generate", "method": "POST",
              "headers": {}, "body": {}, "captchaAction": "IMAGE_GENERATION"}
    result = await client._send("api_request", params)
    assert result.get("error") != "PROVIDER_DISPATCH_UNAUTHORIZED"
